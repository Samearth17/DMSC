from contextlib import contextmanager
import threading
import time
import json
from pathlib import Path
from app.config.profile import Profile
from app.auditing.engine import AuditEngine
from app.storage.repository import Repository
from app.correlation.groups import group_reports


class Controller:
    def __init__(self,path,connectors):
        self.path,self.connectors=path,connectors
        self.lock=threading.RLock()
        self.running=False
        self.last_error=None
        self.run_id=None
        self.stop=threading.Event()
        with self.repository() as repo:
            repo.reconcile_incomplete_runs()
            self.profile=Profile.parse(repo.setting('active_profile',{'name':'My monitoring profile','platforms':{'news':True}}))
            self.schedule=repo.setting('schedule',{'enabled':False,'interval_minutes':60,'next_run_at':None})
            for category, dimension in self.profile.dimensions.items():
                for value in dimension.values:
                    repo.add_value(category,value)
            instagram=self.connectors.get('instagram')
            if instagram:
                instagram.access=repo.setting('instagram_access',{})
                instagram.cache_scope=instagram.access.get('session_file')
        self.scheduler=threading.Thread(target=self.schedule_loop,daemon=True)

    @contextmanager
    def repository(self):
        repo=Repository(self.path)
        try:
            yield repo
        finally:
            repo.close()

    def save_profile(self,data):
        p=Profile.parse(data)
        if p.platforms['x'] or p.platforms['reddit']:
            raise ValueError('X and Reddit are deferred in this release')
        if not any(p.active_terms().values()):
            for dim in p.dimensions.values():
                if dim.values:
                    dim.enabled = True
        with self.lock:
            with self.repository() as repo:
                repo.set_setting('active_profile',p.snapshot())
                for category, dimension in p.dimensions.items():
                    for value in dimension.values:
                        repo.add_value(category,value)
            self.profile=p
        return p.snapshot()

    def start(self):
        with self.lock:
            if self.running:
                raise ValueError('An audit is already running')
            p=Profile.parse(self.profile.snapshot())
            if not any(p.active_terms().values()):
                for dim in p.dimensions.values():
                    if dim.values:
                        dim.enabled = True
            if not any(p.platforms.values()) or not (any(p.active_terms().values()) or any(p.saved_sources.values()) or any(p.platform_queries.values())):
                raise ValueError('Enable a platform and add values to at least one enabled category')
            if p.platforms['x'] or p.platforms['reddit']:
                raise ValueError('X and Reddit are deferred; disable them')
            self.running=True
            self.last_error=None
            with self.repository() as repo:
                self.run_id=repo.begin(p)
            worker=threading.Thread(target=self.run,args=(p,self.run_id),daemon=True)
            worker.start()
        return {'status':'started','run_id':self.run_id}

    def run(self,p,run_id=None):
        try:
            with self.repository() as repo:
                report=AuditEngine(repo,self.connectors).run(p,run_id=run_id)
                items=repo.events(report['id'])
                report['candidate_groups']=group_reports([i for i in items if i['analysis']['relevant']])
                from app.correlation.service import persist_events
                report['event_count']=len(persist_events(repo,report['id'],items))
                report['processing']={'text':'lexical-v2','transcripts':'not_collected',
                                      'vision':'not_implemented','geopolitical_analysis':'not_implemented'}
                repo.save_report(report)
                # Local alerts are review queue entries; they make no factual claims.
                with repo.db:
                    for item in items:
                        if item['analysis']['relevant'] and item['analysis'].get('relevance_score',0)>=.75:
                            from app.normalization.models import now
                            alert_id=report['id']+':'+item['id']
                            repo.db.execute('INSERT OR IGNORE INTO alerts VALUES (?,?,?,?)',
                                (alert_id,item['id'],json.dumps({'run_id':report['id'],'type':'relevance_match','evidence_level':'Unverified'}),now()))
        except Exception:
            with self.lock:
                self.last_error='Audit stopped after an internal error; inspect the last saved report.'
        finally:
            with self.lock:
                self.running=False

    def archive_value(self,category,ident):
        with self.lock:
            with self.repository() as repo:
                value=repo.archive_value(category,ident)
                self.profile.dimensions[category].values=[v for v in self.profile.dimensions[category].values if v!=value]
                repo.set_setting('active_profile',self.profile.snapshot())
        return {'archived':True}

    def _find_local_session(self):
        root = Path(__file__).resolve().parents[3]
        search_dirs = [
            Path('.'),
            Path(self.path).parent,
            root,
            Path(self.path).parent / 'sessions',
            Path.home() / '.config' / 'instaloader',
        ]
        for d in search_dirs:
            if not d.exists():
                continue
            for pattern in ('session-*.json', 'session.json', 'session-*'):
                for p in d.glob(pattern):
                    if p.is_file() and p.stat().st_size > 0:
                        return p
        return None

    def instagram_status(self):
        import re
        with self.repository() as repo:
            config=repo.setting('instagram_access',{})
            last=repo.setting('instagram_status',{})
        found = self._find_local_session()
        detected_user = ''
        if found:
            m = re.search(r'session-([A-Za-z0-9_.]+)', found.stem)
            detected_user = m.group(1) if m else ''
        return {'username':config.get('username',''),'configured':bool(config),
                'status':last.get('status','Not tested' if config else 'Not configured'),
                'error':last.get('error'),'tested_at':last.get('tested_at'),
                'has_local_file':bool(found),
                'local_filename':found.name if found else '',
                'detected_username':detected_user}

    def instagram_configure(self,data):
        import re
        from app.connectors.instagram.access import import_session_data, save_session_cookies, read_cookies
        with self.lock:
            if self.running:
                raise ValueError('Wait for the current audit before changing platform access')
            sessions_dir = Path(self.path).parent/'sessions'
            if data.get('sessionid') and data.get('csrftoken'):
                cookies = {'sessionid': data['sessionid'].strip(), 'csrftoken': data['csrftoken'].strip()}
                if data.get('ds_user_id'):
                    cookies['ds_user_id'] = data['ds_user_id'].strip()
                config = save_session_cookies(sessions_dir, data.get('username','').strip(), cookies)
            elif data.get('use_local_file'):
                found = self._find_local_session()
                if not found:
                    raise ValueError('No local session file (e.g. session-<username>.json or session.json) found')
                cookies = read_cookies(found)
                m = re.search(r'session-([A-Za-z0-9_.]+)', found.stem)
                detected_user = m.group(1) if m else ''
                username = data.get('username') or detected_user or 'instagram_user'
                config = save_session_cookies(sessions_dir, username, cookies)
            else:
                config=import_session_data(sessions_dir,data.get('username'),data.get('session_data'))
            with self.repository() as repo:
                repo.set_setting('instagram_access',config)
                repo.set_setting('instagram_status',{})
            connector=self.connectors.get('instagram')
            if connector:
                connector.access=config
                connector.cache_scope=config['session_file']
        return self.instagram_status()

    def instagram_scrape(self, data):
        scrape_type = data.get('type', 'profile')
        target = str(data.get('target', '')).strip()
        limit = min(max(int(data.get('limit', 10)), 1), 50)
        if not target:
            raise ValueError('Enter a username or hashtag to scrape')
        with self.lock:
            if self.running:
                raise ValueError('Wait for the audit before requesting Instagram scraping')
            connector = self.connectors.get('instagram')
            if not connector or not connector.available()[0]:
                return {'error': 'instaloader_not_installed'}
            if not connector.access:
                return {'error': 'instagram_not_configured'}
            payload = {
                'operation': 'scrape',
                'scrape_type': scrape_type,
                'target': target,
                'limit': limit
            }
            for k in ('hours', 'since', 'until'):
                if data.get(k) is not None:
                    payload[k] = data[k]
            return connector.operation(payload, timeout=90)

    def instagram_operation(self,data,operation):
        from app.normalization.models import now
        if operation=='profiles':
            term=data.get('search','')
            if not isinstance(term,str) or not term.strip() or len(term)>200:
                raise ValueError('Enter a profile search term of up to 200 characters')
            for key in ('minimum','maximum'):
                if data.get(key) is not None and (type(data[key]) is not int or data[key]<0):
                    raise ValueError('Follower bounds must be non-negative integers')
            if data.get('minimum') is not None and data.get('maximum') is not None and data['minimum']>data['maximum']:
                raise ValueError('Minimum followers must not exceed maximum')
        with self.lock:
            if self.running:
                raise ValueError('Wait for the audit before requesting Instagram searches')
            connector=self.connectors.get('instagram')
            if not connector or not connector.available()[0]:
                result={'error':'instaloader_not_installed'}
            elif not connector.access:
                result={'error':'instagram_not_configured'}
            else:
                result=connector.operation({**data,'operation':operation})
            if operation=='test':
                result['tested_at']=now()
                result['status']=result.get('status','Unavailable')
                with self.repository() as repo:
                    repo.set_setting('instagram_status',result)
        return result

    def configure_schedule(self,data):
        if not isinstance(data,dict) or set(data)-{'enabled','interval_minutes'}:
            raise ValueError('Invalid schedule fields')
        enabled,interval=data.get('enabled'),data.get('interval_minutes')
        if type(enabled) is not bool or type(interval) is not int or not 5<=interval<=10080:
            raise ValueError('Choose an interval between 5 and 10080 minutes')
        with self.lock:
            self.schedule={'enabled':enabled,'interval_minutes':interval,'next_run_at':time.time()+interval*60 if enabled else None}
            with self.repository() as repo:
                repo.set_setting('schedule',self.schedule)
            return dict(self.schedule)

    def tick(self,timestamp=None):
        timestamp=time.time() if timestamp is None else timestamp
        with self.lock:
            if not self.schedule['enabled'] or self.running or timestamp < (self.schedule.get('next_run_at') or 0):
                return
            self.schedule['next_run_at']=timestamp+self.schedule['interval_minutes']*60
            with self.repository() as repo:
                repo.set_setting('schedule',self.schedule)
            try:
                self.start()
            except ValueError as exc:
                self.last_error=str(exc)

    def schedule_loop(self):
        while not self.stop.wait(2):
            self.tick()

    def status(self):
        with self.lock:
            return {'running':self.running,'run_id':self.run_id,'last_error':self.last_error,'schedule':dict(self.schedule),
                    'capabilities':{p:{'installed':c.available()[0],'note':c.available()[1],
                                      'live_access':'determined_by_audit'} for p,c in self.connectors.items()},
                    'deferred':['x','reddit']}

    def transcription_status(self):
        from app.intelligence.transcription import get_transcription_status
        with self.repository() as repo:
            cfg = repo.setting('transcription_config', {})
        return get_transcription_status(cfg)

    def transcription_configure(self, data):
        if not isinstance(data, dict):
            raise ValueError('Configuration must be a dictionary')
        from app.intelligence.transcription import get_transcription_status
        with self.repository() as repo:
            cfg = repo.setting('transcription_config', {})
            cfg.update(data)
            repo.set_setting('transcription_config', cfg)
        return get_transcription_status(cfg)

    def transcribe_record(self, data):
        url = data.get('url')
        event_id = data.get('event_id')
        with self.repository() as repo:
            cfg = repo.setting('transcription_config', {})
            if event_id:
                row = repo.db.execute("SELECT normalized FROM events WHERE id=?", (event_id,)).fetchone()
                if not row:
                    raise ValueError(f"Event {event_id} not found")
                event_data = json.loads(row[0])
                target_url = url or event_data.get('url')
                if not target_url:
                    raise ValueError("Record has no media URL to transcribe")
                from app.intelligence.transcription import transcribe_audio
                res = transcribe_audio(target_url, config=cfg)
                if res.get('status') == 'collected' and res.get('text'):
                    event_data.setdefault('metadata', {})
                    event_data['metadata']['transcript_text'] = res['text']
                    event_data['metadata']['transcript_status'] = 'collected'
                    normalized_str = json.dumps(event_data, ensure_ascii=False)
                    repo.db.execute("UPDATE events SET normalized=? WHERE id=?", (normalized_str, event_id))
                    from app.normalization.models import WatchtowerEvent
                    from app.intelligence.rules import analyze
                    wevent = WatchtowerEvent(**{k: v for k, v in event_data.items() if k in WatchtowerEvent.__dataclass_fields__})
                    analysis = analyze(wevent, self.profile)
                    repo.db.execute("UPDATE analysis_results SET analysis=? WHERE event_id=?", (json.dumps(analysis), event_id))
                    return {'status': 'collected', 'text': res['text'], 'analysis': analysis, 'provider': res.get('provider')}
                return res
            elif url:
                save_event = bool(data.get('save') or data.get('save_to_watchtower'))
                from app.intelligence.transcription import transcribe_audio, fetch_single_video_metadata
                res = transcribe_audio(url, config=cfg)
                if save_event:
                    import uuid
                    from datetime import datetime, timezone
                    from app.normalization.models import WatchtowerEvent
                    from app.intelligence.rules import analyze

                    meta = fetch_single_video_metadata(url) or {}
                    ident = str(meta.get("id") or abs(hash(url)) % 100000000)
                    extractor = (meta.get("extractor") or "").lower()
                    platform = "youtube" if "youtube" in extractor or "youtu" in url else "instagram" if "instagram" in extractor or "instagram.com" in url else "video"

                    published = None
                    if isinstance(meta.get("timestamp"), (int, float)):
                        try:
                            published = datetime.fromtimestamp(meta["timestamp"], timezone.utc).isoformat()
                        except Exception:
                            pass
                    elif meta.get("upload_date"):
                        try:
                            published = datetime.strptime(meta["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc).isoformat()
                        except Exception:
                            pass

                    transcript_text = res.get('text') if res.get('status') == 'collected' else None
                    title = meta.get("title") or "Targeted Video Analysis"
                    desc = meta.get("description") or ""

                    event = WatchtowerEvent(
                        platform=platform,
                        source_type="video",
                        source_id=str(meta.get("uploader_id") or meta.get("channel_id") or ident),
                        item_id=ident,
                        url=url,
                        account=meta.get("uploader") or meta.get("channel") or meta.get("creator"),
                        content=f"{title}\n{desc}".strip(),
                        engagement={"views": meta.get("view_count"), "likes": meta.get("like_count")},
                        published_at=published,
                        title=title,
                        author=meta.get("uploader") or meta.get("channel"),
                        media=[{"type": "video", "id": ident, "thumbnails": meta.get("thumbnails", [])}],
                        metadata={
                            "title": title,
                            "duration": meta.get("duration"),
                            "collection_scope": "targeted_single_video",
                            "transcript_status": "collected" if transcript_text else res.get('status', 'not_collected'),
                            "transcript_text": transcript_text
                        }
                    ).validate()

                    analysis = analyze(event, self.profile)
                    latest_run = repo.db.execute("SELECT id FROM audit_runs ORDER BY started_at DESC LIMIT 1").fetchone()
                    run_id = latest_run[0] if latest_run else repo.begin(self.profile)
                    rid, _ = repo.store_raw(run_id, platform, f"direct:{url}", meta)
                    eid = repo.store_event(run_id, rid, event, analysis)

                    return {
                        'status': res.get('status', 'collected'),
                        'text': transcript_text,
                        'provider': res.get('provider'),
                        'event_id': eid,
                        'event': event.to_dict(),
                        'analysis': analysis
                    }
                return res
            else:
                raise ValueError("Provide event_id or url to transcribe")

