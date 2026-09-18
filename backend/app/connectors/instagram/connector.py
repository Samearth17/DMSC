from dataclasses import asdict
import importlib.util
import json
import subprocess
import sys
from app.connectors.base import Batch, ConnectorError, SourceConnector
from app.normalization.models import WatchtowerEvent


class InstagramConnector(SourceConnector):
    platform = "instagram"
    version = "1-instaloader-public"

    def __init__(self):
        self.access = {}
        self.cache_scope = None

    def operation(self, data, timeout=60):
        import os
        from pathlib import Path
        data = {**data,'access':dict(self.access)}
        backend_dir = str(Path(__file__).resolve().parents[3])
        env = dict(os.environ)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONPATH'] = backend_dir + os.pathsep + env.get('PYTHONPATH', '')
        try:
            result = subprocess.run([sys.executable,'-m','app.connectors.instagram.worker'],
                input=json.dumps(data),capture_output=True,text=True,encoding='utf-8',timeout=timeout+5,check=False,
                cwd=backend_dir,env=env)
        except subprocess.TimeoutExpired:
            return {'error':'instagram_timeout'}
        try:
            return json.loads(result.stdout)
        except (ValueError,TypeError):
            return {'error':'instagram_worker_error'}

    def available(self):
        return (True,"ready_public_access_may_require_session") if importlib.util.find_spec("instaloader") else (False,"instaloader_not_installed")

    def search(self, query, policy):
        window=getattr(self,'time_window',None)
        data = self.operation({'query':asdict(query),'policy':asdict(policy),
                               'time_window':window.snapshot() if window else None,
                               'incremental':getattr(self,'incremental_state',{})},policy.timeout_seconds)
        if data.get("error"):
            raise ConnectorError(data["error"],rate_limited=data["error"] == "instagram_rate_limited")
        return Batch(data["records"],warnings=data.get("warnings",[]),notes=data.get('notes',[]),requests=None,
                     rate_limited="instagram_rate_limited" in data.get("warnings",[]))

    def normalize(self, record):
        item_url = record.get("url")
        if not item_url and record.get("shortcode"):
            item_url = "https://www.instagram.com/p/" + record["shortcode"] + "/"
        owner_id = str(record.get("owner_id") or record.get("username") or "instagram")
        item_id = str(record.get("id") or record.get("shortcode") or item_url or "")
        username = record.get("username") or record.get("author") or "Instagram"
        content = record.get("caption") or record.get("content") or record.get("title") or ""

        return WatchtowerEvent(
            platform=self.platform,
            source_type="account" if record.get("owner_id") else "post",
            source_id=owner_id,
            item_id=item_id,
            url=item_url or "",
            account=username,
            content=content,
            published_at=record.get("published_at"),
            engagement=record.get("engagement", {}),
            published_at_source='instagram_post' if record.get('published_at') else None,
            time_confidence=1.0 if record.get('published_at') else None,
            author=username,
            title=record.get("title"),
            media=record.get("media", []),
            metadata={
                "collection_scope": record.get("collection_scope", "public_posts_from_discovered_profiles_or_hashtag"),
                "transcript_status": record.get("transcript_status", "collected" if record.get("transcript_text") else "not_collected"),
                "transcript_text": record.get("transcript_text"),
                "discovery_method": record.get("discovery_method", "instaloader"),
            },
        ).validate()
