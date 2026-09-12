# Preserve the existing X scraper

No original scraper source was available for this build. Integration and live
validation cannot be completed until its files or repository are provided.
Do not rename or rewrite its functions to fit an assumed API.

Create a trusted local Python bridge module, separate from the original files.
Set `WATCHTOWER_X_BRIDGE` to its importable module name (for example,
`local_x_bridge`). This setting is an environment variable, never a remotely
submitted profile field. Importing a bridge executes local Python code.

The bridge contract is:

```python
from app.connectors.base import Batch, ConnectorError
from app.normalization.models import WatchtowerEvent

VERSION = "1"  # Bump when collection or normalization behavior changes.

def search(query, policy) -> Batch:
    # Call the existing scraper using ITS actual API, once inspected.
    # Enforce policy.items_per_query, timeout and request limits.
    # Return original raw objects; do not put geopolitical labels here.
    # requests=None if the existing scraper cannot expose HTTP counts.
    ...

def normalize(raw: dict) -> WatchtowerEvent:
    # Map the original scraper's actual field names to the common schema.
    # platform must be "x"; source_id is a stable account ID when available;
    # item_id is the stable post ID. Preserve the original raw input.
    ...
```

This is a contract illustration, not a ready-to-run bridge. Use
`ConnectorError("stable_code", rate_limited=True, requests=None)` for observed
rate limits. Only mark errors retryable when retries are appropriate. Never
return an empty successful batch to conceal a blocked request or login wall.

The core cannot forcibly time out arbitrary in-process bridge code. If the
original scraper can hang, wrap its invocation in a bounded subprocess while
leaving the original scraper itself untouched.

PowerShell, once the actual bridge is present on Python's module path:

```powershell
$env:WATCHTOWER_X_BRIDGE = "local_x_bridge"
watchtower doctor
watchtower run --platform x
```

Acceptance checks: preserve a hash of original source files, replay representative
raw fixtures, check account/post identifiers and timestamps, test empty success,
partial retrieval, throttling, timeout, and repeated-audit cache behavior. Do not
claim integration complete before these pass against the actual scraper.
