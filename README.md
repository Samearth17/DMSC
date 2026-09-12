# Watchtower 0.3 — local public-information monitoring

Watchtower is a local, browser-operated monitoring and audit application. A user
selects saved geography, entities, keywords, hashtags, incident types, platforms,
and a time window. Watchtower generates bounded queries, collects accessible public
records, preserves raw data, normalizes and analyses them, and produces global,
platform, source, and candidate-event reports.

Collection is not verification. A collected claim remains unverified until a human
or a future evidence workflow assesses independent sources and contradictions.

## Quick start on Windows

1. Extract the ZIP to a new folder.
2. Install Python 3.11 or newer and enable the Python launcher.
3. Double-click `install_windows.bat` once.
4. Double-click `start_dashboard.bat` whenever you want to use Watchtower.
5. Configure and run audits at `http://127.0.0.1:8765/` in the browser.

Keep the terminal window open while Watchtower is in use. Stop it with Ctrl+C. A
normal user does not need to edit YAML, use environment variables, or run a backend
command for each audit.

## Linux/macOS setup

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[all]'
.venv/bin/python -m app.cli serve --open
```

Developer-equivalent installed command:

```sh
watchtower --db data/watchtower.sqlite3 serve --open
```

## First audit

1. Open **Monitoring profile**.
2. Add reusable values, select them, and enable their categories.
3. Enable only the required platforms. Start with **News**.
4. Open **Run audit**, select the time window and review collection limits.
5. Select **Preview queries**. Preview makes no network requests.
6. Select **Run audit** and watch the platform progress update automatically.
7. Inspect **Platforms**, **Records & search**, **Events**, and **Audit history**.

Values and selections are stored in SQLite and survive application restarts. A
profile or audit never receives pre-populated operational monitoring data.

## Priority connector status

| Platform | Current capability | Validation in this release |
|---|---|---|
| YouTube | Bounded yt-dlp search, full metadata, channel, publication timestamp, thumbnails, views, duration | Live one-item audit completed with a current record |
| News | Google News RSS plus saved public RSS feeds, publisher and publication timestamp | Live one-item audit completed with a current record |
| Instagram | Local session import/test, public profile discovery, follower-range filtering, saved profiles, hashtag/profile post collection | Session handling and collection outcomes tested with fixtures; no authenticated live account was supplied |
| X | Existing bridge contract retained | Deferred; original scraper files were not supplied |
| Reddit | Draft official-API adapter retained | Deferred pending API permission |
| Meta | Domain-restricted indexed/public-page collection | Foundation only; non-empty Facebook collection not proven |
| Web | Public search plus bounded robots-aware HTML extraction | Foundation only; availability depends on the source |

“Installed” and “accessible” are different. Authentication failure, rate limit,
unavailability, empty accessible results, stale results, and successful results are
reported separately.

## Time-window rules

Every run resolves and stores an exact UTC `start_time` and `end_time`, plus the
chosen display timezone. Connectors add date constraints where supported. The
shared pipeline then validates every normalized `published_at` again:

- `CURRENT`: may enter relevance and candidate-event processing.
- `STALE`: retained and counted, but excluded from current results/events.
- `AFTER_WINDOW`: retained and excluded.
- `UNKNOWN_TIME`: retained for review and excluded from current results/events.

`collected_at` never substitutes for publication time. Day-only YouTube dates that
overlap a partial-day boundary are classified as unknown rather than guessed.

## Instagram setup

Watchtower does not collect passwords or automate login. Create a legitimate local
Instaloader session through Instaloader's normal login/2FA flow, for example:

```sh
instaloader --login your_username
```

Then open **Settings → Instagram access**, enter the username, choose the resulting
local session file, select **Import session**, and then **Test connection**. The
session is copied to a private file under `data/sessions`; cookies are never returned
by the API or included in audit reports. Do not upload or send sessions to anyone.
Private accounts, CAPTCHAs, access barriers, and anti-bot controls are not bypassed.

## Data, search, export, and reprocessing

The default database is `data/watchtower.sqlite3`. It contains immutable audit
snapshots, raw source responses and records, normalized record versions, analysis,
source history, candidate events, alerts, queries, and collection attempts.

The dashboard searches historical records by text, platform, source, monitoring
category, date, time classification, and evidence level. JSON and CSV exports are
available for raw records, normalized records, platform audits, and candidate
events. Reprocessing creates a new analysis revision from stored records and makes
zero collection requests; it does not rewrite the original audit.

Back up the `data` directory if the history matters. SQLite and session files are
local but not an encrypted vault; protect the operating-system account and backups.

## Local security and access limits

The server binds only to loopback, validates Host and Origin, and requires a random
per-process token for API calls. Do not expose this development-stage service to a
LAN or internet proxy. Raw content can contain untrusted text; the UI renders it as
text, not HTML. Formula-like CSV values are neutralized.

The Web collector accepts only public HTTP(S) targets, validates and pins public DNS
addresses, applies byte and redirect limits, and respects robots rules. No connector
bypasses login, CAPTCHA, consent, private-account, or technical access controls.

## Scheduling

Settings supports local interval schedules from 5 minutes to 7 days. The same audit
pipeline is reused. Watchtower and the computer must remain running. Runs never
overlap in one process. If the application stops during a run, the next startup
marks that audit failed and explains that its coverage is incomplete.

## Developer commands

```sh
watchtower doctor
watchtower init
watchtower plan --config config.yaml
watchtower run --config config.yaml
watchtower report
watchtower export --out exports/results.json
python -m unittest discover -s backend/tests -v
node --check backend/app/api/static/app.js
```

YAML remains available for developer automation, but the browser is the primary
control centre. See [configuration](docs/CONFIGURATION.md),
[connectors](docs/CONNECTORS.md), [auditing](docs/AUDITING.md), and
[architecture](docs/ARCHITECTURE.md).

## Explicitly partial or unavailable

Whisper/audio transcription, OCR/vision, model NER, semantic embeddings,
geopolitical inference, source-independence assessment, contradiction analysis,
calibrated confidence, PostgreSQL, durable multi-process workers, email/messaging
alerts, and Playwright rendering are not implemented. Candidate clustering is a
review aid; it never marks an event verified. See [roadmap](docs/ROADMAP.md) and
[validation evidence](docs/VALIDATION.md).
