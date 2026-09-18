from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from app.connectors.base import Batch, ConnectorError, SourceConnector
from app.connectors.news.connector import FeedRedirect
from app.normalization.models import WatchtowerEvent


class MetaConnector(SourceConnector):
    """Indexed Meta (Facebook) discovery via public search feeds and news aggregation.
    
    Provides high-yield, real-time public Facebook posts, news articles, and status updates
    without requiring authentication or fragile HTML scraping.
    """
    platform = "meta"
    version = "2-google-news-facebook-indexed"
    MAX_BYTES = 4 * 1024 * 1024

    def available(self) -> tuple[bool, str]:
        return True, "ready"

    def search(self, query, policy):
        text = query.text.strip()
        if not text:
            return Batch([], requests=1)

        # Build query targeting facebook.com
        search_query = f"{text} site:facebook.com"
        window = getattr(self, "time_window", None)
        if window:
            from datetime import timedelta
            from app.config.time_window import instant
            tomorrow = (instant(window.end_time) + timedelta(days=1)).date().isoformat()
            search_query += f" after:{window.start_time[:10]} before:{tomorrow}"

        # Primary discovery: Google News RSS indexed Facebook posts
        params = {
            "q": search_query,
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        }
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Watchtower/0.3 public RSS monitor (Meta/Facebook Discovery)"},
        )
        redirects = FeedRedirect()

        try:
            with urllib.request.build_opener(redirects).open(req, timeout=policy.timeout_seconds) as response:
                data = response.read(self.MAX_BYTES + 1)
            if len(data) > self.MAX_BYTES:
                raise ConnectorError("meta_response_too_large", requests=1 + redirects.followed)
            batch = self._parse_rss(data, policy.items_per_query)
            batch.requests = 1 + redirects.followed
            return batch
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ConnectorError("meta_http_429", rate_limited=True, requests=1 + redirects.followed) from None
            # Fallback to secondary search
            return self._fallback_bing(query, policy)
        except (urllib.error.URLError, TimeoutError, OSError):
            return self._fallback_bing(query, policy)
        except (ET.ParseError, ValueError):
            return self._fallback_bing(query, policy)

    def _parse_rss(self, data: bytes, limit: int) -> Batch:
        if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
            raise ValueError("Invalid feed content")
        root = ET.fromstring(data)
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("Expected an RSS feed")

        records = []
        for item in root.findall("./channel/item")[:limit]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            guid = item.findtext("guid") or link
            pub_date = item.findtext("pubDate")
            desc = item.findtext("description") or ""
            source = item.find("source")
            source_name = source.text if source is not None else "Facebook"

            clean_title = re.sub(r"\s*-\s*facebook\.com\s*$", "", title, flags=re.IGNORECASE).strip()

            records.append({
                "id": guid,
                "url": link,
                "title": clean_title,
                "raw_title": title,
                "description": desc,
                "published": pub_date,
                "source_name": source_name,
                "platform": "meta",
                "raw_xml": ET.tostring(item, encoding="unicode"),
            })

        return Batch(records, requests=1, raw_response=data.decode("utf-8", errors="replace"))

    def _fallback_bing(self, query, policy) -> Batch:
        term = f"{query.text} site:facebook.com"
        url = "https://www.bing.com/search?" + urllib.parse.urlencode({
            "format": "rss",
            "q": term,
            "count": policy.items_per_query,
        })
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Watchtower/0.3 public search monitor"},
            )
            with urllib.request.urlopen(req, timeout=policy.timeout_seconds) as r:
                body = r.read(self.MAX_BYTES + 1)
            root = ET.fromstring(body)
            records = []
            for item in root.findall("./channel/item")[:policy.items_per_query]:
                link = item.findtext("link") or ""
                title = item.findtext("title") or ""
                desc = item.findtext("description") or ""
                records.append({
                    "id": link,
                    "url": link,
                    "title": title,
                    "raw_title": title,
                    "description": desc,
                    "published": None,
                    "source_name": "Facebook",
                    "platform": "meta",
                    "raw_xml": ET.tostring(item, encoding="unicode"),
                })
            return Batch(records, requests=1, raw_response=body.decode("utf-8", errors="replace"))
        except Exception:
            return Batch([], requests=1, warnings=["meta_fallback_unreachable"])

    def normalize(self, record: dict) -> WatchtowerEvent:
        published = None
        if record.get("published"):
            try:
                dt = parsedate_to_datetime(record["published"])
                published = dt.astimezone(timezone.utc).isoformat() if dt.tzinfo else None
            except (ValueError, TypeError, OverflowError):
                pass

        raw_content = (record.get("title") or "") + "\n" + (record.get("description") or "")
        clean_content = unescape(re.sub(r"<[^>]+>", " ", raw_content)).strip()

        return WatchtowerEvent(
            platform=self.platform,
            source_type="facebook_post",
            source_id="facebook.com",
            item_id=str(record.get("id") or record.get("url") or ""),
            url=record.get("url") or "",
            account=record.get("source_name") or "Facebook",
            author=record.get("source_name") or "Facebook",
            published_at=published,
            published_at_source="facebook_indexed_feed" if published else None,
            time_confidence=1.0 if published else None,
            title=record.get("title"),
            content=clean_content or record.get("title") or "Facebook post",
            metadata={
                "title": record.get("title"),
                "collection_scope": "facebook_public_indexed",
                "url_type": "aggregator_link",
                "full_text_status": "not_collected",
            },
        ).validate()
