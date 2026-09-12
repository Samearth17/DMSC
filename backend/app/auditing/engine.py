from dataclasses import asdict
import random
import time
import sys
import uuid
from app.config.profile import PLATFORMS
from app.connectors.base import Batch, ConnectorError
from app.discovery.queries import generate
from app.intelligence.rules import analyze
from app.normalization.models import now
from app.storage.repository import digest

COUNTERS = ("queries_generated", "queries_executed", "cached_queries", "connector_calls", "failed_calls",
            "rate_limited_calls", "sources_discovered", "items_checked", "cached_items", "new_items",
            "relevant_items", "errors", "items_discovered", "within_time_window", "items_stale",
            "items_unknown_time", "items_after_window", "items_duplicate", "retry_count")
HTTP = ("requests", "successful_requests", "failed_requests", "rate_limited_requests")


def counters():
    return {k: 0 for k in (*COUNTERS, *HTTP)}


def aggregate_status(statuses):
    active = [s for s in statuses if s != "disabled"]
    if not active:
        return "disabled"
    if all(s == "complete" for s in active):
        return "complete"
    if all(s == "failed" for s in active):
        return "failed"
    return "partial"


class AuditEngine:
    def __init__(self, repository, connectors, *, sleep=time.sleep, clock=time.time):
        self.repo, self.connectors, self.sleep, self.clock = repository, connectors, sleep, clock
        self.last_call = {}

    def request(self, connector, query, policy, metrics):
        for attempt in range(policy.retries+1):
            metrics['retry_count'] += int(attempt > 0)
            remaining = self.last_call.get(connector.platform, 0) + policy.min_interval_seconds - self.clock()
            if remaining > 0:
                self.sleep(remaining)
            self.last_call[connector.platform] = self.clock()
            metrics["connector_calls"] += 1
            try:
                batch = connector.search(query, policy)
                if not isinstance(batch, Batch) or not isinstance(batch.records, list):
                    raise ConnectorError("connector_contract_error")
                self.http(metrics, batch.requests, False, False)
                return batch
            except ConnectorError as exc:
                metrics["failed_calls"] += 1
                metrics["rate_limited_calls"] += int(exc.rate_limited)
                self.http(metrics, exc.requests, True, exc.rate_limited)
                # Stop on explicit platform throttling; never loop through it.
                if exc.rate_limited or not exc.retryable or attempt == policy.retries:
                    raise
                self.sleep(min(60, policy.backoff_seconds * 2**attempt + random.uniform(0, .2)))
            except Exception:
                metrics["failed_calls"] += 1
                self.http(metrics, None, True, False)
                raise ConnectorError("connector_unexpected_error") from None

    @staticmethod
    def http(metrics, count, failed, limited):
        if count is None:
            for key in HTTP:
                metrics[key] = None
        elif metrics["requests"] is not None:
            metrics["requests"] += count
            metrics["failed_requests" if failed else "successful_requests"] += count
            metrics["rate_limited_requests"] += count if limited else 0

    def run(self, profile, run_id=None):
        started = self.clock()
        window = profile.time_window.resolve()
        report = {"id": run_id or self.repo.begin(profile), "status": "running", "started_at": now(),
                  "snapshot": profile.snapshot(), "platforms": {}, "metrics": counters(),
                  "time_window": window.snapshot(),
                  "scope": "bounded query results; not a full account or web inventory"}
        report['snapshot']['resolved_time_window'] = window.snapshot()
        with self.repo.db:
            from app.storage.repository import encode
            self.repo.db.execute('UPDATE audit_runs SET snapshot=? WHERE id=?', (encode(report['snapshot']),report['id']))
        self.repo.save_report(report)
        try:
            for platform in PLATFORMS:
                audit = {"status": "disabled", "metrics": counters(), "queries": [], "sources": {},
                         "errors": [], "notes": [], "duration_seconds": 0}
                report["platforms"][platform] = audit
                if not profile.platforms[platform]:
                    continue
                pstart = self.clock()
                queries = generate(profile, platform)
                audit["metrics"]["queries_generated"] = len(queries)
                connector = self.connectors.get(platform)
                if connector:
                    connector.time_window = window
                ready, reason = connector.available() if connector else (False, "connector_not_implemented")
                if not queries or not ready:
                    audit["status"] = "failed"
                    audit["errors"] = ["no_enabled_values" if not queries else reason]
                    audit["metrics"]["errors"] = 1
                    audit["queries"] = [{**asdict(q), "status": "not_executed", "errors": [audit["errors"][0]]} for q in queries]
                    self.repo.save_report(report)
                    continue
                seen_relevant, throttle = set(), False
                audit['status'] = 'running'
                for query in queries:
                    qa = {**asdict(query), "status": "running", "errors": []}
                    audit["queries"].append(qa)
                    self.repo.save_report(report)
                    if throttle:
                        qa.update(status="failed", errors=["skipped_after_rate_limit"])
                        continue
                    policy, m = profile.policies[platform], audit["metrics"]
                    incremental = self.repo.incremental_state(platform,query.term) if query.dimension=='saved_source' else None
                    connector.incremental_state = incremental or {}
                    key = digest([platform, connector.version, query.text, policy.items_per_query, policy.pages_per_query,
                                  profile.time_window.hours,window.start_time[:10],window.end_time[:10],
                                  window.start_time if profile.time_window.hours is None else None,
                                  window.end_time if profile.time_window.hours is None else None,
                                  getattr(connector,'cache_scope',None),
                                  (incremental or {}).get('last_item_id')])
                    cached = self.repo.cache_get(key, self.clock(), policy.cache_ttl_seconds)
                    try:
                        if cached is not None:
                            batch = Batch(**cached)
                            m["cached_queries"] += 1
                        else:
                            m["queries_executed"] += 1
                            attempt_id = uuid.uuid4().hex
                            with self.repo.db:
                                self.repo.db.execute('INSERT INTO collection_attempts VALUES (?,?,?,?,?,?,?,?)',
                                    (attempt_id,report['id'],platform,query.text,now(),None,'running','{}'))
                            try:
                                batch = self.request(connector, query, policy, m)
                            finally:
                                with self.repo.db:
                                    self.repo.db.execute('UPDATE collection_attempts SET finished_at=?,status=?,payload=? WHERE id=?',
                                        (now(),'failed' if sys.exc_info()[0] else 'complete',encode(m),attempt_id))
                            if len(batch.records) > policy.items_per_query:
                                batch.records = batch.records[:policy.items_per_query]
                                batch.warnings.append("connector_exceeded_item_limit")
                            if not batch.warnings and not batch.rate_limited:
                                self.repo.cache_put(key, self.clock(), asdict(batch))
                        if batch.rate_limited:
                            throttle = True
                            m["rate_limited_calls"] += 1
                            if not batch.warnings:
                                batch.warnings.append("rate_limited_partial_batch")
                        qa["from_cache"] = cached is not None
                        qa["retrieval_status"] = "cached" if cached is not None else "live"
                        self.repo.response(report["id"], platform, query.text, batch.raw_response)
                        qa["errors"].extend(batch.warnings)
                        qa['notes'] = list(batch.notes)
                        audit['notes'].extend(n for n in batch.notes if n not in audit['notes'])
                        m["errors"] += len(batch.warnings)
                        m['items_discovered'] += len(batch.records)
                        for raw in batch.records:
                            m["items_checked"] += 1
                            rid, existing = self.repo.store_raw(report["id"], platform, query.text, raw)
                            try:
                                event = connector.normalize(raw).validate()
                                if event.platform != platform:
                                    raise ValueError("platform mismatch")
                                analysis = analyze(event, profile)
                                classification = window.classify(event.published_at)
                                if event.metadata.get('time_precision') == 'day' and event.published_at:
                                    from app.config.time_window import instant
                                    from datetime import timedelta
                                    day = instant(event.published_at)
                                    if day+timedelta(days=1) > instant(window.start_time) and day <= instant(window.end_time):
                                        if not (day >= instant(window.start_time) and day+timedelta(days=1) <= instant(window.end_time)):
                                            classification = 'UNKNOWN_TIME'
                                analysis['time_classification'] = classification
                                analysis['matched_objective'] = analysis['relevant']
                                analysis['relevant'] = analysis['relevant'] and classification == 'CURRENT'
                                time_counter = {'CURRENT':'within_time_window','STALE':'items_stale',
                                                'UNKNOWN_TIME':'items_unknown_time','AFTER_WINDOW':'items_after_window'}[classification]
                                m[time_counter] += 1
                                identity_exists = self.repo.db.execute('SELECT 1 FROM events WHERE platform=? AND item_id=?',
                                                                      (platform,event.item_id)).fetchone() is not None
                            except Exception:
                                self.repo.raw_error(rid, "normalization_failed")
                                qa["errors"].append("normalization_failed")
                                m["errors"] += 1
                                continue
                            eid = self.repo.store_event(report["id"], rid, event, analysis)
                            self.repo.update_source_state(report['id'],platform,event,cached is not None)
                            m['items_duplicate'] += int(identity_exists)
                            source = audit["sources"].setdefault(event.source_id, {
                                "source_id": event.source_id, "source_type": event.source_type,
                                "account": event.account, "status": "complete", "last_audited": now(),
                                "scope": "items returned by query; not full source history",
                                "items_checked": 0, "new_items": 0, "cached_items": 0, "relevant_items": 0,
                                "requests": None, "duration_seconds": None,
                                "errors": [], "queries": [], "all_items_from_query_cache": True})
                            source[time_counter] = source.get(time_counter,0)+1
                            source['items_duplicate'] = source.get('items_duplicate',0)+int(identity_exists)
                            source["all_items_from_query_cache"] &= cached is not None
                            if query.text not in source["queries"]:
                                source["queries"].append(query.text)
                            source["items_checked"] += 1
                            kind = "cached_items" if existing else "new_items"
                            source[kind] += 1
                            m[kind] += 1
                            if analysis["relevant"] and eid not in seen_relevant:
                                seen_relevant.add(eid)
                                m["relevant_items"] += 1
                                source["relevant_items"] += 1
                        qa["status"] = "partial" if qa["errors"] else "complete"
                    except ConnectorError as exc:
                        throttle = exc.rate_limited
                        qa.update(status="failed", errors=[exc.code])
                        m["errors"] += 1
                        if query.dimension=='saved_source':
                            self.repo.source_failure(platform,query.term,exc.rate_limited)
                    self.repo.save_report(report)
                # Reflect retrieval problems on sources actually associated with those queries.
                for source in audit["sources"].values():
                    related = [q for q in audit["queries"] if q["text"] in source["queries"]]
                    source["status"] = aggregate_status([q["status"] for q in related])
                    source["errors"] = [err for q in related for err in q["errors"]]
                audit["metrics"]["sources_discovered"] = len(audit["sources"])
                audit["status"] = aggregate_status([q["status"] for q in audit["queries"]])
                audit['errors'] = list(dict.fromkeys(e for q in audit['queries'] for e in q['errors']))
                audit["duration_seconds"] = round(self.clock()-pstart, 3)
                self.repo.save_report(report)
            report["status"] = aggregate_status([a["status"] for a in report["platforms"].values()])
        except (Exception, KeyboardInterrupt):
            report["status"] = "failed"
            report["fatal_error"] = "interrupted_or_internal_failure"
            raise
        finally:
            report["finished_at"] = now()
            report["duration_seconds"] = round(self.clock()-started, 3)
            for key in report["metrics"]:
                values = [a["metrics"][key] for a in report["platforms"].values()]
                report["metrics"][key] = None if any(v is None for v in values) else sum(values)
            self.repo.save_report(report)
        return report
