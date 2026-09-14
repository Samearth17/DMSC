"""Video and audio transcription integration (WhisperFlow / Whisper).

Extracts spoken audio text from YouTube and Instagram video media to enable
transcript-based relevance evaluation and evidence provenance.
"""
import importlib.util
import logging
import os
from typing import Optional

logger = logging.getLogger("watchtower.transcription")


def is_transcription_available() -> tuple[bool, str]:
    """Check if WhisperFlow or Whisper transcription backends are installed."""
    if importlib.util.find_spec("whisperflow"):
        return True, "whisperflow"
    if importlib.util.find_spec("whisper"):
        return True, "whisper"
    return False, "transcription_backend_not_installed"


def transcribe_audio(audio_path_or_url: str, provider: Optional[str] = None) -> dict:
    """Transcribe audio from a local file path or stream URL.

    Returns a dict with 'status', 'text', and 'provider'.
    """
    available, detected = is_transcription_available()
    active_provider = provider or detected

    if not available:
        return {
            "status": "not_configured",
            "text": None,
            "provider": active_provider,
            "error": "WhisperFlow or Whisper package is not installed"
        }

    try:
        if active_provider == "whisperflow":
            import whisperflow  # type: ignore
            # Invoke WhisperFlow pipeline if available
            pipeline = getattr(whisperflow, "Pipeline", None) or getattr(whisperflow, "load_model", None)
            if callable(pipeline):
                model = pipeline("base")
                result = model.transcribe(audio_path_or_url)
                text = result.get("text", "") if isinstance(result, dict) else str(result)
                return {"status": "collected", "text": text.strip(), "provider": "whisperflow"}
        elif active_provider == "whisper":
            import whisper  # type: ignore
            model = whisper.load_model("base")
            result = model.transcribe(audio_path_or_url)
            text = result.get("text", "") if isinstance(result, dict) else str(result)
            return {"status": "collected", "text": text.strip(), "provider": "whisper"}
    except Exception as exc:
        logger.warning(f"Transcription failed: {exc}")
        return {
            "status": "failed",
            "text": None,
            "provider": active_provider,
            "error": str(exc)
        }

    return {"status": "not_configured", "text": None, "provider": active_provider}


def attach_transcript_to_record(record: dict, platform: str) -> dict:
    """Extract or attach transcript metadata to a collected raw record."""
    # If transcript already supplied in record (e.g. from subtitles, fixture, or cache)
    if record.get("transcript_text"):
        record.setdefault("transcript_status", "collected")
        return record

    # Check if record has subtitles from yt-dlp
    subtitles = record.get("subtitles") or record.get("automatic_captions")
    if isinstance(subtitles, dict) and subtitles:
        # If subtitles exist in any language
        first_lang = next(iter(subtitles.values()), [])
        if isinstance(first_lang, list) and first_lang:
            text_lines = [entry.get("text", "") for entry in first_lang if isinstance(entry, dict)]
            if any(text_lines):
                record["transcript_text"] = " ".join(text_lines).strip()
                record["transcript_status"] = "subtitles_extracted"
                return record

    record.setdefault("transcript_status", "not_collected")
    record.setdefault("transcript_text", None)
    return record
