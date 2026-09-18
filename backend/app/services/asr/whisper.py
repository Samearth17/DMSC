"""OpenAI Whisper and WhisperFlow ASR adapter service."""
import importlib.util
import json
import logging
import os
import shutil
import urllib.request
from typing import Any, Dict, Optional, Tuple

from app.services.asr.base import (
    BaseASRService,
    TranscriptionResult,
    TranscriptionSegment,
)

logger = logging.getLogger("watchtower.asr.whisper")
DEFAULT_API_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"


class WhisperASRService(BaseASRService):
    """Adapter for local openai-whisper and cloud WhisperFlow API."""
    provider_name = "whisper"

    def __init__(
        self,
        model_name: str = "base",
        api_key: Optional[str] = None,
        api_endpoint: Optional[str] = None,
        use_cloud: bool = False
    ):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("WHISPERFLOW_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.api_endpoint = api_endpoint or os.getenv("WHISPERFLOW_API_ENDPOINT") or DEFAULT_API_ENDPOINT
        self.use_cloud = use_cloud or bool(self.api_key and not importlib.util.find_spec("whisper"))

    def is_available(self) -> Tuple[bool, str]:
        if self.use_cloud or self.api_key:
            return True, "ready_cloud_whisperflow_api"
        if importlib.util.find_spec("whisper"):
            if shutil.which("ffmpeg"):
                return True, "ready_local_whisper"
            return False, "missing_ffmpeg_binary"
        return False, "whisper_not_installed"

    def get_capabilities(self) -> Dict[str, Any]:
        avail, reason = self.is_available()
        return {
            "provider": "whisperflow_api" if self.use_cloud else "whisper",
            "model": self.model_name,
            "available": avail,
            "status_reason": reason,
            "has_api_key": bool(self.api_key),
            "cloud_enabled": self.use_cloud,
        }

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        decoder: Optional[str] = None,
        **kwargs
    ) -> TranscriptionResult:
        if self.use_cloud and self.api_key:
            return self._transcribe_cloud(audio_path, language)
        return self._transcribe_local(audio_path, language)

    def _transcribe_local(self, audio_path: str, language: Optional[str]) -> TranscriptionResult:
        if not importlib.util.find_spec("whisper"):
            return TranscriptionResult(
                status="not_configured",
                text="",
                language=language or "en",
                engine="whisper",
                error="openai-whisper package is not installed in the environment."
            )
        if not shutil.which("ffmpeg"):
            return TranscriptionResult(
                status="failed",
                text="",
                language=language or "en",
                engine="whisper",
                error="ffmpeg binary is required for local audio decoding."
            )

        try:
            import whisper  # type: ignore
            model = whisper.load_model(self.model_name)
            opts = {}
            if language:
                opts["language"] = language
            result = model.transcribe(audio_path, **opts)

            text = result.get("text", "").strip() if isinstance(result, dict) else str(result).strip()
            detected_lang = result.get("language") or language or "en"
            raw_segs = result.get("segments", []) if isinstance(result, dict) else []

            segments = [
                TranscriptionSegment(
                    start=float(s.get("start", 0.0)),
                    end=float(s.get("end", 0.0)),
                    text=str(s.get("text", "")).strip(),
                )
                for s in raw_segs
            ]

            return TranscriptionResult(
                status="collected",
                text=text,
                language=detected_lang,
                segments=segments,
                engine=f"whisper ({self.model_name})",
                decoder="greedy",
            )
        except Exception as exc:
            logger.exception(f"Local Whisper transcription failed: {exc}")
            return TranscriptionResult(
                status="failed",
                text="",
                language=language or "en",
                engine="whisper",
                error=str(exc)
            )

    def _transcribe_cloud(self, audio_path: str, language: Optional[str]) -> TranscriptionResult:
        filename = os.path.basename(audio_path)
        content_type = "audio/mpeg" if filename.endswith(".mp3") else "audio/wav" if filename.endswith(".wav") else "application/octet-stream"

        try:
            with open(audio_path, "rb") as f:
                file_bytes = f.read()

            boundary = "----WatchtowerWhisperAdapter7MA4YWxkTrZu0gW"
            body = bytearray()

            body.extend(f"--{boundary}\r\n".encode())
            body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
            body.extend(b"whisper-1\r\n")

            if language:
                body.extend(f"--{boundary}\r\n".encode())
                body.extend(b'Content-Disposition: form-data; name="language"\r\n\r\n')
                body.extend(f"{language}\r\n".encode())

            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode())
            body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
            body.extend(file_bytes)
            body.extend(b"\r\n")
            body.extend(f"--{boundary}--\r\n".encode())

            req = urllib.request.Request(
                self.api_endpoint,
                data=bytes(body),
                headers={
                    "Authorization": f"Bearer {self.api_key.strip()}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                },
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = (data.get("text") or "").strip()
                return TranscriptionResult(
                    status="collected",
                    text=text,
                    language=language or "unknown",
                    segments=[],
                    engine="whisperflow_api",
                    decoder="cloud_api"
                )
        except Exception as exc:
            logger.warning(f"Whisper cloud API request failed: {exc}")
            return TranscriptionResult(
                status="failed",
                text="",
                language=language or "unknown",
                engine="whisperflow_api",
                error=f"Cloud API request failed: {exc}"
            )
