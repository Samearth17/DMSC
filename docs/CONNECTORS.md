# Connector guide

All collection modules implement the `SourceConnector` boundary: availability,
bounded search, raw output, and normalization. Platform-specific implementation
details do not leak into the audit or intelligence layers.

| Platform | Discovery | Time constraint | Current limitations |
|---|---|---|---|
| YouTube | yt-dlp `ytsearch` with metadata hydration | Search date terms, yt-dlp date range, shared exact filter | Internal HTTP counts opaque; transcript/media processing optional and absent |
| News | Google News RSS and saved RSS feeds | Feed query date terms plus shared exact filter | Feed metadata only; aggregator links are not publisher full text |
| Instagram | Saved public profiles, bounded profile discovery, hashtags | Stops on stale newest-first post, then shared exact filter | Valid local session generally required; search is not global caption search |
| X | Thin module bridge | Adapter responsibility plus shared filter when activated | Original scraper not supplied; connector not registered |
| Reddit | Official OAuth draft | API timestamp plus shared filter when activated | Deferred pending permitted credentials/API access |
| Meta | Indexed domain-filtered public links and accessible pages | Shared filter when timestamps exist | Login/access walls are reported; zero indexed links is not proof of no activity |
| Web | Public search RSS and bounded HTTP pages | Shared filter when timestamps exist | No browser rendering; only public robots-permitted pages |

## YouTube metadata

The connector collects video ID, URL, title, description, uploader/channel, channel
ID, publication timestamp or upload date, duration, thumbnails, and view count when
yt-dlp supplies them. Downloads are disabled and unrelated local yt-dlp config is
ignored. On a broken bundled certificate file it retries with the operating-system
trust store; TLS verification remains enabled. A missing JavaScript runtime is
reported as an informational metadata-only limitation, not hidden.

## News and RSS

The Google News collector preserves the original feed response and each item's XML,
publisher, title, summary, aggregator URL, and RSS publication time. Saved feeds use
the generic public HTTP safety boundary. `published_at_source` is `rss_feed`; feed
discovery time is never used as article publication time.

## Instagram access

The dashboard imports a user-selected Instaloader cookie session using a restricted
JSON/pickle reader that rejects executable pickle globals. The copied file is
created with restrictive permissions where the operating system supports them.
API status returns the username and connection state only—never the stored path or
cookies. The worker stops on explicit throttling and never collects private profiles.

Profile discovery returns up to 20 accessible public candidates with username,
display name, biography, profile URL/image, follower/following/post counts, and
verification badge when available. Follower bounds filter this discovered set; they
are not a global Instagram database query. Unavailable counts remain unavailable.

## Error semantics

Connectors emit stable, non-secret codes. Authentication required, authentication
failed, expired session, rate limit, access-control requirement, network failure,
timeout, invalid response, and successful empty results remain distinct. Exceptions,
headers, cookies, passwords, and tokens are not copied into reports.
