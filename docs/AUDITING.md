# Auditing and evidence semantics

Every execution is an `AuditRun`. It owns one `PlatformAudit` per known platform and
zero or more `SourceAudit` reports for sources actually returned by collection.

## Status

| Status | Meaning |
|---|---|
| `complete` | Every bounded query completed or used a valid cache |
| `partial` | Some planned data, items, or fields could not be retrieved/normalized |
| `failed` | No planned query completed, access was unavailable, or the run was interrupted |
| `disabled` | The user did not select the platform |
| `running` | Work is currently in progress; stale running rows are reconciled to failed at restart |

A complete audit means complete within the stored budget. It never means exhaustive
coverage of a platform, account, channel, or the Web. A successful query with zero
accessible results is different from collection failure.

## Principal counters

| Counter | Exact meaning |
|---|---|
| `queries_generated` | Bounded deduplicated queries in the plan |
| `queries_executed` | Queries with a live connector attempt; retries do not duplicate this count |
| `connector_calls` | Connector invocations including retries |
| `requests` | Instrumented HTTP attempts; `null` means the connector is opaque |
| `cached_queries` | Query batches reused within TTL with no external call |
| `items_discovered` | Raw items accepted from connector batches |
| `items_checked` | Raw item occurrences submitted to normalization |
| `new_items` | New raw payload revisions, not necessarily newly published posts |
| `cached_items` | Previously stored identical raw payloads |
| `items_duplicate` | Previously known platform/item identities |
| `within_time_window` | Publication instant falls inside both exact bounds |
| `items_stale` | Publication instant precedes the start |
| `items_after_window` | Publication instant follows the end |
| `items_unknown_time` | Publication time is absent, invalid, or too imprecise at a boundary |
| `relevant_items` | Distinct current identities matching the objective |
| `errors` | Retrieval warnings, connector errors, and normalization failures |
| `rate_limited_calls` | Observed calls stopped by explicit throttling |

Raw records are stored before normalization. Invalid normalized records retain their
raw payload and stable error code. HTTP totals are never invented. Source-level
request and duration fields remain `null` when a shared query makes attribution
impossible.

## Relevance, events, and evidence

Relevance 0–1 is a transparent weighted coverage of configured category types. It
is not a probability and not verification. Configured and matched entities are
stored separately; model NER is marked unavailable. Original and normalized
hashtags, geography mentions with provenance, incident matches, and optional
processing status are preserved.

Normalized source records are separate from candidate incident events. Correlation
uses exact content or high headline similarity within 24 hours. It stores every
supporting record and source. One source is `Single Source`; repeated or multiple
unassessed reports remain `Unverified`. The application does not automatically
assign partially/strongly corroborated or verified status because it has not assessed
source independence, direct evidence, contradictions, or reliability.

## Historical integrity and reprocessing

Each audit stores the profile plus resolved time window used at execution. Later
profile changes do not mutate it. Reprocessing reads stored normalized versions,
creates a separate analysis revision, and makes zero collection requests. The
original normalized version, analysis, audit report, and raw evidence remain linked.
