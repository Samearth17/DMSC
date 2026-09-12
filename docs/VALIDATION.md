# Validation — Watchtower 0.3

Validation was performed on 11 September 2026 with placeholder terms only.

## Automated checks

- Python unit/integration suite: configuration, value persistence/archive, bounded
  queries, time validation, stale/unknown/future classification, disabled connector
  isolation, raw/normalized history, incremental saved feeds, YouTube/News/Instagram
  normalization, session redaction, unsafe pickle rejection, follower filtering,
  retries/rate limits, correlation/evidence, reprocessing, API security, exports,
  scheduling, and restart reconciliation.
- JavaScript syntax check and Python bytecode compilation.
- Temporary real HTTP server smoke test: root page, value creation, profile save,
  preview, background run, live status polling, News platform detail, records, event,
  and immutable snapshot.

The current clean suite contains 60 passing tests. The release handoff records the
same final check after packaging.

## Browser interaction check

The dashboard was opened in Chrome and exercised as a user: profile navigation,
value add/select, save, reload persistence, 7-day time selection, no-network query
preview, audit start/live status, platform detail, historical search, and Instagram
not-configured/unavailable messaging. No private monitoring data or session was used.

## Live connectors

- **YouTube:** one bounded `earthquake` metadata result completed; its publication
  timestamp was current in the 7-day window. The installed yt-dlp reported that no
  JavaScript runtime was available; this is retained as a metadata-only note and did
  not prevent required metadata extraction.
- **News:** one bounded Google News RSS result completed and was current in the same
  7-day window.
- The integrated live run completed both platforms with zero connector errors and
  produced two review candidates. This demonstrates the pipeline, not completeness.
- **Instagram:** the installed connector correctly returned not configured. Session
  import/test/search/rate-limit behavior passed isolated fixture tests, but no valid
  user session was available for a live authenticated request.
- X and Reddit were not run. Meta/Web foundations were not re-certified in this
  release and should not be described as production-ready.

## Environment boundaries

Linux execution and Chrome QA were performed. Windows batch files were inspected but
not executed on Windows. External platforms can change behavior, require login, rate
limit, or deny access after release. Every real run must be judged by its own stored
audit rather than this validation note.
