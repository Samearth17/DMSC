"""Bounded isolated Instaloader worker with Selenium and indexed discovery fallbacks.

Provides resilient Instagram collection across public profiles, hashtags, and breaking news.
"""
import contextlib
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import islice
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def _safe_raw(post):
    """Return a JSON-serializable snapshot of a Post's internal dict."""
    try:
        raw = post._asdict()
    except Exception:
        return {}

    def _coerce(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, dict):
            return {str(k): _coerce(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_coerce(v) for v in value]
        return str(value)

    return _coerce(raw)


def _iter_hashtag_posts(loader, tag, limit=50):
    """Safely extract Post objects from Instagram hashtag feed."""
    import instaloader as il
    tag = str(tag).lstrip('#').strip()
    if not tag:
        return
    seen_ids = set()
    try:
        hashtag = il.Hashtag.from_name(loader.context, tag)
    except Exception:
        return

    node = getattr(hashtag, "_node", {})
    top = node.get("top") or node.get("recent") or {}

    while True:
        sections = top.get("sections", []) if isinstance(top, dict) else []
        for s in sections:
            if not isinstance(s, dict):
                continue
            lc = s.get("layout_content", {})
            if not isinstance(lc, dict):
                continue
            media_nodes = []
            if "medias" in lc and isinstance(lc["medias"], list):
                media_nodes.extend(item.get("media") for item in lc["medias"] if isinstance(item, dict) and item.get("media"))
            for key in ("one_by_two_item", "two_by_two_item", "one_by_two_left", "one_by_two_right"):
                sub = lc.get(key)
                if isinstance(sub, dict) and "clips" in sub:
                    clips_items = sub["clips"].get("items", [])
                    if isinstance(clips_items, list):
                        media_nodes.extend(item.get("media") for item in clips_items if isinstance(item, dict) and item.get("media"))
            if "fill_items" in lc and isinstance(lc["fill_items"], list):
                media_nodes.extend(item.get("media") for item in lc["fill_items"] if isinstance(item, dict) and item.get("media"))

            for m in media_nodes:
                mid = str(m.get("id") or m.get("pk") or "")
                if mid and mid in seen_ids:
                    continue
                if mid:
                    seen_ids.add(mid)
                try:
                    p = il.Post.from_iphone_struct(loader.context, m)
                    if hasattr(p, "_node") and isinstance(p._node, dict):
                        if "edge_media_to_comment" not in p._node and "comments" in p._node:
                            p._node["edge_media_to_comment"] = {"count": p._node["comments"]}
                        if "edge_media_preview_like" not in p._node and "like_count" in p._node:
                            p._node["edge_media_preview_like"] = {"count": p._node["like_count"]}
                    yield p
                    if len(seen_ids) >= limit:
                        return
                except Exception:
                    continue

        max_id = top.get("next_max_id") if isinstance(top, dict) else None
        more = top.get("more_available") if isinstance(top, dict) else False
        if not max_id or not more or len(seen_ids) >= limit:
            break

        try:
            resp = loader.context.get_json("api/v1/tags/web_info/", params={"tag_name": tag, "max_id": max_id})
            data = resp.get("data") if isinstance(resp, dict) else {}
            top = (data.get("top") or data.get("recent") or {}) if isinstance(data, dict) else {}
        except Exception:
            break

    if not seen_ids and hasattr(hashtag, "get_posts"):
        try:
            for p in islice(hashtag.get_posts(), limit):
                yield p
        except Exception:
            pass


def _search_indexed_instagram_posts(term, limit=10, time_window_str=None):
    """Google News RSS indexed discovery for real-time Instagram breaking news & posts."""
    query = f"{term} site:instagram.com"
    if time_window_str:
        try:
            from app.config.time_window import TimeWindow, instant
            from datetime import timedelta
            tw = TimeWindow.parse(time_window_str)
            tomorrow = (instant(tw.end_time) + timedelta(days=1)).date().isoformat()
            query += f" after:{tw.start_time[:10]} before:{tomorrow}"
        except Exception:
            pass

    params = {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Watchtower/0.3 public RSS monitor (Instagram Discovery)"}
    )
    items = []
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = resp.read(4 * 1024 * 1024)
        root = ET.fromstring(data)
        for item in root.findall("./channel/item")[:limit]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            guid = item.findtext("guid") or link
            pub = item.findtext("pubDate")
            desc = item.findtext("description") or ""
            dt_str = None
            if pub:
                try:
                    dt_str = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
                except Exception:
                    pass

            clean_title = re.sub(r"\s*-\s*instagram\.com\s*$", "", title, flags=re.IGNORECASE).strip()
            shortcode = guid.split("/")[-1] if "p/" in link else guid

            items.append({
                "id": str(guid),
                "shortcode": shortcode,
                "owner_id": "instagram",
                "username": "Instagram",
                "caption": clean_title + ("\n" + desc if desc else ""),
                "title": clean_title,
                "url": link,
                "published_at": dt_str,
                "media": [{"type": "image", "url": ""}],
                "engagement": {"likes": 0, "comments": 0},
                "discovery_method": "indexed_public_discovery",
                "collection_scope": "public_indexed_posts",
            })
    except Exception:
        pass
    return items


def _parse_time_bounds(data):
    since_dt, until_dt = None, None
    since_val = data.get('since')
    if since_val:
        try:
            s = str(since_val).replace('Z', '+00:00')
            dt = datetime.fromisoformat(s)
            since_dt = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            pass
    elif data.get('hours'):
        try:
            from datetime import timedelta
            since_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=float(data['hours']))
        except Exception:
            pass
    until_val = data.get('until')
    if until_val:
        try:
            u = str(until_val).replace('Z', '+00:00')
            dt = datetime.fromisoformat(u)
            until_dt = dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
        except Exception:
            pass
    return since_dt, until_dt


