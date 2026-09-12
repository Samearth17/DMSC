"""Behavioral acceptance checks; all fixture collection is explicitly synthetic."""
from datetime import datetime,timedelta,timezone
from email.utils import format_datetime
import json
from pathlib import Path
import pickle
import subprocess
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from types import SimpleNamespace

from app.api.controller import Controller
from app.api import routes
from app.config.profile import Profile,Policy
from app.config.time_window import TimeWindow
from app.connectors.youtube.connector import YouTubeConnector
from app.connectors.news.connector import NewsConnector
from app.connectors.instagram.connector import InstagramConnector
from app.connectors.instagram.access import read_cookies,import_session
from app.connectors.instagram.worker import collect
from app.auditing.engine import AuditEngine
from app.storage.repository import Repository
from app.correlation.service import persist_events,reprocess
from app.discovery.queries import generate,Query
from test_watchtower import record,profile,Fake


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'watchtower.db')
        self.repo=Repository(self.path)
        self.at=datetime(2026,9,11,12,tzinfo=timezone.utc)
        self.window=TimeWindow(None,(self.at-timedelta(hours=24)).isoformat(),self.at.isoformat(),'UTC')
    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()
    def current_profile(self):
        p=profile()
        p.time_window=self.window
        return p
    def dated(self,delta,ident):
        r=record()
        r['published']=format_datetime(self.at+timedelta(hours=delta)) if delta is not None else None
        r['id']=ident
        return r

    def test_value_library_and_selections_survive_restart(self):
        c=Controller(self.path,{'news':Fake()})
        value=self.repo.add_value('entities','Example entity')
        c.save_profile({'dimensions':{'entities':{'enabled':True,'values':[value['value']]}}})
        restarted=Controller(self.path,{'news':Fake()})
        self.assertEqual(restarted.profile.dimensions['entities'].values,['Example entity'])
        self.assertEqual(self.repo.values('entities')[0]['value'],'Example entity')

    def test_archive_deselects_without_changing_historical_snapshot(self):
        c=Controller(self.path,{'news':Fake()})
        c.save_profile(profile().snapshot())
        r=AuditEngine(self.repo,{'news':Fake()}).run(c.profile)
        value=self.repo.values('keywords')[0]
        c.archive_value('keywords',value['id'])
        self.assertEqual(self.repo.values('keywords'),[])
        self.assertEqual(c.profile.dimensions['keywords'].values,[])
        self.assertEqual(self.repo.report(r['id'])['snapshot']['dimensions']['keywords']['values'],['flood'])

    def test_case_dedup_and_restore_value(self):
        a=self.repo.add_value('hashtags','#Example')
        b=self.repo.add_value('hashtags','example')
        self.assertEqual(a['id'],b['id'])
        self.repo.archive_value('hashtags',a['id'])
        self.assertEqual(self.repo.add_value('hashtags','EXAMPLE')['id'],a['id'])

    def test_time_window_validation(self):
        for data in [{'hours':2},{'hours':True},{'hours':None},{'timezone':'Invalid/Zone'},
                     {'hours':None,'start_time':'2026-09-11T12:00','end_time':'2026-09-12T12:00'}]:
            with self.assertRaises(ValueError):TimeWindow.parse(data)
        for hours in [1,6,12,24,48,168]:
            w=TimeWindow(hours).resolve(self.at)
            self.assertEqual(datetime.fromisoformat(w.end_time)-datetime.fromisoformat(w.start_time),timedelta(hours=hours))

    def test_recent_stale_missing_and_after_window_are_preserved(self):
        records=[self.dated(-1,'new'),self.dated(-24*3650,'old'),self.dated(None,'unknown'),self.dated(1,'future')]
        r=AuditEngine(self.repo,{'news':Fake(records)}).run(self.current_profile())
        m=r['metrics']
        for key in ['within_time_window','items_stale','items_unknown_time','items_after_window','relevant_items']:
            self.assertEqual(m[key],1,key)
        self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM source_records').fetchone()[0],4)
        items=self.repo.events(r['id'])
        self.assertEqual(len(persist_events(self.repo,r['id'],items)),1)
        self.assertEqual(len(self.repo.search_records({'classification':'STALE'})),1)
        self.assertEqual(r['snapshot']['resolved_time_window'],self.window.snapshot())

    def test_disabled_connector_never_called(self):
        news,ig=Fake(),MagicMock()
        AuditEngine(self.repo,{'news':news,'instagram':ig}).run(profile())
        ig.search.assert_not_called()
        ig.available.assert_not_called()

    def test_saved_source_queries_share_budget_and_disabled_platforms_skip(self):
        p=Profile.parse({'platforms':{'news':True},'saved_sources':{'news':['https://example.org/rss']},
                         'policies':{'news':{'query_limit':1}}})
        self.assertEqual(generate(p,'news')[0].dimension,'saved_source')
        p.platforms['news']=False
        self.assertEqual(generate(p,'news'),[])

    def test_query_cap_under_thousands_of_terms(self):
        p=Profile.parse({'platforms':{'news':True},'dimensions':{k:{'enabled':True,'values':[f'{k} {i}' for i in range(1000)]} for k in ['geography','entities','keywords','hashtags','incident_types']}})
        self.assertEqual(len(generate(p,'news')),8)

    def test_youtube_stale_and_unknown_date_precision(self):
        c=YouTubeConnector()
        c.available=lambda:(True,'fixture')
        raws=[{'id':'old','title':'flood','timestamp':(self.at-timedelta(days=3650)).timestamp()},
              {'id':'new','title':'flood','timestamp':(self.at-timedelta(hours=1)).timestamp()},
              {'id':'day','title':'flood','upload_date':'20260911'}]
        from app.connectors.base import Batch
        c.search=lambda q,p:Batch(raws)
        p=self.current_profile();p.platforms={'youtube':True,**{k:False for k in p.platforms if k!='youtube'}}
        r=AuditEngine(self.repo,{'youtube':c}).run(p)
        self.assertEqual(r['metrics']['items_stale'],1)
        self.assertEqual(r['metrics']['items_unknown_time'],1)
        self.assertEqual(r['metrics']['relevant_items'],1)

    @patch('app.connectors.news.connector.urllib.request.build_opener')
    def test_news_discovery_dates_and_publication_provenance(self,opener):
        opener.return_value.open.return_value.__enter__.return_value.read.return_value=b'<rss><channel/></rss>'
        c=NewsConnector();c.time_window=self.window
        c.search(Query('"flood"','keywords','flood'),Policy())
        url=opener.return_value.open.call_args.args[0].full_url
        self.assertIn('after%3A2026-09-10',url)
        self.assertIn('before%3A2026-09-12',url)
        e=c.normalize(self.dated(-1,'a'))
        self.assertEqual(e.published_at_source,'rss_feed')
        self.assertNotEqual(e.published_at,e.collected_at)

    @patch('app.connectors.web.http.PublicHTTP.get')
    def test_configured_rss_preserves_feed_identity(self,get):
        get.return_value=(b'<rss><channel><item><guid>a</guid><title>flood</title><link>https://example.org/a</link></item></channel></rss>',{},'https://example.org/rss')
        c=NewsConnector();b=c.search(Query('https://example.org/rss','saved_source','https://example.org/rss'),Policy())
        self.assertEqual(c.normalize(b.records[0]).source_id,'https://example.org/rss')

    @patch('app.connectors.web.http.PublicHTTP.get')
    def test_saved_rss_uses_incremental_item_boundary(self,get):
        get.return_value=(b'<rss><channel><item><guid>new</guid><title>flood</title><link>https://example.org/new</link></item><item><guid>old</guid><title>flood</title><link>https://example.org/old</link></item></channel></rss>',{},'https://example.org/rss')
        c=NewsConnector();c.incremental_state={'last_item_id':'old'}
        batch=c.search(Query('https://example.org/rss','saved_source','https://example.org/rss'),Policy())
        self.assertEqual([x['id'] for x in batch.records],['new'])
        self.assertEqual(batch.notes,['incremental_boundary_reached'])

    def test_instagram_session_is_local_and_redacted(self):
        path=Path(self.tmp.name)/'session'
        path.write_bytes(pickle.dumps({'sessionid':'TEST-SECRET','csrftoken':'TEST-CSRF'}))
        c=Controller(self.path,{'instagram':InstagramConnector()})
        import base64
        result=c.instagram_configure({'username':'example','session_data':base64.b64encode(path.read_bytes()).decode()})
        self.assertTrue(result['configured'])
        self.assertNotIn('TEST-SECRET',json.dumps(result))
        self.assertNotIn('session_file',json.dumps(result))
        restarted=Controller(self.path,{'instagram':InstagramConnector()})
        self.assertEqual(restarted.instagram_status()['username'],'example')

    def test_pickle_globals_rejected(self):
        path=Path(self.tmp.name)/'bad'
        path.write_bytes(pickle.dumps(Path('/tmp/example')))
        with self.assertRaises(ValueError):read_cookies(path)

    def test_instagram_not_configured_and_follower_validation(self):
        c=Controller(self.path,{'instagram':InstagramConnector()})
        with patch.object(c.connectors['instagram'],'available',return_value=(True,'ready')):
            self.assertEqual(c.instagram_operation({},'test')['error'],'instagram_not_configured')
        with self.assertRaises(ValueError):c.instagram_operation({'search':'x','minimum':10,'maximum':1},'profiles')

    @patch('app.connectors.instagram.connector.subprocess.run')
    def test_instagram_worker_errors_never_success(self,run):
        from app.connectors.base import ConnectorError
        for code in ['instagram_rate_limited','instagram_session_expired','instagram_login_required']:
            run.return_value=SimpleNamespace(stdout=json.dumps({'error':code}))
            with self.assertRaises(ConnectorError) as ctx:InstagramConnector().search(Query('x','keywords','x'),Policy())
            self.assertEqual(ctx.exception.rate_limited,code=='instagram_rate_limited')

    def test_instagram_profile_metadata_and_follower_filter(self):
        import instaloader
        def fake_profile(name,followers,private=False):
            return SimpleNamespace(username=name,followers=followers,is_private=private,full_name='Example',biography='Public bio',followees=4,mediacount=10,is_verified=False,profile_pic_url='https://example.org/image')
        path=Path(self.tmp.name)/'cookies.json';path.write_text(json.dumps({'sessionid':'test','csrftoken':'test'}))
        with patch.object(instaloader,'Instaloader') as loader,patch.object(instaloader,'TopSearchResults') as results:
            results.return_value.get_profiles.return_value=iter([fake_profile('small',1),fake_profile('match',200),fake_profile('private',200,True),fake_profile('large',99999)])
            data=collect({'access':{'username':'example','session_file':str(path)},'operation':'profiles','search':'example','minimum':100,'maximum':1000})
            self.assertEqual([p['username'] for p in data['profiles']],['match'])
            self.assertEqual(data['profiles'][0]['followers'],200)
            loader.return_value.close.assert_called_once()

    def test_correlation_copies_never_verified_and_historical_analysis_unchanged(self):
        records=[self.dated(-1,'a'),self.dated(-1,'b')]
        records[1]['source_url']='https://second.example'
        r=AuditEngine(self.repo,{'news':Fake(records)}).run(self.current_profile())
        events=persist_events(self.repo,r['id'],self.repo.events(r['id']))
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['evidence_level'],'Unverified')
        self.assertEqual(events[0]['distinct_text_count'],1)
        before=self.repo.report(r['id'])
        revision=reprocess(self.repo,r['id'],profile(dimensions={'keywords':{'enabled':True,'values':['unmatched']}}))
        self.assertEqual(revision['collection_requests'],0)
        self.assertEqual(revision['events'],[])
        self.assertEqual(self.repo.report(r['id']),before)
        self.assertTrue(self.repo.events(r['id'])[0]['analysis']['relevant'])

    def test_query_attempts_and_raw_export(self):
        r=AuditEngine(self.repo,{'news':Fake([self.dated(-1,'a')])}).run(self.current_profile())
        self.assertEqual(self.repo.db.execute('SELECT COUNT(*) FROM queries').fetchone()[0],1)
        self.assertEqual(self.repo.db.execute('SELECT status FROM collection_attempts').fetchone()[0],'complete')
        self.assertEqual(routes.export_data(self.repo,r['id'],'raw')[0]['payload']['id'],'a')
        self.assertTrue(self.repo.source_states()[0]['last_successful_run'])

    def test_query_cache_does_not_cross_time_window_sizes(self):
        connector=Fake([self.dated(-.5,'a')])
        one=profile();one.time_window=TimeWindow(1)
        day=profile();day.time_window=TimeWindow(24)
        AuditEngine(self.repo,{'news':connector}).run(one)
        AuditEngine(self.repo,{'news':connector}).run(day)
        self.assertEqual(connector.calls,2)

    def test_startup_reconciles_interrupted_audit(self):
        p=self.current_profile()
        rid=self.repo.begin(p)
        report={'id':rid,'status':'running','started_at':self.at.isoformat(),'snapshot':p.snapshot(),
                'metrics':{},'platforms':{'news':{'status':'running','metrics':{},'queries':[{'text':'x','status':'running','errors':[]}],'sources':{},'errors':[]}}}
        self.repo.save_report(report)
        with self.repo.db:
            self.repo.db.execute('INSERT INTO collection_attempts VALUES (?,?,?,?,?,?,?,?)',('attempt',rid,'news','x',self.at.isoformat(),None,'running','{}'))
        self.assertEqual(self.repo.reconcile_incomplete_runs(),1)
        saved=self.repo.report(rid)
        self.assertEqual(saved['status'],'failed')
        self.assertEqual(saved['platforms']['news']['status'],'failed')
        self.assertEqual(saved['platforms']['news']['queries'][0]['errors'],['application_interrupted'])
        self.assertEqual(self.repo.db.execute('SELECT status FROM collection_attempts').fetchone()[0],'failed')

    def test_search_uses_historical_normalized_versions(self):
        p=self.current_profile();p.policies['news'].cache_ttl_seconds=0
        first=AuditEngine(self.repo,{'news':Fake([self.dated(-1,'a')])}).run(p)
        updated=self.dated(-1,'a');updated['title']='New unrelated content'
        AuditEngine(self.repo,{'news':Fake([updated])}).run(p)
        results=self.repo.search_records({'run_id':first['id'],'q':'flood','platform':'news'})
        self.assertEqual(len(results),1)
        self.assertIn('Flood',results[0]['event']['content'])


if __name__=='__main__':unittest.main()
