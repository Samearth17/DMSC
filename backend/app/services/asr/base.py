"""Base abstractions and language definitions for Watchtower ASR services."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The 22 Scheduled Indian Languages supported by AI4Bharat IndicConformer
SUPPORTED_INDIC_LANGUAGES: Dict[str, str] = {
    "as": "Assamese",
    "bn": "Bengali",
    "brx": "Bodo",
    "doi": "Dogri",
    "gu": "Gujarati",
    "hi": "Hindi",
    "kn": "Kannada",
    "kok": "Konkani",
    "ks": "Kashmiri",
    "mai": "Maithili",
    "ml": "Malayalam",
    "mni": "Manipuri",
    "mr": "Marathi",
    "ne": "Nepali",
    "or": "Odia",
    "pa": "Punjabi",
    "sa": "Sanskrit",
    "sat": "Santali",
    "sd": "Sindhi",
    "ta": "Tamil",
    "te": "Telugu",
    "ur": "Urdu",
}

# Common language aliases and full names normalized to 2-letter ISO/Indic codes
LANGUAGE_ALIASES: Dict[str, str] = {
    "assamese": "as",
    "bengali": "bn",
    "bangla": "bn",
    "bodo": "brx",
    "dogri": "doi",
    "gujarati": "gu",
    "gujrati": "gu",
    "hindi": "hi",
    "kannada": "kn",
    "konkani": "kok",
    "kashmiri": "ks",
    "maithili": "mai",
    "malayalam": "ml",
    "manipuri": "mni",
    "marathi": "mr",
    "nepali": "ne",
    "odia": "or",
    "oriya": "or",
    "punjabi": "pa",
    "panjabi": "pa",
    "sanskrit": "sa",
    "santali": "sat",
    "santhali": "sat",
    "sindhi": "sd",
    "tamil": "ta",
    "telugu": "te",
    "urdu": "ur",
    "en": "en",
    "english": "en",
}


def normalize_language_code(code_or_name: Optional[str]) -> Optional[str]:
    """Normalize language code or name to standard 2/3 letter code."""
    if not code_or_name:
        return None
    cleaned = str(code_or_name).strip().lower()
    if cleaned in SUPPORTED_INDIC_LANGUAGES:
        return cleaned
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    # Check if prefix matches
    code_part = cleaned.split("-")[0].split("_")[0]
    if code_part in SUPPORTED_INDIC_LANGUAGES:
        return code_part
    return cleaned


def is_supported_indic_language(code: str) -> bool:
    """Check if language code is one of the 22 scheduled Indian languages."""
    norm = normalize_language_code(code)
    return norm in SUPPORTED_INDIC_LANGUAGES


def validate_indic_language_code(code: Optional[str], default: str = "hi") -> str:
    """Validate language code for IndicConformer.
    
    Raises ValueError if explicitly given an unsupported language code.
    Defaults to 'hi' (Hindi) if None or empty.
    """
    if not code:
        return default
    norm = normalize_language_code(code)
    if norm in SUPPORTED_INDIC_LANGUAGES:
        return norm
    raise ValueError(
        f"Unsupported language code '{code}'. IndicConformer supports 22 scheduled Indian languages: "
        f"{', '.join(sorted(SUPPORTED_INDIC_LANGUAGES.keys()))}"
    )


@dataclass
class TranscriptionSegment:
    """A timestamped segment of recognized speech."""
    start: float
    end: float
    text: str
    confidence: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text.strip(),
            "confidence": self.confidence,
        }


@dataclass
class TranscriptionResult:
    """Unified transcription output container."""
    status: str  # 'collected', 'failed', 'not_configured'
    text: str
    language: str
    segments: List[TranscriptionSegment] = field(default_factory=list)
    engine: str = "indic_conformer"
    decoder: str = "rnnt"
    device: str = "cpu"
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "text": self.text,
            "language": self.language,
            "segments": [s.to_dict() for s in self.segments],
            "engine": self.engine,
            "decoder": self.decoder,
            "device": self.device,
            "duration_seconds": round(self.duration_seconds, 2) if self.duration_seconds is not None else None,
            "error": self.error,
        }


class BaseASRService(ABC):
    """Abstract base class for all ASR transcription engines in Watchtower."""
    provider_name: str = "base"

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: Optional[str] = None,
        decoder: Optional[str] = None,
        **kwargs
    ) -> TranscriptionResult:
        """Transcribe audio file preserving verbatim native script.
        
        Args:
            audio_path: Local path to audio file.
            language: Language code (e.g. 'hi', 'te', 'ta', 'mr', etc.).
            decoder: Decoding algorithm ('rnnt' or 'ctc' for IndicConformer).
        """
        pass

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Check if backend dependencies, binaries, and models are available."""
        pass

    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Return engine metadata, supported languages, decoders, and device info."""
        pass