def collect(data):
    started = time.monotonic()
    import instaloader as il
    from instaloader import exceptions as ex

    class StopOn429(il.RateController):
        def handle_429(self, query_type):
            raise ex.TooManyRequestsException("rate_limited")

    query = data.get('query', {'dimension': 'keywords', 'term': ''})
    policy = data.get('policy', {'timeout_seconds': 60, 'items_per_query': 10})
    timeout_budget = float(policy.get("timeout_seconds", 60))
    safety_buffer = min(5.0, timeout_budget * 0.2) if timeout_budget > 10 else 1.0

    def time_budget_approaching():
        return (time.monotonic() - started) >= (timeout_budget - safety_buffer)

    loader = il.Instaloader(
        download_pictures=False, download_videos=False,
        download_video_thumbnails=False, download_geotags=False, download_comments=False,
        save_metadata=False, compress_json=False, quiet=True, max_connection_attempts=1,
        request_timeout=min(policy["timeout_seconds"], 20), rate_controller=StopOn429
    )

    records, warnings, notes = [], [], []
    method = "hashtag" if query.get("dimension") == "hashtags" else "profile_search"
    max_items = int(data.get('limit')) if data.get('operation') == 'scrape' and data.get('limit') else policy["items_per_query"]

    def append(post):
        boundary = data.get('incremental', {}).get('last_item_id')
        if boundary and str(post.mediaid) == str(boundary):
            if 'incremental_boundary_reached' not in notes:
                notes.append('incremental_boundary_reached')
            return False
        if len(records) >= max_items:
            return False
        node = getattr(post, "_node", {}) if isinstance(getattr(post, "_node", None), dict) else {}
        likes = (node.get("edge_media_preview_like", {}).get("count")
                 if isinstance(node.get("edge_media_preview_like"), dict)
                 else node.get("likes"))
        if likes is None:
            try:
                likes = post.likes
            except Exception:
                likes = 0

        comments = (node.get("edge_media_to_comment", {}).get("count")
                    if isinstance(node.get("edge_media_to_comment"), dict)
                    else node.get("comments"))
        if comments is None:
            try:
                comments = post.comments
            except Exception:
                comments = 0

        records.append({
            "id": str(post.mediaid), "shortcode": post.shortcode, "owner_id": str(post.owner_id),
            "username": post.owner_username, "caption": post.caption,
            "published_at": post.date_utc.replace(tzinfo=timezone.utc).isoformat(),
            "media": [{"type": "video" if post.is_video else "image", "url": post.url}],
            "engagement": {"likes": likes, "comments": comments},
            "raw_node": _safe_raw(post), "discovery_method": method
        })
        return True

    try:
        access = data.get('access', {})
        session = access.get('session_file') or os.getenv('WATCHTOWER_INSTAGRAM_SESSION')
        username = access.get('username') or os.getenv('WATCHTOWER_INSTAGRAM_USERNAME')
        has_session = False

        if session and username:
            try:
                from app.connectors.instagram.access import read_cookies
                loader.load_session(username, read_cookies(session))
                has_session = True
            except Exception:
                has_session = False

        # Operation 1: Connection Test
        if data.get('operation') == 'test':
            if not has_session:
                return {'error': 'instagram_not_configured'}
            logged_in = loader.test_login()
            return {'status': 'Connected'} if logged_in else {'error': 'instagram_session_expired'}

        # Operation 2: Dedicated Scraper
        if data.get('operation') == 'scrape':
            scrape_type = data.get('scrape_type', 'profile')
            target = str(data.get('target', '')).strip()
            limit = int(data.get('limit', 10))
            since_dt, until_dt = _parse_time_bounds(data)
            profile_info = None

            if scrape_type == 'profile':
                user = target.lstrip('@').strip()
                # Try Instaloader if session is valid
                if has_session:
                    try:
                        profile_obj = il.Profile.from_username(loader.context, user)
                        if profile_obj:
                            profile_info = {
                                'username': profile_obj.username,
                                'display_name': profile_obj.full_name,
                                'followers': profile_obj.followers,
                                'following': profile_obj.followees,
                                'post_count': profile_obj.mediacount,
                                'biography': profile_obj.biography,
                                'verified_account': profile_obj.is_verified,
                                'url': f'https://www.instagram.com/{profile_obj.username}/'
                            }
                            if profile_obj.is_private:
                                warnings.append('instagram_private_profile_skipped')
                                return {'profile': profile_info, 'records': [], 'warnings': ['This profile is private. Posts cannot be viewed without following.'], 'notes': []}

                            consecutive_old = 0
                            for post in profile_obj.get_posts():
                                pdate = getattr(post, 'date_utc', None)
                                is_pinned = getattr(post, 'is_pinned', False)
                                if pdate:
                                    if until_dt and pdate > until_dt:
                                        continue
                                    if since_dt and pdate < since_dt:
                                        if is_pinned:
                                            continue
                                        consecutive_old += 1
                                        if consecutive_old >= 3:
                                            break
                                        continue
                                    else:
                                        consecutive_old = 0
                                if not append(post):
                                    break
                                if len(records) >= limit:
                                    break
                            return {'profile': profile_info, 'records': records, 'warnings': warnings, 'notes': notes}
                    except Exception:
                        pass

                # Fallback to headless Selenium engine for accurate public extraction
                try:
                    from app.connectors.instagram.selenium_engine import SeleniumInstagramEngine
                    sel = SeleniumInstagramEngine()
                    if sel.is_available():
                        sel_result = sel.scrape_profile(user, limit=limit, since_dt=since_dt, until_dt=until_dt)
                        if sel_result and not sel_result.get('error') and (sel_result.get('records') or sel_result.get('profile')):
                            return sel_result
                except Exception:
                    pass

                # Final fallback: public indexed discovery
                indexed_items = _search_indexed_instagram_posts(f"@{user}", limit=limit)
                if indexed_items:
                    profile_info = {
                        'username': user,
                        'display_name': user,
                        'followers': None,
                        'following': None,
                        'post_count': len(indexed_items),
                        'biography': 'Discovered via public indexed news & posts',
                        'verified_account': False,
                        'url': f'https://www.instagram.com/{user}/',
                        'engine': 'indexed_public_discovery'
                    }
                    return {'profile': profile_info, 'records': indexed_items, 'warnings': ['instagram_session_unconfigured_using_public_indexed_discovery'], 'notes': notes}

                return {'error': 'instagram_collection_error', 'notes': [f'Could not find public profile @{user}']}

            elif scrape_type == 'hashtag':
                tag = target.lstrip('#').strip()
                method = "hashtag"
                if has_session:
                    try:
                        search_limit = max(limit * 3, 30) if (since_dt or until_dt) else limit
                        for post in _iter_hashtag_posts(loader, tag, search_limit):
                            pdate = getattr(post, 'date_utc', None)
                            if pdate:
                                if until_dt and pdate > until_dt:
                                    continue
                                if since_dt and pdate < since_dt:
                                    continue
                            if not append(post):
                                break
                            if len(records) >= limit:
                                break
                    except Exception:
                        pass

                # If no records via Instaloader, use indexed discovery
                if not records:
                    indexed_items = _search_indexed_instagram_posts(f"#{tag}", limit=limit)
                    records.extend(indexed_items)

                return {'profile': None, 'records': records, 'warnings': warnings, 'notes': notes}

        # Operation 3: Profile Search
        if data.get('operation') == 'profiles':
            if not has_session:
                return {'error': 'instagram_not_configured'}
            profiles = []
            candidates = il.TopSearchResults(loader.context, data['search']).get_profiles()
            for profile in islice(candidates, 20):
                if time_budget_approaching():
                    break
                if profile.is_private:
                    continue
                followers = profile.followers
                if followers is None and (data.get('minimum') is not None or data.get('maximum') is not None):
                    continue
                if data.get('minimum') is not None and followers < data['minimum']:
                    continue
                if data.get('maximum') is not None and followers > data['maximum']:
                    continue
                profiles.append({
                    'username': profile.username, 'display_name': profile.full_name,
                    'url': 'https://www.instagram.com/' + profile.username + '/', 'biography': profile.biography,
                    'followers': followers, 'following': profile.followees, 'post_count': profile.mediacount,
                    'verified_account': profile.is_verified, 'image': profile.profile_pic_url,
                    'follower_count_source': 'instagram_profile', 'private': False
                })
            return {'profiles': profiles, 'scope': 'At most 20 discovered public profiles; follower filtering is local, not global search.'}

        # General Search (Keyword / Hashtag in Audits or Find Related Coverage)
        if method == "hashtag":
            tag = query.get("term", "").lstrip("#").strip()
            if has_session:
                try:
                    for post in _iter_hashtag_posts(loader, tag, policy["items_per_query"]):
                        if time_budget_approaching():
                            if 'instagram_time_budget_reached' not in notes:
                                notes.append('instagram_time_budget_reached')
                            break
                        if not append(post):
                            break
                        if data.get('time_window'):
                            from app.config.time_window import TimeWindow
                            if TimeWindow.parse(data['time_window']).classify(records[-1]['published_at']) == 'STALE':
                                break
                except Exception:
                    pass
            if not records:
                indexed_items = _search_indexed_instagram_posts(f"#{tag}", policy["items_per_query"], data.get('time_window'))
                records.extend(indexed_items)
        else:
            # Full keyword / breaking news search
            term = query.get("term", "").strip()
            if has_session:
                try:
                    if query.get('dimension') == 'saved_source':
                        profiles = [il.Profile.from_username(loader.context, term)]
                    else:
                        profiles = il.TopSearchResults(loader.context, term.lstrip("@")).get_profiles()

                    for profile in islice(profiles, 3):
                        if time_budget_approaching():
                            if 'instagram_time_budget_reached' not in notes:
                                notes.append('instagram_time_budget_reached')
                            break
                        if profile.is_private:
                            warnings.append("instagram_private_profile_skipped")
                            continue
                        remaining = policy["items_per_query"] - len(records)
                        for post in islice(profile.get_posts(), remaining):
                            if time_budget_approaching():
                                if 'instagram_time_budget_reached' not in notes:
                                    notes.append('instagram_time_budget_reached')
                                break
                            if not append(post):
                                break
                            if data.get('time_window'):
                                from app.config.time_window import TimeWindow
                                if TimeWindow.parse(data['time_window']).classify(records[-1]['published_at']) == 'STALE':
                                    break
                        if len(records) >= policy["items_per_query"] or time_budget_approaching():
                            if time_budget_approaching() and 'instagram_time_budget_reached' not in notes:
                                notes.append('instagram_time_budget_reached')
                            break
                except Exception:
                    pass

            # Augment with indexed public discovery for breaking news coverage
            if len(records) < policy["items_per_query"]:
                needed = policy["items_per_query"] - len(records)
                indexed_items = _search_indexed_instagram_posts(term, needed, data.get('time_window'))
                existing_urls = {r.get('url') for r in records if r.get('url')}
                for it in indexed_items:
                    if it.get('url') not in existing_urls:
                        records.append(it)
                        existing_urls.add(it.get('url'))

    except Exception as exc:
        if isinstance(exc, ex.TooManyRequestsException):
            code = "instagram_rate_limited"
        elif isinstance(exc, ex.LoginRequiredException):
            code = "instagram_login_required"
        elif isinstance(exc, ex.BadCredentialsException):
            code = 'instagram_authentication_failed'
        elif isinstance(exc, ex.AbortDownloadException):
            code = 'instagram_access_control_required'
        elif isinstance(exc, ex.ConnectionException):
            code = "instagram_access_or_network_error"
        else:
            code = "instagram_collection_error"
        if not records:
            return {"error": code}
        warnings.append(code)
    finally:
        loader.close()

    return {"records": records, "warnings": warnings, "notes": notes}


if __name__ == "__main__":
    try:
        data = json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(sys.stderr):
            result = collect(data)
        out = json.dumps(result, ensure_ascii=False).encode('utf-8')
        sys.stdout.buffer.write(out + b'\n')
    except Exception:
        sys.stdout.buffer.write(b'{"error":"instagram_worker_error"}\n')
