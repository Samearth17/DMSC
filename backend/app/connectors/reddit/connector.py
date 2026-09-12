from datetime import datetime, timezone
import json
import os
import urllib.request
import urllib.error
import urllib.parse
from app.connectors.base import Batch, ConnectorError, SourceConnector
from app.connectors.news.connector import NoRedirect
from app.normalization.models import WatchtowerEvent


class RedditConnector(SourceConnector):
    platform = "reddit"
    def available(self):
        return (True,"ready_oauth") if os.getenv("WATCHTOWER_REDDIT_TOKEN") else (False,"reddit_approved_oauth_token_required")

    def search(self, query, policy):
        token=os.getenv("WATCHTOWER_REDDIT_TOKEN")
        if not token:
            raise ConnectorError("reddit_approved_oauth_token_required",requests=0)
        url="https://oauth.reddit.com/search?"+urllib.parse.urlencode({"q":query.text,"type":"link",
            "sort":"new","limit":policy.items_per_query,"raw_json":1})
        req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,
            "User-Agent":os.getenv("WATCHTOWER_REDDIT_USER_AGENT","desktop:watchtower-monitor:0.3 (local public-information audit)")})
        try:
            with urllib.request.build_opener(NoRedirect).open(req,timeout=policy.timeout_seconds) as response:
                body=response.read(4*1024*1024+1)
            if len(body)>4*1024*1024:
                raise ConnectorError("reddit_response_too_large",requests=1)
            payload=json.loads(body)
            records=[r["data"] for r in payload["data"]["children"] if r.get("kind")=="t3"]
            return Batch(records[:policy.items_per_query],requests=1,raw_response=body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code="reddit_token_expired_or_invalid" if exc.code==401 else "reddit_access_denied" if exc.code==403 else f"reddit_http_{exc.code}"
            raise ConnectorError(code,requests=1,rate_limited=exc.code==429,retryable=500<=exc.code<600) from None
        except (urllib.error.URLError,OSError,TimeoutError):
            raise ConnectorError("reddit_network_error",requests=1,retryable=True) from None
        except (KeyError,ValueError,TypeError):
            raise ConnectorError("reddit_invalid_response",requests=1) from None

    def normalize(self, raw):
        published=datetime.fromtimestamp(raw["created_utc"],timezone.utc).isoformat() if raw.get("created_utc") else None
        return WatchtowerEvent(platform=self.platform,source_type="subreddit",source_id=raw.get("subreddit_id") or raw["subreddit"],
            item_id=raw["name"],url="https://www.reddit.com"+raw["permalink"],account=raw.get("author"),
            content=(raw.get("title") or "")+"\n"+(raw.get("selftext") or ""),published_at=published,
            engagement={"score":raw.get("score"),"comments":raw.get("num_comments")},
            metadata={"subreddit":raw.get("subreddit"),"collection_scope":"public_api_search_posts"}).validate()
