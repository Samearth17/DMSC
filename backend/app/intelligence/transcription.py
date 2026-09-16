"""Video and audio transcription integration (WhisperFlow / Whisper).

Extracts spoken audio text from YouTube and Instagram video media to enable
transcript-based relevance evaluation and evidence provenance.
Supports both:
1. Local Whisper model (via installed openai-whisper package)
2. Cloud WhisperFlow / OpenAI Whisper API (via API key & HTTP endpoints)
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
from typing import Optional

# Ensure standard Mac Homebrew / Unix binary paths are available for ffmpeg and yt-dlp
for _bin_path in ("/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/bin", "/bin"):
    if _bin_path not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = _bin_path + os.pathsep + os.environ.get("PATH", "")

logger = logging.getLogger("watchtower.transcription")

AVAILABLE_MODELS = ["tiny", "base", "small", "medium"]
DEFAULT_API_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


def is_transcription_available() -> tuple[bool, str]:
    """Check if WhisperFlow or Whisper transcription backends are installed or configured."""
    if os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY"):
        return True, "whisperflow_api"
    if importlib.util.find_spec("whisper"):
        return True, "whisper"
    if importlib.util.find_spec("whisperflow"):
        return True, "whisperflow"
    return False, "transcription_backend_not_installed"


def get_transcription_status(config: Optional[dict] = None) -> dict:
    """Return comprehensive status of local whisper and cloud WhisperFlow API integration."""
    config = config or {}
    local_installed = importlib.util.find_spec("whisper") is not None
    ffmpeg_installed = shutil.which("ffmpeg") is not None
    api_key = config.get("api_key") or os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    has_api_key = bool(api_key.strip())

    active_provider = config.get("provider")
    if not active_provider:
        if has_api_key:
            active_provider = "whisperflow_api"
        elif local_installed:
            active_provider = "whisper"
        else:
            active_provider = "not_configured"

    selected_model = config.get("model", "base")
    api_endpoint = config.get("api_endpoint") or DEFAULT_API_ENDPOINT
    auto_transcribe = bool(config.get("auto_transcribe", False))

    notes = []
    if local_installed and not ffmpeg_installed:
        notes.append("Local whisper is installed. To decode local audio files on Mac, install ffmpeg: run 'brew install ffmpeg' in terminal, or configure an API Key for cloud transcription.")
    elif local_installed and ffmpeg_installed:
        notes.append("Local Whisper engine and ffmpeg are ready for on-device transcription.")
    if has_api_key:
        notes.append("Cloud WhisperFlow API is configured and ready for cloud-based transcription.")

    return {
        "available": local_installed or has_api_key,
        "local_installed": local_installed,
        "ffmpeg_installed": ffmpeg_installed,
        "has_api_key": has_api_key,
        "api_key_masked": f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else ("configured" if has_api_key else ""),
        "provider": active_provider,
        "model": selected_model,
        "available_models": AVAILABLE_MODELS,
        "api_endpoint": api_endpoint,
        "auto_transcribe": auto_transcribe,
        "notes": notes
    }


def _transcribe_via_api(audio_path: str, api_key: str, endpoint: Optional[str] = None, model: str = "whisper-1") -> dict:
    """Send audio file to WhisperFlow / OpenAI Whisper transcription API."""
    url = endpoint or DEFAULT_API_ENDPOINT
    filename = os.path.basename(audio_path)
    content_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/m4a" if filename.endswith(".m4a") else "application/octet-stream"

    with open(audio_path, "rb") as f:
        file_bytes = f.read()

    boundary = "----WebKitFormBoundaryWatchtowerWhisperFlow7MA4YWxkTrZu0gW"
    body = bytearray()

    # Part: model
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
    body.extend(f"{model or 'whisper-1'}\r\n".encode())

    # Part: file
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
    body.extend(file_bytes)
    body.extend(b"\r\n")

    # Final boundary
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data.get("text", "")
            return {
                "status": "collected",
                "text": text.strip(),
                "provider": "whisperflow_api"
            }
    except Exception as exc:
        logger.warning(f"WhisperFlow API request failed: {exc}")
        return {
            "status": "failed",
            "text": None,
            "provider": "whisperflow_api",
            "error": f"API request failed: {exc}"
        }


def fetch_single_video_metadata(url: str, timeout: int = 45) -> Optional[dict]:
    """Fetch metadata for a single desired video without downloading the media."""
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
    """Download audio stream from a single desired video URL using yt-dlp to a temporary file."""
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


def transcribe_audio(audio_path_or_url: str, provider: Optional[str] = None, model: str = "base", config: Optional[dict] = None) -> dict:
    """Transcribe audio from a local file path, direct URL, or video URL.

    Returns a dict with 'status', 'text', 'provider', and optional 'error'.
    """
    config = config or {}
    api_key = config.get("api_key") or os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY")
    api_endpoint = config.get("api_endpoint") or os.getenv("WHISPERFLOW_API_ENDPOINT")
    active_provider = provider or config.get("provider")

    if not active_provider:
        if api_key:
            active_provider = "whisperflow_api"
        else:
            available, detected = is_transcription_available()
            active_provider = detected if available else "whisper"

    # If an audio or video URL is provided, download it locally first
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
        # Route 1: WhisperFlow / Cloud API
        if active_provider in ("whisperflow_api", "openai") or (api_key and active_provider != "whisper"):
            if not api_key:
                return {
                    "status": "not_configured",
                    "text": None,
                    "provider": "whisperflow_api",
                    "error": "WhisperFlow API key not configured. Enter your API key in Settings."
                }
            return _transcribe_via_api(target_path, api_key, endpoint=api_endpoint, model="whisper-1")

        # Route 2: Local Whisper Model
        if active_provider in ("whisper", "local"):
            if importlib.util.find_spec("whisper") is None:
                return {
                    "status": "not_configured",
                    "text": None,
                    "provider": "whisper",
                    "error": "openai-whisper package is not installed in .venv"
                }

            if not shutil.which("ffmpeg"):
                return {
                    "status": "failed",
                    "text": None,
                    "provider": "whisper",
                    "error": "ffmpeg is not found on your system. To transcribe audio locally on Mac, install ffmpeg: run 'brew install ffmpeg' in terminal, or use Cloud Whisper API."
                }

            import whisper  # type: ignore
            model_name = model or config.get("model", "base")
            loaded_model = whisper.load_model(model_name)
            result = loaded_model.transcribe(target_path)
            text = result.get("text", "") if isinstance(result, dict) else str(result)
            return {
                "status": "collected",
                "text": text.strip(),
                "provider": f"whisper ({model_name})"
            }

        # Route 3: Legacy WhisperFlow local library
        if active_provider == "whisperflow":
            import whisperflow  # type: ignore
            pipeline = getattr(whisperflow, "Pipeline", None) or getattr(whisperflow, "load_model", None)
            if callable(pipeline):
                m = pipeline(model or "base")
                result = m.transcribe(target_path)
                text = result.get("text", "") if isinstance(result, dict) else str(result)
                return {"status": "collected", "text": text.strip(), "provider": "whisperflow"}

    except Exception as exc:
        logger.warning(f"Transcription failed: {exc}")
        return {
            "status": "failed",
            "text": None,
            "provider": active_provider,
            "error": str(exc)
        }
    finally:
        if temp_downloaded_file and os.path.exists(temp_downloaded_file):
            try:
                os.unlink(temp_downloaded_file)
            except OSError:
                pass

    return {"status": "not_configured", "text": None, "provider": active_provider}


def attach_transcript_to_record(record: dict, platform: str, auto_transcribe: bool = False, config: Optional[dict] = None) -> dict:
    """Extract or attach transcript metadata to a collected raw record."""
    # 1. If transcript already supplied in record (e.g. from subtitles, fixture, or cache)
    if record.get("transcript_text"):
        record.setdefault("transcript_status", "collected")
        return record

    # 2. Check if record has subtitles from yt-dlp (fastest, zero CPU)
    subtitles = record.get("subtitles") or record.get("automatic_captions")
    if isinstance(subtitles, dict) and subtitles:
        first_lang = next(iter(subtitles.values()), [])
        if isinstance(first_lang, list) and first_lang:
            text_lines = [entry.get("text", "") for entry in first_lang if isinstance(entry, dict)]
            if any(text_lines):
                record["transcript_text"] = " ".join(text_lines).strip()
                record["transcript_status"] = "subtitles_extracted"
                return record

    # 3. If auto_transcribe is enabled and video URL is present, transcribe via Whisper
    if auto_transcribe and record.get("url"):
        res = transcribe_audio(record["url"], config=config)
        if res.get("status") == "collected" and res.get("text"):
            record["transcript_text"] = res["text"]
            record["transcript_status"] = "collected"
            return record

    record.setdefault("transcript_status", "not_collected")
    record.setdefault("transcript_text", None)
    return record
