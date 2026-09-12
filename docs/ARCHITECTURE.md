# Architecture

Watchtower 0.3 preserves the existing connector/audit foundation and adds the
application workflows required by the first milestone. The browser and CLI call the
same domain pipeline; no platform connector decides geopolitical meaning.

```text
Profile + exact time window
  -> bounded query generator
  -> enabled SourceConnector instances only
  -> raw discovery response + raw source record
  -> WatchtowerRecord normalization
  -> exact time classification
  -> modular relevance/provenance analysis
  -> candidate event correlation
  -> SQLite audit/evidence history
  -> local API and dashboard
```

## Modules

- `config`: strict profiles, policies, saved sources, and timezone-aware windows.
- `discovery`: priority round-robin queries without Cartesian expansion.
- `connectors`: common boundary plus isolated platform implementations.
- `auditing`: pacing, retry/backoff, caching, telemetry, and status orchestration.
- `normalization`: source-agnostic records with time/location provenance.
- `intelligence`: transparent lexical analysis; optional model processing is absent.
- `correlation`: conservative review candidates, not automatic verification.
- `storage`: additive SQLite schema and repository boundary.
- `api`: loopback HTTP transport, controller, background runs, and static dashboard.

## SQLite schema version 2

| Table | Purpose |
|---|---|
| `monitoring_profiles` | Content-addressed immutable profile versions |
| `monitoring_values` | Persistent reusable category libraries and archives |
| `audit_runs` | Global lifecycle and exact snapshot |
| `platform_audits` | Platform metrics, queries, status, notes, and errors |
| `sources`, `source_audits` | Source identity and audit history |
| `source_state` | Last item, collection/success time, failures, and rate limits |
| `queries`, `collection_attempts` | Durable plan and connector attempt telemetry |
| `discovery_responses` | Original successful connector response text |
| `source_records` | Every raw occurrence, fingerprint, and error |
| `events` | Legacy-compatible normalized source-record identity |
| `event_sources` | Immutable normalized versions linked to raw records |
| `analysis_results` | Original per-run analysis |
| `incident_events`, `incident_sources` | Separate candidate incidents and evidence |
| `analysis_revisions` | Reprocessing results without recollection |
| `query_cache` | Connector/time/source-state-specific batches |
| `alerts` | Local review-queue alerts |
| `app_settings` | Active profile, schedule, and redacted access references |

The historical `events` table name is retained for migration compatibility but
contains normalized records. Public `/api/events` returns `incident_events`; public
`/api/records` returns normalized source records. A PostgreSQL adapter will require
ordered migrations and integration tests; changing a connection string is not
currently sufficient.

## Runtime boundaries

One process should own a database. WAL and transactions protect concurrent dashboard
reads, while controller locking prevents overlapping audits or access reconfiguration.
The next startup reconciles abandoned running rows to failed. Scheduling is local and
in-process. Retention is not automatic because raw evidence must remain auditable.

X remains a thin bridge boundary; its original source was not supplied. Reddit is
kept out of the active registry pending permitted API access. These limits are visible
in capabilities and cannot silently become empty successful results.
