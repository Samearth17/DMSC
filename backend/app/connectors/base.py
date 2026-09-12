from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from app.config.profile import Policy
from app.discovery.queries import Query
from app.normalization.models import WatchtowerEvent


class ConnectorError(Exception):
    def __init__(self, code, *, retryable=False, rate_limited=False, requests=None):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.rate_limited = rate_limited
        self.requests = requests


@dataclass
class Batch:
    records: list[dict]
    requests: int | None = None  # None means uninstrumented, never fabricated zero.
    warnings: list[str] = field(default_factory=list)
    raw_response: str | None = None
    rate_limited: bool = False
    notes: list[str] = field(default_factory=list)


class SourceConnector(ABC):
    platform: str
    version = "1"
    def available(self) -> tuple[bool, str]:
        return True, "ready"

    @abstractmethod
    def search(self, query: Query, policy: Policy) -> Batch: ...

    @abstractmethod
    def normalize(self, record: dict) -> WatchtowerEvent: ...
