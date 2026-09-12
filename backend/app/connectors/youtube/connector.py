import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from app.connectors.base import Batch, ConnectorError, SourceConnector
from app.normalization.models import WatchtowerEvent


class YouTubeConnector(SourceConnector):
    platform = "youtube"
    version = '3-dated-metadata'

    def available(self):
        return (True, "ready") if importlib.util.find_spec("yt_dlp") else (False, "yt_dlp_not_installed")

    def search(self, query, policy):
        window = getattr(self, 'time_window', None)
        text = query.text
        if window:
            from datetime import timedelta
            from app.config.time_window import instant
            tomorrow=(instant(window.end_time)+timedelta(days=1)).date().isoformat()
            text += f' after:{window.start_time[:10]} before:{tomorrow}'
        command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-flat-playlist",
                   "--skip-download", "--dump-single-json", "--quiet",
                   "--ignore-no-formats-error", "--extractor-args", "youtube:skip=dash,hls",
                   "--socket-timeout", str(policy.timeout_seconds), "--retries", "0",
                   "--extractor-retries", "0"]
        if window:
            command.extend(["--dateafter", window.start_time[:10].replace('-', ''),
                            "--datebefore", window.end_time[:10].replace('-', '')])
        command.extend(["--", f"ytsearch{policy.items_per_query}:{text}"])
        # Optional use of the OS certificate store. TLS verification stays enabled.
        if os.getenv("WATCHTOWER_YOUTUBE_SYSTEM_CERTS") == "1":
            command[3:3] = ["--compat-options", "no-certifi"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                    timeout=policy.timeout_seconds, check=False)
            # Some Python installations ship a broken certifi PEM. Fall back to the
            # operating-system certificate store; verification remains enabled.
            if result.returncode and os.getenv("WATCHTOWER_YOUTUBE_SYSTEM_CERTS") != "1" and (
                    "PEM lib" in result.stderr or "CERTIFICATE_VERIFY_FAILED" in result.stderr):
                retry = command[:]
                retry[3:3] = ["--compat-options", "no-certifi"]
                result = subprocess.run(retry, capture_output=True, text=True, encoding="utf-8",
                                        timeout=policy.timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            raise ConnectorError("youtube_timeout", retryable=True) from None
        if result.returncode:
            limited = "429" in result.stderr or "too many requests" in result.stderr.lower()
            code = "youtube_rate_limited" if limited else "youtube_tls_error" if "SSLError" in result.stderr or "CERTIFICATE_VERIFY_FAILED" in result.stderr else "youtube_extraction_failed"
            raise ConnectorError(code,
                                 rate_limited=limited, retryable=False)
        try:
            payload = json.loads(result.stdout)
            entries = payload["entries"]
            if not isinstance(entries, list):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise ConnectorError("youtube_invalid_response") from None
        warnings = ["youtube_missing_entries"] if any(e is None for e in entries) else []
        notes = []
        if "WARNING:" in result.stderr:
            if 'No supported JavaScript runtime' in result.stderr:
                notes.append('youtube_javascript_runtime_unavailable_metadata_only')
            else:
                warnings.append("youtube_extractor_warning")
        return Batch([e for e in entries[:policy.items_per_query] if e is not None],
                     requests=None, warnings=warnings, raw_response=result.stdout,notes=notes)

    def normalize(self, record):
        ident = str(record.get("id") or "")
        source = record.get("channel_id") or record.get("uploader_id") or record.get("channel_url")
        published = None
        if isinstance(record.get("timestamp"), (int, float)):
            try:
                published = datetime.fromtimestamp(record["timestamp"], timezone.utc).isoformat()
            except (ValueError, OverflowError, OSError):
                pass
        date_only = False
        if published is None and record.get('upload_date'):
            try:
                published = datetime.strptime(record['upload_date'],'%Y%m%d').replace(tzinfo=timezone.utc).isoformat()
                date_only = True
            except (ValueError,TypeError):
                pass
        # If channel identity is absent, audit an individual video, never invent an account.
        return WatchtowerEvent(
            platform=self.platform, source_type="channel" if source else "video",
            source_id=str(source or ident), item_id=ident,
            url=f"https://www.youtube.com/watch?v={ident}",
            account=record.get("channel") or record.get("uploader"),
            content="\n".join(str(record.get(k) or "") for k in ("title", "description")).strip(),
            engagement={"views": record.get("view_count")},
            published_at=published,
            published_at_source='youtube_upload_date' if date_only else 'youtube_timestamp' if published else None,
            time_confidence=0.5 if date_only else 1.0 if published else None,
            title=record.get('title'), author=record.get('uploader'),
            media=[{"type": "video", "id": ident, 'thumbnails':record.get('thumbnails',[])}],
            metadata={"title": record.get("title"), "duration": record.get("duration"),
                      "time_precision":'day' if date_only else 'second',
                      "collection_scope": "video_metadata", "transcript_status": "not_collected"}).validate()
