"""Video and audio transcription integration.

Extracts spoken audio text from YouTube and social media media to enable
transcript-based relevance evaluation and evidence provenance.

Supports:
1. AI4Bharat IndicConformer 600M Multilingual (Local on-device, 22 Indian languages, MIT license)
2. Local Whisper model (via installed openai-whisper package)
3. Cloud WhisperFlow / OpenAI Whisper API (via API key & HTTP endpoints)
"""
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
from typing import Any, Dict, Optional, Tuple

from app.services.asr import (
    SUPPORTED_INDIC_LANGUAGES,
    get_asr_service,
    is_supported_indic_language,
    normalize_language_code,
)

# Ensure standard Mac Homebrew / Unix binary paths are available for ffmpeg and yt-dlp
for _bin_path in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin", "/bin"):
    if _bin_path not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _bin_path + os.pathsep + os.environ.get("PATH", "")

logger = logging.getLogger("watchtower.transcription")

AVAILABLE_WHISPER_MODELS = ["tiny", "base", "small", "medium"]
DEFAULT_API_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


def is_transcription_available() -> Tuple[bool, str]:
    """Check if any ASR transcription backend is available."""
    # Priority 1: IndicConformer (local 22 Indian languages)
    try:
        service = get_asr_service("indic_conformer")
        avail, reason = service.is_available()
        if avail:
            return True, "indic_conformer"
    except Exception:
        pass

    # Priority 2: Cloud API key
    if os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return True, "whisperflow_api"

    # Priority 3: Local Whisper
    if importlib.util.find_spec("whisper"):
        return True, "whisper"

    return False, "transcription_backend_not_installed"


def get_transcription_status(config: Optional[dict] = None) -> Dict[str, Any]:
    """Return comprehensive status of IndicConformer, local Whisper, and cloud API."""
    config = config or {}
    indic_service = get_asr_service("indic_conformer", config)
    indic_avail, indic_reason = indic_service.is_available()
    indic_caps = indic_service.get_capabilities()

    whisper_installed = importlib.util.find_spec("whisper") is not None
    ffmpeg_installed = shutil.which("ffmpeg") is not None
    api_key = config.get("api_key") or os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    has_api_key = bool(api_key.strip())

    active_provider = config.get("provider")
    if not active_provider:
        if indic_avail:
            active_provider = "indic_conformer"
        elif has_api_key:
            active_provider = "whisperflow_api"
        elif whisper_installed:
            active_provider = "whisper"
        else:
            active_provider = "not_configured"

    selected_model = config.get("model", "indic-conformer-600m" if active_provider == "indic_conformer" else "base")
    selected_language = config.get("language", "hi")
    selected_decoder = config.get("decoder", "rnnt")
    auto_transcribe = bool(config.get("auto_transcribe", False))

    notes = []
    if indic_avail:
        notes.append(
            f"AI4Bharat IndicConformer 600M ready on device '{indic_caps.get('device', 'cpu')}'. "
            f"Full on-device support for 22 scheduled Indian languages (verbatim native script)."
        )
    if whisper_installed and ffmpeg_installed:
        notes.append("Local OpenAI Whisper engine and ffmpeg are ready.")
    elif whisper_installed and not ffmpeg_installed:
        notes.append("Local Whisper is installed, but ffmpeg binary is missing. Install with 'brew install ffmpeg'.")
    if has_api_key:
        notes.append("Cloud WhisperFlow API is configured.")

    return {
        "available": indic_avail or whisper_installed or has_api_key,
        "local_installed": indic_avail or whisper_installed,
        "provider": active_provider,
        "indic_conformer": {
            "available": indic_avail,
            "device": indic_caps.get("device", "cpu"),
            "model_id": indic_caps.get("model_id"),
            "supported_languages": SUPPORTED_INDIC_LANGUAGES,
            "decoders": ["rnnt", "ctc"],
            "default_decoder": "rnnt",
        },
        "whisper": {
            "installed": whisper_installed,
            "available_models": AVAILABLE_WHISPER_MODELS,
            "has_api_key": has_api_key,
            "api_key_masked": f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else ("configured" if has_api_key else ""),
        },
        "ffmpeg_installed": ffmpeg_installed,
        "selected_language": selected_language,
        "selected_decoder": selected_decoder,
        "model": selected_model,
        "auto_transcribe": auto_transcribe,
        "notes": notes,
    }


def fetch_single_video_metadata(url: str, timeout: int = 45) -> Optional[dict]:
    """Fetch metadata for a single desired video without downloading media."""
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        "--quiet",
        url
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if res.returncode and ("PEM lib" in res.stderr or "CERTIFICATE_VERIFY_FAILED" in res.stderr):
            retry = cmd[:]
            retry.insert(3, "--compat-options")
            retry.insert(4, "no-certifi")
            res = subprocess.run(retry, capture_output=True, text=True, timeout=timeout, check=False)
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception as exc:
        logger.warning(f"Metadata fetch failed for {url}: {exc}")
    return None


