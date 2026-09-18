"""AI4Bharat IndicConformer 600M Multilingual ASR Service.

Provides on-device speech-to-text recognition across all 22 scheduled Indian languages
using the official ai4bharat/indic-conformer-600m-multilingual hybrid CTC + RNNT model.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Tuple

from app.services.asr.base import (
    BaseASRService,
    SUPPORTED_INDIC_LANGUAGES,
    TranscriptionResult,
    TranscriptionSegment,
    normalize_language_code,
    validate_indic_language_code,
)

logger = logging.getLogger("watchtower.asr.indic_conformer")

MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"
SAMPLE_RATE = 16000
CHUNK_DURATION_SEC = 30.0
OVERLAP_DURATION_SEC = 1.0


class IndicConformerASRService(BaseASRService):
    """Local ASR engine for 22 Indian languages powered by AI4Bharat IndicConformer 600M."""
    provider_name = "indic_conformer"

    _cached_model = None
    _cached_device = None

    def __init__(self, model_id: str = MODEL_ID, preferred_device: Optional[str] = None):
        self.model_id = model_id
        self.preferred_device = preferred_device

    @classmethod
    def clear_cache(cls):
        """Release cached model weights from memory."""
        cls._cached_model = None
        cls._cached_device = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            elif hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
        except Exception:
            pass

    def _select_device(self):
        """Select best available acceleration device: CUDA -> MPS -> CPU."""
        if self.preferred_device:
            return self.preferred_device
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    def _load_model(self):
        """Load model weights as singleton with automatic remote code trust."""
        if IndicConformerASRService._cached_model is not None:
            return IndicConformerASRService._cached_model, IndicConformerASRService._cached_device

        device_str = self._select_device()
        logger.info(f"Loading IndicConformer 600M model '{self.model_id}' on device '{device_str}'...")

        try:
            from transformers import AutoModel
            import torch

            model = AutoModel.from_pretrained(
                self.model_id,
                trust_remote_code=True
            )
            try:
                model = model.to(device_str)
            except Exception as exc:
                if device_str == "mps":
                    logger.warning(f"MPS placement failed ({exc}). Falling back to CPU for IndicConformer.")
                    device_str = "cpu"
                    model = model.to("cpu")
                else:
                    raise

            model.eval()
            IndicConformerASRService._cached_model = model
            IndicConformerASRService._cached_device = device_str
            return model, device_str
        except Exception as exc:
            logger.error(f"Failed to load IndicConformer model: {exc}")
            raise

    def is_available(self) -> Tuple[bool, str]:
        """Check if torch, torchaudio, and transformers are ready."""
        try:
            import torch
            import torchaudio
            import transformers
            return True, "ready_local_indic_conformer"
        except ImportError as exc:
            return False, f"missing_dependency_{exc.name}"

    def get_capabilities(self) -> Dict[str, Any]:
        available, reason = self.is_available()
        return {
            "provider": self.provider_name,
            "model_id": self.model_id,
            "available": available,
            "status_reason": reason,
            "device": self._select_device(),
            "decoders": ["rnnt", "ctc"],
            "default_decoder": "rnnt",
            "supported_languages": SUPPORTED_INDIC_LANGUAGES,
            "sample_rate": SAMPLE_RATE,
            "chunk_duration_seconds": CHUNK_DURATION_SEC,
            "overlap_seconds": OVERLAP_DURATION_SEC,
            "license": "MIT",
        }

    def _load_and_normalize_audio(self, audio_path: str):
        """Load audio file and normalize to 16kHz mono float32 tensor."""
        import torch
        import torchaudio

        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        # Try native torchaudio load
        try:
            waveform, sr = torchaudio.load(audio_path)
        except Exception:
            # Fallback to ffmpeg conversion if audio format isn't directly supported by backend
            waveform, sr = self._convert_via_ffmpeg(audio_path)

        if waveform.numel() == 0:
            raise ValueError(f"Audio file contains no samples: {audio_path}")

        # Convert to mono if multi-channel
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)

        # Resample to 16kHz if needed
        if sr != SAMPLE_RATE:
            resampler = torchaudio.transforms.Resample(orig_freq=sr, new_freq=SAMPLE_RATE)
            waveform = resampler(waveform)

        return waveform, SAMPLE_RATE

    def _convert_via_ffmpeg(self, audio_path: str):
        """Use FFmpeg to convert arbitrary audio/video to 16kHz mono WAV."""
        import torch
        import torchaudio

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is required to decode this audio stream")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_wav = tmp.name

        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-f", "wav", tmp_wav
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                raise RuntimeError(f"FFmpeg audio conversion failed: {res.stderr}")
            waveform, sr = torchaudio.load(tmp_wav)
            return waveform, sr
        finally:
            if os.path.exists(tmp_wav):
                try:
                    os.unlink(tmp_wav)
                except OSError:
                    pass

    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        decoder: Optional[str] = "rnnt",
        **kwargs
    ) -> TranscriptionResult:
        """Transcribe audio into native Indian script verbatim."""
        start_time = time.monotonic()
        lang_code = validate_indic_language_code(language, default="hi")
        active_decoder = (decoder or "rnnt").lower()
        if active_decoder not in ("rnnt", "ctc"):
            active_decoder = "rnnt"

        try:
            model, device_str = self._load_model()
            waveform, sr = self._load_and_normalize_audio(audio_path)
            total_samples = waveform.shape[1]
            total_duration = total_samples / sr

            chunk_samples = int(CHUNK_DURATION_SEC * sr)
            overlap_samples = int(OVERLAP_DURATION_SEC * sr)
            step_samples = chunk_samples - overlap_samples

            segments: List[TranscriptionSegment] = []
            full_texts: List[str] = []

            # Process in overlapping windows for long broadcast media
            for start_idx in range(0, total_samples, step_samples):
                end_idx = min(start_idx + chunk_samples, total_samples)
                chunk_waveform = waveform[:, start_idx:end_idx]

                chunk_start_sec = start_idx / sr
                chunk_end_sec = end_idx / sr

                # Inference on chunk
                chunk_text = self._infer_chunk(model, chunk_waveform, lang_code, active_decoder, device_str)
                if chunk_text:
                    full_texts.append(chunk_text)
                    segments.append(TranscriptionSegment(
                        start=chunk_start_sec,
                        end=chunk_end_sec,
                        text=chunk_text,
                    ))

                if end_idx >= total_samples:
                    break

            assembled_text = " ".join(full_texts).strip()

            return TranscriptionResult(
                status="collected",
                text=assembled_text,
                language=lang_code,
                segments=segments,
                engine=self.provider_name,
                decoder=active_decoder,
                device=device_str,
                duration_seconds=total_duration,
            )

        except Exception as exc:
            logger.exception(f"IndicConformer transcription failed on '{audio_path}': {exc}")
            return TranscriptionResult(
                status="failed",
                text="",
                language=lang_code,
                segments=[],
                engine=self.provider_name,
                decoder=active_decoder,
                device=self._cached_device or "cpu",
                error=str(exc),
            )

    def _infer_chunk(self, model, chunk_waveform, language: str, decoder: str, device: str) -> str:
        """Run forward inference on a single audio chunk with MPS fallback."""
        import torch

        try:
            chunk_input = chunk_waveform.to(device)
            with torch.inference_mode():
                # Model supports forward with language and decoder args
                if hasattr(model, "transcribe"):
                    res = model.transcribe(chunk_input, language=language, decoder=decoder)
                else:
                    # Direct callable AutoModel interface
                    res = model(chunk_input, language=language, decoder=decoder)

            if isinstance(res, str):
                return res.strip()
            if isinstance(res, (list, tuple)) and len(res) > 0:
                return str(res[0]).strip()
            if isinstance(res, dict):
                return str(res.get("text") or res.get("transcript") or "").strip()
            return str(res).strip()

        except Exception as exc:
            if device == "mps":
                logger.warning(f"MPS kernel error during inference ({exc}). Falling back to CPU for chunk.")
                chunk_cpu = chunk_waveform.to("cpu")
                model_cpu = model.to("cpu")
                IndicConformerASRService._cached_device = "cpu"
                with torch.inference_mode():
                    if hasattr(model_cpu, "transcribe"):
                        res = model_cpu.transcribe(chunk_cpu, language=language, decoder=decoder)
                    else:
                        res = model_cpu(chunk_cpu, language=language, decoder=decoder)
                if isinstance(res, str):
                    return res.strip()
                if isinstance(res, (list, tuple)) and len(res) > 0:
                    return str(res[0]).strip()
                return str(res).strip()
            raise
