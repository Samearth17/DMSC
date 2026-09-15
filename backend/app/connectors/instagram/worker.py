"""Bounded isolated Instaloader worker. No downloads or private-profile collection."""
import contextlib
from datetime import date, datetime, timezone
from itertools import islice
import json
import os
import sys
import time


def _safe_raw(post):
    """Return a JSON-serializable snapshot of a Post's internal dict.

    post._asdict() is a private Instaloader API that returns a plain dict,
    but its values can include datetime objects, date objects, and other
    non-serializable Instaloader types.  Coerce them here so json.dumps()
    in __main__ never crashes and silently discards all collected records.
    """
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
        # Anything else (custom Instaloader types, sets, …) → string fallback
        return str(value)

    return _coerce(raw)


def _iter_hashtag_posts(loader, tag, limit=50):
    """Safely extract Post objects from Instagram hashtag feed, supporting modern layout formats (medias, clips, fill_items) and pagination."""
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
    # Modern Instagram hashtags place posts in 'top' sections ('recent' tab was deprecated by Instagram)
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


def collect(data):
    started = time.monotonic()
    import instaloader as il
    from instaloader import exceptions as ex
    class StopOn429(il.RateController):
        def handle_429(self, query_type):
            raise ex.TooManyRequestsException("rate_limited")
    query, policy = data.get('query',{'dimension':'keywords','term':''}), data.get('policy',{'timeout_seconds':60,'items_per_query':10})
    timeout_budget = float(policy.get("timeout_seconds", 60))
    safety_buffer = min(5.0, timeout_budget * 0.2) if timeout_budget > 10 else 1.0

    def time_budget_approaching():
        return (time.monotonic() - started) >= (timeout_budget - safety_buffer)

    loader = il.Instaloader(download_pictures=False,download_videos=False,
        download_video_thumbnails=False,download_geotags=False,download_comments=False,
        save_metadata=False,compress_json=False,quiet=True,max_connection_attempts=1,
        request_timeout=min(policy["timeout_seconds"],20),rate_controller=StopOn429)
    records, warnings, notes = [], [], []
    method = "hashtag" if query["dimension"] == "hashtags" else "profile_search"
    max_items = int(data.get('limit')) if data.get('operation') == 'scrape' and data.get('limit') else policy["items_per_query"]
    def append(post):
        boundary=data.get('incremental',{}).get('last_item_id')
        if boundary and str(post.mediaid)==str(boundary):
            if 'incremental_boundary_reached' not in notes:
                notes.append('incremental_boundary_reached')
            return False
        if len(records) >= max_items:
            return False
        node = getattr(post, "_node", {}) if isinstance(getattr(post, "_node", None), dict) else {}
        likes = (node.get("edge_media_preview_like", {}).get("count")
                 if isinstance(node.get("edge_media_preview_like"), dict)
                 else node.get("like_count"))
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

        records.append({"id":str(post.mediaid),"shortcode":post.shortcode,"owner_id":str(post.owner_id),
            "username":post.owner_username,"caption":post.caption,
            "published_at":post.date_utc.replace(tzinfo=timezone.utc).isoformat(),
            "media":[{"type":"video" if post.is_video else "image","url":post.url}],
            "engagement":{"likes":likes,"comments":comments},
            "raw_node":_safe_raw(post),"discovery_method":method})
        return True
    try:
        access=data.get('access',{})
        session = access.get('session_file') or os.getenv('WATCHTOWER_INSTAGRAM_SESSION')
        username = access.get('username') or os.getenv('WATCHTOWER_INSTAGRAM_USERNAME')
        if session and username:
            from app.connectors.instagram.access import read_cookies
            loader.load_session(username,read_cookies(session))
        else:
            return {'error':'instagram_not_configured'}
        if data.get('operation') == 'test':
            logged_in=loader.test_login()
            return {'status':'Connected'} if logged_in else {'error':'instagram_session_expired'}
        if data.get('operation') == 'scrape':
            scrape_type = data.get('scrape_type', 'profile')
            target = str(data.get('target', '')).strip()
            limit = int(data.get('limit', 10))
            profile_info = None

            if scrape_type == 'profile':
                user = target.lstrip('@').strip()
                profile_obj = None
                try:
                    profile_obj = il.Profile.from_username(loader.context, user)
                except Exception:
                    candidates = il.TopSearchResults(loader.context, user).get_profiles()
                    for p in candidates:
                        if p.username.lower() == user.lower():
                            profile_obj = p
                            break
                    if not profile_obj:
                        cand_list = list(candidates)
                        if cand_list:
                            profile_obj = cand_list[0]

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

                    for post in islice(profile_obj.get_posts(), limit):
                        if not append(post):
                            break
                else:
                    return {'error': 'instagram_collection_error', 'notes': [f'Could not find public profile @{user}']}

            elif scrape_type == 'hashtag':
                tag = target.lstrip('#').strip()
                method = "hashtag"
                try:
                    for post in _iter_hashtag_posts(loader, tag, limit):
                        if not append(post):
                            break
                    if not records:
                        warnings.append(f'No posts found for #{tag}. The hashtag may be inactive or restricted.')
                except Exception as exc:
                    warnings.append(f'Hashtag collection error: {exc}')

            return {'profile': profile_info, 'records': records, 'warnings': warnings, 'notes': notes}
        if data.get('operation') == 'profiles':
            profiles=[]
            candidates=il.TopSearchResults(loader.context,data['search']).get_profiles()
            for profile in islice(candidates,20):
                if time_budget_approaching():
                    break
                if profile.is_private:
                    continue
                followers=profile.followers
                if followers is None and (data.get('minimum') is not None or data.get('maximum') is not None):
                    continue
                if data.get('minimum') is not None and followers<data['minimum']:
                    continue
                if data.get('maximum') is not None and followers>data['maximum']:
                    continue
                profiles.append({'username':profile.username,'display_name':profile.full_name,
                    'url':'https://www.instagram.com/'+profile.username+'/', 'biography':profile.biography,
                    'followers':followers,'following':profile.followees,'post_count':profile.mediacount,
                    'verified_account':profile.is_verified,'image':profile.profile_pic_url,
                    'follower_count_source':'instagram_profile','private':False})
            return {'profiles':profiles,'scope':'At most 20 discovered public profiles; follower filtering is local, not global search.'}
        if method == "hashtag":
            tag = query["term"].lstrip("#").strip()
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
        else:
            if query['dimension'] == 'saved_source':
                try:
                    profiles = [il.Profile.from_username(loader.context, query['term'])]
                except Exception:
                    candidates = [p for p in il.TopSearchResults(loader.context, query['term']).get_profiles() if p.username.lower() == query['term'].lower()]
                    profiles = candidates if candidates else []
            else:
                profiles = il.TopSearchResults(loader.context, query["term"].lstrip("@")).get_profiles()

            # Profile search discovers public accounts; it is not full-text caption search.
            for profile in islice(profiles,3):
                if time_budget_approaching():
                    if 'instagram_time_budget_reached' not in notes:
                        notes.append('instagram_time_budget_reached')
                    break
                if profile.is_private:
                    warnings.append("instagram_private_profile_skipped")
                    continue
                remaining = policy["items_per_query"]-len(records)
                for post in islice(profile.get_posts(),remaining):
                    if time_budget_approaching():
                        if 'instagram_time_budget_reached' not in notes:
                            notes.append('instagram_time_budget_reached')
                        break
                    if not append(post):
                        break
                    if data.get('time_window'):
                        from app.config.time_window import TimeWindow
                        if TimeWindow.parse(data['time_window']).classify(records[-1]['published_at']) == 'STALE':
                            # Keep the boundary item for the stale audit count; stop this source.
                            break
                if len(records) >= policy["items_per_query"] or time_budget_approaching():
                    if time_budget_approaching() and 'instagram_time_budget_reached' not in notes:
                        notes.append('instagram_time_budget_reached')
                    break
    except Exception as exc:
        if isinstance(exc,ex.TooManyRequestsException):
            code="instagram_rate_limited"
        elif isinstance(exc,ex.LoginRequiredException):
            code="instagram_login_required"
        elif isinstance(exc,ex.BadCredentialsException):
            code='instagram_authentication_failed'
        elif isinstance(exc,ex.AbortDownloadException):
            code='instagram_access_control_required'
        elif isinstance(exc,ex.ConnectionException):
            code="instagram_access_or_network_error"
        else:
            code="instagram_collection_error"
        if not records:
            return {"error":code}
        warnings.append(code)
    finally:
        loader.close()
    return {"records":records,"warnings":warnings,"notes":notes}


if __name__ == "__main__":
    try:
        data=json.loads(sys.stdin.read())
        with contextlib.redirect_stdout(sys.stderr):
            result=collect(data)
        out = json.dumps(result, ensure_ascii=False).encode('utf-8')
        sys.stdout.buffer.write(out + b'\n')
    except Exception:
        sys.stdout.buffer.write(b'{"error":"instagram_worker_error"}\n')
