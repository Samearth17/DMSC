# Roadmap and acceptance status

| Stage | Status in 0.3 | Remaining work |
|---|---|---|
| Foundation and common models | Working | Ordered external migration tooling |
| Persistent monitoring controls | Working | Named multi-profile management |
| Exact time filtering | Working | More connector-native precision |
| YouTube metadata | Working and live-tested | Transcripts/audio as optional workers |
| News/RSS | Working and live-tested | Conditional HTTP/ETag and more providers |
| Instagram access/search | Implemented and fixture-tested | Live validation with a user-owned session |
| Platform/source reports | Working | More source-attributed HTTP telemetry |
| Source history/incremental use | Working for query cache and saved-source boundaries | Platform-native cursors where available |
| Relevance/provenance | Working lexical baseline | Language models, NER, semantic relevance |
| Candidate events/evidence | Working conservative baseline | Independence, contradiction, reliability assessment |
| X | Deferred | Original scraper files and adapter fixtures |
| Reddit | Deferred | Approved official API credentials and quota tests |
| Meta/Web | Limited foundations | Reliable non-empty validation; optional permitted rendering |
| Search/export/reprocessing/alerts | Working local baseline | External delivery adapters |
| Scheduling | Working while application runs | Durable worker leases/service mode |
| PostgreSQL/media intelligence | Not implemented | Later milestones |

“Working” means tests pass at the documented scope. It does not mean exhaustive
platform coverage. The next production stage should validate authenticated Instagram
on the user's own machine, then harden source-independent evidence assessment before
introducing model-driven geopolitical analysis.
