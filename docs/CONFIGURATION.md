# Monitoring configuration

The dashboard is authoritative for ordinary use. `config.example.yaml` is a
placeholder-only developer example; `config.yaml` is ignored by Git.

## Reusable value libraries

The categories are `geography`, `entities`, `keywords`, `hashtags`, and
`incident_types`. Each category has an independent enable switch, searchable saved
values, multi-selection, add, and archive. Adding a value does not automatically
select it. Archiving removes it from future choices but never edits an old audit
snapshot. Values are case-insensitively deduplicated; hashtags additionally ignore
a leading `#` for identity.

At least one enabled value or saved source and at least one platform are required to
run. A disabled category never contributes a query even when it contains selected
values. Categories are independent discovery lanes (OR), not a hidden AND rule.

## Platforms

Each platform is a Boolean selection. The engine never calls a disabled connector.
X and Reddit controls are disabled in 0.3 by agreement. Meta and Web are available
as explicitly limited foundations; the first production milestone remains YouTube,
Instagram, and News.

## Time window

Supported relative values are 1, 6, 12, 24, 48, and 168 hours. A custom window needs
an offset-aware start before the end. Relative windows are resolved once when an
audit begins; exact resolved instants are copied into that immutable audit snapshot.
The timezone is an IANA name such as `UTC` or `Asia/Kolkata` and controls display.

## Policies

Policies are per platform:

| Setting | Meaning | Bounds |
|---|---|---|
| `query_limit` | Maximum generated/saved-source queries | 1–100 |
| `items_per_query` | Maximum accepted results per query | 1–100 |
| `min_interval_seconds` | Central delay before connector calls | 0–300 |
| `timeout_seconds` | Connector time budget | 1–300 |
| `retries` | Transient retries only | 0–3 |
| `backoff_seconds` | Exponential retry base | 0–60 |
| `cache_ttl_seconds` | Query-cache lifetime | 0–86400 |
| `pages_per_query` | Public-Web page budget | 0–10 |

Explicit rate limits stop the remaining queries for that platform. A fixed delay is
not described as protection from platform restrictions.

## Saved sources

News accepts public HTTP(S) RSS feed URLs without embedded credentials. Instagram
accepts public usernames without `@`. Saved sources use the same platform query
budget. A saved RSS feed and a saved Instagram profile can stop processing at the
last previously stored item when the source returns newest-first content.

Use only placeholders in shared files. Enter actual monitoring data locally.
