import importlib
import os
from app.connectors.base import SourceConnector


class XConnector(SourceConnector):
    """Delegate to a trusted local bridge; the legacy scraper stays untouched.

    WATCHTOWER_X_BRIDGE must name an importable module exposing
    search(query, policy) -> Batch and normalize(raw) -> WatchtowerEvent.
    No default or invented legacy API is assumed.
    """
    platform = "x"

    def __init__(self):
        self.bridge = None
        self.reason = "existing_x_scraper_not_connected"
        module = os.environ.get("WATCHTOWER_X_BRIDGE")
        if module:
            try:
                self.bridge = importlib.import_module(module)
                if not callable(getattr(self.bridge, "search", None)) or not callable(getattr(self.bridge, "normalize", None)):
                    raise ValueError()
                self.version = str(getattr(self.bridge, "VERSION", "1"))
            except Exception:
                self.bridge = None
                self.reason = "x_bridge_import_or_contract_error"

    def available(self):
        return self.bridge is not None, "ready" if self.bridge else self.reason

    def search(self, query, policy):
        return self.bridge.search(query, policy)

    def normalize(self, record):
        return self.bridge.normalize(record).validate()
