from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from app.connectors.base import Batch, ConnectorError, SourceConnector
from app.normalization.models import WatchtowerEvent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class FeedRedirect(urllib.request.HTTPRedirectHandler):
    """Only follow the provider's HTTPS RSS locale redirect, never arbitrary URLs."""
    def __init__(self):
        self.followed = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.hostname != "news.google.com" or target.path != "/rss/search" or target.username or target.password or target.port not in (None, 443):
            return None
        self.followed += 1
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NewsConnector(SourceConnector):
    """Google News public RSS search. Availability is not guaranteed.

    Collect feed metadata, not publisher full text; do not visit discovered URLs.
    """
    platform = "news"
    version = "3-time-and-feeds"
    MAX_BYTES = 4 * 1024 * 1024

    def search(self, query, policy):
        if query.dimension == 'saved_source':
            from app.connectors.web.http import PublicHTTP, FetchError
            client = PublicHTTP(policy.timeout_seconds,self.MAX_BYTES)
            try:
                data, _, url = client.get(query.term)
                batch = self.parse(data,policy.items_per_query)
                for record in batch.records:
                    record['feed_url'] = url
                boundary=getattr(self,'incremental_state',{}).get('last_item_id')
                if boundary:
                    retained=[]
                    for record in batch.records:
                        if str(record.get('id'))==str(boundary):
                            batch.notes.append('incremental_boundary_reached')
                            break
                        retained.append(record)
                    batch.records=retained
                batch.requests = client.requests
                return batch
            except FetchError as exc:
                raise ConnectorError('news_'+exc.code,requests=client.requests,rate_limited=exc.status==429) from None
            except (ET.ParseError,ValueError):
                raise ConnectorError('news_invalid_feed',requests=client.requests) from None
        text = query.text
        window = getattr(self,'time_window',None)
        if window:
            # Expand to calendar days; exact instants are enforced centrally.
            from datetime import timedelta
            from app.config.time_window import instant
            tomorrow=(instant(window.end_time)+timedelta(days=1)).date().isoformat()
            text += f' after:{window.start_time[:10]} before:{tomorrow}'
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": text})
        req = urllib.request.Request(url, headers={"User-Agent": "Watchtower/0.3 public RSS monitor"})
        redirects = FeedRedirect()
        try:
            with urllib.request.build_opener(redirects).open(req, timeout=policy.timeout_seconds) as response:
                data = response.read(self.MAX_BYTES + 1)
            if len(data) > self.MAX_BYTES:
                raise ConnectorError("news_response_too_large", requests=1 + redirects.followed)
        except urllib.error.HTTPError as exc:
            raise ConnectorError(f"news_http_{exc.code}", rate_limited=exc.code == 429,
                                 retryable=500 <= exc.code < 600, requests=1 + redirects.followed) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ConnectorError("news_network_error", retryable=True, requests=1 + redirects.followed) from None
        try:
            batch = self.parse(data, policy.items_per_query)
        except (ET.ParseError, ValueError):
            raise ConnectorError("news_invalid_feed", requests=1 + redirects.followed) from None
        batch.requests = 1 + redirects.followed
        return batch

    @staticmethod
    def parse(data, limit):
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("XML entity declarations are not accepted")
        root = ET.fromstring(data)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("Expected an RSS feed")
        records = []
        for item in root.findall("./channel/item")[:limit]:
            source = item.find("source")
            records.append({"id": item.findtext("guid") or item.findtext("link"),
                            "url": item.findtext("link"), "title": item.findtext("title"),
                            "description": item.findtext("description"),
                            "published": item.findtext("pubDate"),
                            "source_name": source.text if source is not None else None,
                            "source_url": source.get("url") if source is not None else None,
                            "raw_xml": ET.tostring(item, encoding="unicode")})
        return Batch(records, requests=1, raw_response=data.decode("utf-8", errors="replace"))

    def normalize(self, record):
        published = None
        if record.get("published"):
            try:
                dt = parsedate_to_datetime(record["published"])
                published = dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
            except (ValueError, TypeError, OverflowError):
                pass
        return WatchtowerEvent(
            platform=self.platform, source_type="publisher" if record.get("source_url") else "feed",
            source_id=record.get('feed_url') or record.get("source_url") or "google-news-rss",
            item_id=str(record.get("id") or ""), url=record.get("url") or "",
            account=record.get("source_name"), published_at=published,
            published_at_source='rss_feed' if published else None,time_confidence=1.0 if published else None,
            title=record.get('title'),author=record.get('source_name'),
            content=unescape(re.sub(r"<[^>]+>", " ", (record.get("title") or "") + "\n" +
                                   (record.get("description") or ""))),
            metadata={"title": record.get("title"), "collection_scope": "feed_metadata",
                      "url_type": "aggregator_link", "full_text_status": "not_collected"}).validate()
