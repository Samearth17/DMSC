"""Modular Automatic Speech Recognition (ASR) service package.

Supports AI4Bharat IndicConformer 600M Multilingual (22 Indian languages)
and OpenAI Whisper / WhisperFlow backends with unified interfaces.
"""
from app.services.asr.base import (
    BaseASRService,
    TranscriptionResult,
    TranscriptionSegment,
    SUPPORTED_INDIC_LANGUAGES,
    is_supported_indic_language,
    normalize_language_code,
)
from app.services.asr.factory import get_asr_service

__all__ = [
    "BaseASRService",
    "TranscriptionResult",
    "TranscriptionSegment",
    "SUPPORTED_INDIC_LANGUAGES",
    "is_supported_indic_language",
    "normalize_language_code",
    "get_asr_service",
]
