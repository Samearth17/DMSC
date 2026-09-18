"""ASR Service Factory and provider resolution."""
import os
from typing import Any, Dict, Optional

from app.services.asr.base import BaseASRService
from app.services.asr.indic_conformer import IndicConformerASRService
from app.services.asr.whisper import WhisperASRService


def get_asr_service(
    provider: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None
) -> BaseASRService:
    """Resolve and return appropriate ASR service instance based on configuration."""
    config = config or {}

    # Resolution priority: parameter -> config -> environment variable -> default
    resolved_provider = (
        provider or
        config.get("provider") or
        os.getenv("ASR_PROVIDER") or
        ""
    ).strip().lower()

    if not resolved_provider:
        # Check if IndicConformer dependencies are ready
        indic_service = IndicConformerASRService()
        if indic_service.is_available()[0]:
            return indic_service
        # Fallback to Whisper
        whisper_service = WhisperASRService()
        if whisper_service.is_available()[0]:
            return whisper_service
        return indic_service

    if resolved_provider in ("indic_conformer", "indicconformer", "ai4bharat", "indic"):
        return IndicConformerASRService(
            model_id=config.get("model_id", "ai4bharat/indic-conformer-600m-multilingual"),
            preferred_device=config.get("device")
        )

    if resolved_provider in ("whisper", "local_whisper"):
        return WhisperASRService(
            model_name=config.get("model", "base"),
            use_cloud=False
        )

    if resolved_provider in ("whisperflow_api", "openai", "cloud"):
        return WhisperASRService(
            model_name=config.get("model", "whisper-1"),
            api_key=config.get("api_key"),
            api_endpoint=config.get("api_endpoint"),
            use_cloud=True
        )

    # Default fallback
    return IndicConformerASRService()
