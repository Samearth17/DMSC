import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.auditing.engine import AuditEngine
from app.cli import main, safe_cell
from app.config.profile import Profile
from app.connectors.base import Batch, ConnectorError
from app.connectors.news.connector import NewsConnector
from app.connectors.youtube.connector import YouTubeConnector
from app.connectors.x.connector import XConnector
from app.discovery.queries import generate
from app.intelligence.rules import analyze
from app.storage.repository import Repository


def profile(**overrides):
    data = {"platforms": {"news": True}, "dimensions": {"keywords": {"enabled": True, "values": ["flood"]}},
            "policies": {"news": {"min_interval_seconds": 0, "backoff_seconds": 0}}}
    data.update(overrides)
    return Profile.parse(data)


def record(content="Flood report"):
    from datetime import datetime,timezone,timedelta
    from email.utils import format_datetime
    return {"id": "item-1", "url": "https://example.org/story", "source_url": "https://example.org",
            'published':format_datetime(datetime.now(timezone.utc)-timedelta(hours=1)),
            "source_name": "Example", "title": content, "description": "Public test fixture"}


class Fake(NewsConnector):
    version = "test-v1"
    def __init__(self, records=None, error=None):
        self.records = records if records is not None else [record()]
        self.error, self.calls = error, 0
    def search(self, query, policy):
        self.calls += 1
        if self.error:
            raise self.error
        return Batch(copy.deepcopy(self.records), requests=1)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")
    def tearDown(self):
        self.repo.close()
    def run_audit(self, p=None, c=None):
        return AuditEngine(self.repo, {"news": c or Fake()}, sleep=lambda _: None).run(p or profile())

    def test_disabled_values_never_enter_queries(self):
        p = profile(dimensions={"keywords": {"enabled": False, "values": ["PRIVATE_DISABLED"]},
                                "entities": {"enabled": True, "values": ["Example"]}})
        self.assertEqual([q.term for q in generate(p,"news")], ["Example"])
        self.assertEqual(generate(p,"x"), [])

    def test_query_cap_fairness_and_duplicate_removal(self):
        p = profile(dimensions={"keywords": {"enabled": True,"values": ["one", "ONE", "two"],"priority":90},
                                "entities": {"enabled": True,"values": ["three", "four"]}},
                    policies={"news": {"query_limit":3}})
        self.assertEqual([q.term for q in generate(p,"news")], ["one","three","two"])

    def test_reject_unknown_and_non_boolean_configuration(self):
        for data in [{"platforms":{"news":"false"}}, {"dimensions":{"typo":{}}},
                     {"policies":{"news":{"query_limit":0}}}, {"secret":"x"},
                     {"dimensions":{"keywords":{"values":[None]}}}]:
            with self.assertRaises(ValueError):
                Profile.parse(data)

    def test_complete_trace_and_persisted_snapshot(self):
        p = profile()
        result = self.run_audit(p)
        p.dimensions["keywords"].values.append("later")
        saved = self.repo.report(result["id"])
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["snapshot"]["dimensions"]["keywords"]["values"],["flood"])
        self.assertEqual(saved["metrics"]["new_items"],1)
        self.assertEqual(saved["metrics"]["relevant_items"],1)
        self.assertEqual(len(self.repo.source_history("news","https://example.org")),1)
        self.assertEqual(self.repo.events()[0]["analysis"]["evidence_level"],"Unverified")

    def test_cached_run_avoids_network_and_does_not_duplicate_events(self):
        connector = Fake()
        self.run_audit(c=connector)
        result = self.run_audit(c=connector)
        self.assertEqual(connector.calls,1)
        self.assertEqual(result["metrics"]["cached_queries"],1)
        self.assertEqual(result["metrics"]["requests"],0)
        self.assertEqual(result["metrics"]["cached_items"],1)
        self.assertEqual(result["metrics"]["new_items"],0)
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],1)

    def test_reanalysis_uses_current_profile_on_cached_content(self):
        first = profile(dimensions={"entities":{"enabled":True,"values":["flood"]}})
        self.run_audit(first)
        result = self.run_audit(profile())
        item = self.repo.events(result["id"])[0]
        self.assertEqual(item["analysis"]["matches"],{"keywords":["flood"]})

    def test_new_revision_keeps_old_raw_normalized_and_analysis(self):
        p = profile(policies={"news":{"cache_ttl_seconds":0,"min_interval_seconds":0}})
        old = self.run_audit(p, Fake([record("Old flood")]))
        new = self.run_audit(p, Fake([record("Updated flood")]))
        self.assertIn("Old flood",self.repo.events(old["id"])[0]["event"]["content"])
        self.assertIn("Updated flood",self.repo.events(new["id"])[0]["event"]["content"])
        self.assertEqual(new["metrics"]["new_items"],1)

    def test_missing_enabled_connector_is_failed_not_disabled(self):
        result = self.run_audit(profile(platforms={"news":True,"instagram":True}))
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["platforms"]["instagram"]["status"],"failed")
        self.assertEqual(result["platforms"]["x"]["status"],"disabled")

    def test_empty_profile_makes_no_calls(self):
        c = Fake()
        r = self.run_audit(profile(dimensions={}),c)
        self.assertEqual(r["status"],"failed")
        self.assertEqual(c.calls,0)

    def test_all_disabled_is_disabled(self):
        self.assertEqual(self.run_audit(profile(platforms={}))["status"],"disabled")

    def test_rate_limit_stops_remaining_queries(self):
        p = profile(dimensions={"keywords":{"enabled":True,"values":["one","two"]}})
        c = Fake(error=ConnectorError("limited",rate_limited=True,requests=1))
        r = self.run_audit(p,c)
        self.assertEqual(c.calls,1)
        self.assertEqual(r["metrics"]["rate_limited_requests"],1)
        self.assertEqual(r["platforms"]["news"]["queries"][1]["errors"],["skipped_after_rate_limit"])

    def test_retry_has_bounded_calls_and_honest_counters(self):
        c = Fake(error=ConnectorError("temporary",retryable=True,requests=1))
        r = self.run_audit(c=c)
        self.assertEqual(c.calls,2)
        self.assertEqual(r["metrics"]["failed_requests"],2)
        self.assertEqual(r["metrics"]["queries_executed"],1)

    def test_unknown_http_is_null(self):
        c = Fake(error=ConnectorError("yt_error"))
        r = self.run_audit(c=c)
        self.assertIsNone(r["metrics"]["requests"])

    def test_invalid_record_preserved_and_audit_partial(self):
        invalid = record()
        invalid["url"] = "javascript:alert(1)"
        r = self.run_audit(c=Fake([record(),invalid]))
        self.assertEqual(r["status"],"partial")
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM source_records").fetchone()[0],2)
        self.assertEqual(self.repo.db.execute("SELECT COUNT(*) FROM source_records WHERE error IS NOT NULL").fetchone()[0],1)

    def test_unexpected_connector_error_does_not_leak_exception_text(self):
        c = Fake(error=RuntimeError("PRIVATE COOKIE VALUE"))
        r = self.run_audit(c=c)
        self.assertNotIn("PRIVATE COOKIE",json.dumps(r))
        self.assertEqual(r["status"],"failed")

    def test_unicode_and_word_boundaries(self):
        event = Fake().normalize(record("भारत rainflood"))
        p = profile(dimensions={"keywords":{"enabled":True,"values":["भारत","flood"]}})
        self.assertEqual(analyze(event,p)["matches"],{"keywords":["भारत"]})

    def test_feed_preserves_xml_and_no_location_is_invented(self):
        xml = b'<rss><channel><item><guid>1</guid><title>A flood</title><link>https://example.org/1</link><source url="https://example.org">Example</source></item></channel></rss>'
        batch = NewsConnector.parse(xml,10)
        e = NewsConnector().normalize(batch.records[0])
        self.assertIn("<item>",batch.records[0]["raw_xml"])
        self.assertEqual(e.location,[])
        self.assertIsNone(e.published_at)

    def test_invalid_xml_and_entity_declarations_rejected(self):
        for xml in [b'<html/>',b'<!DOCTYPE rss [<!ENTITY x "xx">]><rss><channel/></rss>']:
            with self.assertRaises(ValueError):
                NewsConnector.parse(xml,10)

    @patch("app.connectors.youtube.connector.subprocess.run")
    def test_youtube_query_is_an_argument_no_download(self, run):
        run.return_value = subprocess.CompletedProcess([],0,json.dumps({"entries":[{"id":"abc","title":"A flood","channel_id":"chan"}]}),"")
        p = profile(platforms={"youtube":True})
        c = YouTubeConnector()
        b = c.search(generate(p,"youtube")[0],p.policies["youtube"])
        command = run.call_args.args[0]
        self.assertIn("--ignore-config",command)
        self.assertIn("--skip-download",command)
        self.assertTrue(command[-1].startswith('ytsearch'))
        self.assertEqual(c.normalize(b.records[0]).source_id,"chan")
        self.assertIsNone(b.requests)

    @patch("app.connectors.youtube.connector.subprocess.run")
    def test_youtube_timeout_is_reportable(self, run):
        run.side_effect = subprocess.TimeoutExpired("yt",1)
        p = profile(platforms={"youtube":True})
        with self.assertRaises(ConnectorError) as ctx:
            YouTubeConnector().search(generate(p,"youtube")[0],p.policies["youtube"])
        self.assertEqual(ctx.exception.code,"youtube_timeout")

    def test_csv_formula_safety(self):
        for value in ["=1+1"," @formula","\t+1","-cmd"]:
            self.assertTrue(safe_cell(value).startswith("'"))

    def test_interrupt_is_persisted(self):
        c = Fake(error=KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):
            self.run_audit(c=c)
        self.assertEqual(self.repo.report()["status"],"failed")

    def test_init_will_not_overwrite_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"config.json"
            self.assertEqual(main(["init","--out",str(path)]),0)
            original = path.read_text()
            self.assertEqual(main(["init","--out",str(path)]),1)
            self.assertEqual(path.read_text(),original)

    def test_empty_successful_search_is_complete(self):
        r = self.run_audit(c=Fake([]))
        self.assertEqual(r["status"],"complete")
        self.assertEqual(r["metrics"]["sources_discovered"],0)

    def test_expired_cache_recollects(self):
        c = Fake()
        self.run_audit(c=c)
        with self.repo.db:
            self.repo.db.execute("UPDATE query_cache SET created_at=0")
        self.run_audit(c=c)
        self.assertEqual(c.calls,2)

    @patch.dict("os.environ", {"WATCHTOWER_X_BRIDGE":"test_local_bridge"})
    @patch("app.connectors.x.connector.importlib.import_module")
    def test_x_thin_adapter_delegates_without_rewriting(self, importer):
        from types import SimpleNamespace
        event = Fake().normalize(record())
        event.platform = "x"
        original = {"original_legacy_field":"value"}
        bridge = SimpleNamespace(search=lambda q,p: Batch([original]),normalize=lambda raw: event)
        importer.return_value = bridge
        connector = XConnector()
        p = profile(platforms={"x":True})
        batch = connector.search(generate(p,"x")[0],p.policies["x"])
        self.assertIs(batch.records[0],original)
        self.assertEqual(connector.normalize(original).platform,"x")
        self.assertTrue(connector.available()[0])

    @patch("app.connectors.news.connector.urllib.request.build_opener")
    def test_news_search_encodes_query_and_uses_timeout(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = b'<rss><channel/></rss>'
        p = profile()
        batch = NewsConnector().search(generate(p,"news")[0],p.policies["news"])
        req = opener.return_value.open.call_args.args[0]
        self.assertIn("q=%22flood%22",req.full_url)
        self.assertEqual(batch.requests,1)
        self.assertEqual(opener.return_value.open.call_args.kwargs["timeout"],45)


if __name__ == "__main__":
    unittest.main()
