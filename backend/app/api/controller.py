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
            if not any(p.platforms.values()) or not (any(p.active_terms().values()) or any(p.saved_sources.values())):
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

    def instagram_status(self):
        with self.repository() as repo:
            config=repo.setting('instagram_access',{})
            last=repo.setting('instagram_status',{})
        return {'username':config.get('username',''),'configured':bool(config),
                'status':last.get('status','Not tested' if config else 'Not configured'),
                'error':last.get('error'),'tested_at':last.get('tested_at')}

    def instagram_configure(self,data):
        from app.connectors.instagram.access import import_session_data
        with self.lock:
            if self.running:
                raise ValueError('Wait for the current audit before changing platform access')
            config=import_session_data(Path(self.path).parent/'sessions',data.get('username'),data.get('session_data'))
            with self.repository() as repo:
                repo.set_setting('instagram_access',config)
                repo.set_setting('instagram_status',{})
            connector=self.connectors.get('instagram')
            if connector:
                connector.access=config
                connector.cache_scope=config['session_file']
        return self.instagram_status()

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
