"""Bounded isolated Instaloader worker. No downloads or private-profile collection."""
import contextlib
from datetime import date, datetime, timezone
from itertools import islice
import json
import os
import sys


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


def collect(data):
    import instaloader as il
    from instaloader import exceptions as ex
    class StopOn429(il.RateController):
        def handle_429(self, query_type):
            raise ex.TooManyRequestsException("rate_limited")
    query, policy = data.get('query',{'dimension':'keywords','term':''}), data.get('policy',{'timeout_seconds':30,'items_per_query':10})
    loader = il.Instaloader(download_pictures=False,download_videos=False,
        download_video_thumbnails=False,download_geotags=False,download_comments=False,
        save_metadata=False,compress_json=False,quiet=True,max_connection_attempts=1,
        request_timeout=min(policy["timeout_seconds"],20),rate_controller=StopOn429)
    records, warnings, notes = [], [], []
    method = "hashtag" if query["dimension"] == "hashtags" else "profile_search"
    def append(post):
        boundary=data.get('incremental',{}).get('last_item_id')
        if boundary and str(post.mediaid)==str(boundary):
            if 'incremental_boundary_reached' not in notes:
                notes.append('incremental_boundary_reached')
            return False
        if len(records) >= policy["items_per_query"]:
            return False
        records.append({"id":str(post.mediaid),"shortcode":post.shortcode,"owner_id":str(post.owner_id),
            "username":post.owner_username,"caption":post.caption,
            "published_at":post.date_utc.replace(tzinfo=timezone.utc).isoformat(),
            "media":[{"type":"video" if post.is_video else "image","url":post.url}],
            "engagement":{"likes":post.likes,"comments":post.comments},
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
            return {'status':'Connected'} if logged_in and logged_in.casefold()==username.casefold() else {'error':'instagram_session_expired'}
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
                try:
                    hashtag = il.Hashtag.from_name(loader.context, tag)
                    hashtag_node = getattr(hashtag, "_node", {})
                    recent = hashtag_node.get("recent")
                    if isinstance(recent, dict):
                        if "more_available" not in recent:
                            recent["more_available"] = False
                        if "next_max_id" not in recent:
                            recent["next_max_id"] = None
                    for post in islice(hashtag.get_posts(), limit):
                        if not append(post):
                            break
                except KeyError as exc:
                    if str(exc) == "'more_available'":
                        if not records:
                            return {"error": "instagram_hashtag_api_incompatible", "notes": ["Instagram hashtag response is incompatible with current Instaloader. Use profile queries instead."]}
                        warnings.append("instagram_hashtag_api_incompatible")
                    else:
                        raise

            return {'profile': profile_info, 'records': records, 'warnings': warnings, 'notes': notes}
        if data.get('operation') == 'profiles':
            profiles=[]
            candidates=il.TopSearchResults(loader.context,data['search']).get_profiles()
            for profile in islice(candidates,20):
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

            hashtag = il.Hashtag.from_name(loader.context, tag)

            # Instagram can currently return the newer "sections" hashtag
            # response without the pagination field Instaloader's
            # SectionIterator expects.  Pre-patch the node as a best-effort
            # measure so the iterator may never need to fetch a "more_available"
            # field.  If the field is still missing during iteration (e.g.
            # the internal structure changed again) the KeyError is caught
            # below and reported as instagram_hashtag_api_incompatible so the
            # caller can display a meaningful message instead of a generic error.
            hashtag_node = getattr(hashtag, "_node", {})
            recent = hashtag_node.get("recent")

            if isinstance(recent, dict):
                if "more_available" not in recent:
                    recent["more_available"] = False

                if "next_max_id" not in recent:
                    recent["next_max_id"] = None

            try:
                hashtag_posts = hashtag.get_posts()

                # Instagram's hashtag API only surfaces posts from public
                # accounts — private posts never appear in hashtag feeds.
                # Calling post.owner_profile.is_private would trigger a
                # separate live HTTP request per post (lazy profile fetch)
                # with no benefit, multiplying requests and rate-limit risk.
                for post in islice(hashtag_posts, policy["items_per_query"]):
                    if not append(post):
                        break

            except KeyError as exc:
                if str(exc) == "'more_available'":
                    # The Instagram API changed its hashtag response format and
                    # Instaloader's SectionIterator cannot parse it.  Return a
                    # specific error code so the UI can show a useful message.
                    if not records:
                        return {
                            "error": "instagram_hashtag_api_incompatible",
                            "notes": [
                                "Instagram hashtag response is incompatible with "
                                "the installed Instaloader version. "
                                "Update Instaloader or use profile/saved-source queries."
                            ],
                        }
                    # Partial results already collected — surface as a warning.
                    if "instagram_hashtag_api_incompatible" not in warnings:
                        warnings.append("instagram_hashtag_api_incompatible")
                else:
                    raise
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
                if profile.is_private:
                    warnings.append("instagram_private_profile_skipped")
                    continue
                remaining = policy["items_per_query"]-len(records)
                for post in islice(profile.get_posts(),remaining):
                    if not append(post):
                        break
                    if data.get('time_window'):
                        from app.config.time_window import TimeWindow
                        if TimeWindow.parse(data['time_window']).classify(records[-1]['published_at']) == 'STALE':
                            # Keep the boundary item for the stale audit count; stop this source.
                            break
                if len(records) >= policy["items_per_query"]:
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
