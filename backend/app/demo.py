from app.auditing.engine import AuditEngine
from app.config.profile import Profile
from app.connectors.base import Batch
from app.connectors.news.connector import NewsConnector


class DemoConnector(NewsConnector):
    version = "synthetic-demo-1"
    def search(self, query, policy):
        return Batch([{"id": "synthetic-001", "url": "https://example.org/demo-only",
                       "source_url": "https://example.org", "source_name": "SYNTHETIC DEMO SOURCE",
                       "title": "SYNTHETIC DEMO: example topic", "description": "Not a real-world report."}], requests=0)


def demo(repository):
    profile = Profile.parse({"name": "SYNTHETIC OFFLINE DEMO", "platforms": {"news": True},
                             "dimensions": {"keywords": {"enabled": True, "values": ["example topic"]}}})
    report = AuditEngine(repository, {"news": DemoConnector()}).run(profile)
    report["demo_notice"] = "Synthetic fixtures only. No external platform was contacted."
    repository.save_report(report)
    return report
