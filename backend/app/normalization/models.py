from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WatchtowerEvent:
    platform: str
    source_type: str
    source_id: str
    item_id: str
    url: str
    content: str
    account: str | None = None
    engagement: dict = field(default_factory=dict)
    media: list = field(default_factory=list)
    location: list = field(default_factory=list)
    published_at: str | None = None
    collected_at: str = field(default_factory=now)
    metadata: dict = field(default_factory=dict)
    title: str | None = None
    author: str | None = None
    hashtags: list = field(default_factory=list)
    entities: list = field(default_factory=list)
    published_at_source: str | None = None
    time_confidence: float | None = None

    def validate(self):
        if not self.item_id or not self.source_id:
            raise ValueError("Missing source/item identity")
        if urlsplit(self.url).scheme not in {"http", "https"}:
            raise ValueError("Record URL must be HTTP(S)")
        for loc in self.location:
            if loc.get("provenance") not in {"platform-provided", "text-mentioned", "transcript-derived",
                                              "image/video-derived", "model-inferred"}:
                raise ValueError("Location requires provenance")
            if not 0 <= loc.get("confidence", -1) <= 1:
                raise ValueError("Location confidence must be in [0,1]")
        return self

    def to_dict(self):
        return asdict(self)


# Compatibility name for adapters built against v0.2. Correlated events are separate.
WatchtowerRecord = WatchtowerEvent