def download_audio_from_url(url: str, timeout: int = 180) -> Optional[str]:
    """Download audio stream from a single video URL using yt-dlp to a temporary file."""
    base_name = f"wt_audio_{uuid.uuid4().hex}"
    out_template = os.path.join(tempfile.gettempdir(), f"{base_name}.%(ext)s")

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-playlist",
        "--force-overwrites",
        "-f", "bestaudio/best",
        "-o", out_template,
        url
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if res.returncode and ("PEM lib" in (res.stderr or "") or "CERTIFICATE_VERIFY_FAILED" in (res.stderr or "")):
            retry = cmd[:]
            retry.insert(3, "--compat-options")
            retry.insert(4, "no-certifi")
            res = subprocess.run(retry, capture_output=True, text=True, timeout=timeout, check=False)

        # Check for any created audio file matching base_name
        tmpdir = tempfile.gettempdir()
        for fname in os.listdir(tmpdir):
            if fname.startswith(base_name):
                fpath = os.path.join(tmpdir, fname)
                if os.path.exists(fpath) and os.path.getsize(fpath) > 1000:
                    return fpath
    except Exception as exc:
        logger.warning(f"Audio download failed for {url}: {exc}")

    return None


def transcribe_audio(
    audio_path_or_url: str,
    provider: Optional[str] = None,
    model: str = "base",
    config: Optional[dict] = None,
    language: Optional[str] = None,
    decoder: Optional[str] = None,
) -> dict:
    """Transcribe audio from a local file path, direct URL, or video URL.

    Returns a dict with 'status', 'text', 'provider', 'language', 'segments', 'decoder', and optional 'error'.
    """
    config = config or {}
    active_provider = provider or config.get("provider")

    if not active_provider:
        avail, detected = is_transcription_available()
        active_provider = detected if avail else "indic_conformer"

    temp_downloaded_file = None
    target_path = audio_path_or_url
    if audio_path_or_url.startswith(("http://", "https://")):
        dl = download_audio_from_url(audio_path_or_url)
        if dl:
            temp_downloaded_file = dl
            target_path = dl
        else:
            return {
                "status": "failed",
                "text": None,
                "provider": active_provider,
                "error": f"Could not extract audio stream from URL: {audio_path_or_url}"
            }

    try:
        # Instantiate through modular factory
        service = get_asr_service(provider=active_provider, config=config)
        lang = language or config.get("language") or "hi"
        dec = decoder or config.get("decoder") or "rnnt"

        result = service.transcribe(
            target_path,
            language=lang,
            decoder=dec,
            model=model or config.get("model", "base")
        )

        output_dict = result.to_dict()
        output_dict["provider"] = result.engine
        return output_dict

    except Exception as exc:
        logger.exception(f"Transcription execution failed: {exc}")
        return {
            "status": "failed",
            "text": None,
            "provider": active_provider,
            "error": str(exc),
        }
    finally:
        if temp_downloaded_file and os.path.exists(temp_downloaded_file):
            try:
                os.unlink(temp_downloaded_file)
            except OSError:
                pass


def attach_transcript_to_record(
    record: dict,
    platform: str,
    auto_transcribe: bool = False,
    config: Optional[dict] = None
) -> dict:
    """Extract or attach transcript metadata to a collected raw record."""
    if record.get("transcript_text"):
        record.setdefault("transcript_status", "collected")
        return record

    subtitles = record.get("subtitles") or record.get("automatic_captions")
    if isinstance(subtitles, dict) and subtitles:
        first_lang = next(iter(subtitles.values()), [])
        if isinstance(first_lang, list) and first_lang:
            text_lines = [entry.get("text", "") for entry in first_lang if isinstance(entry, dict)]
            if any(text_lines):
                record["transcript_text"] = " ".join(text_lines).strip()
                record["transcript_status"] = "subtitles_extracted"
                return record

    if auto_transcribe and record.get("url"):
        res = transcribe_audio(record["url"], config=config)
        if res.get("status") == "collected" and res.get("text"):
            record["transcript_text"] = res["text"]
            record["transcript_language"] = res.get("language")
            record["transcript_engine"] = res.get("engine")
            record["transcript_decoder"] = res.get("decoder")
            record["transcript_segments"] = res.get("segments")
            record["transcript_status"] = "collected"
            return record

    record.setdefault("transcript_status", "not_collected")
    record.setdefault("transcript_text", None)
    return record
