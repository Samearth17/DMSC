import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from app.api.controller import Controller
from app.api.server import handler
from app.config.profile import Profile,Policy
from app.discovery.queries import Query
from app.connectors.news.connector import FeedRedirect
from app.connectors.instagram.connector import InstagramConnector
from app.connectors.web.http import public_addresses,FetchError
from app.connectors.web.connector import WebConnector
from app.correlation.groups import group_reports
from test_watchtower import Fake,record


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.controller=Controller(str(Path(self.tmp.name)/'test.db'),{'news':Fake()})
        self.token='test-session-token'
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.controller,self.token))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.controller.stop.set()
        self.tmp.cleanup()
    def request(self,path,data=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,
            headers=headers or {'X-Watchtower-Token':self.token,'Content-Type':'application/json'})
        return urllib.request.urlopen(req,timeout=5)

    def test_profile_run_report_export_evidence_flow(self):
        p=Profile.parse({'name':'UI test','platforms':{'news':True},'dimensions':{'keywords':{'enabled':True,'values':['flood']}}}).snapshot()
        with self.request('/api/profile',p) as response:
            self.assertEqual(response.status,200)
        with self.request('/api/run',{}) as response:
            self.assertEqual(response.status,202)
        for _ in range(100):
            if not self.controller.running:
                break
            time.sleep(.01)
        self.assertFalse(self.controller.running)
        with self.request('/api/runs') as response:
            rid=json.load(response)[0]['id']
        with self.request('/api/records?run_id='+rid) as response:
            items=json.load(response)
            self.assertEqual(len(items),1)
        with self.request('/api/events?run_id='+rid) as response:
            self.assertEqual(len(json.load(response)),1)
        with self.request('/api/evidence?run_id='+rid+'&event_id='+items[0]['id']) as response:
            self.assertEqual(json.load(response)[0]['raw']['id'],'item-1')
        with self.request('/api/export?format=csv&run_id='+rid) as response:
            self.assertIn('Flood report',response.read().decode('utf-8-sig'))
        with self.request('/api/report?run_id='+rid) as response:
            self.assertIn('candidate_groups',json.load(response))

    def test_api_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/profile',headers={'X-Test':'1'})
        self.assertEqual(ctx.exception.code,403)

    def test_api_rejects_cross_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.request('/api/profile',headers={'X-Watchtower-Token':self.token,'Origin':'https://evil.example'})
        self.assertEqual(ctx.exception.code,403)

    def test_bootstrap_and_assets_are_served(self):
        with self.request('/') as r:
            text=r.read().decode()
            self.assertIn(self.token,text)
            self.assertNotIn('__SESSION_TOKEN__',text)
        for path in ['/app.js','/style.css']:
            with self.request(path) as r:
                self.assertEqual(r.status,200)

    def test_deferred_platform_rejected(self):
        with self.assertRaises(ValueError):
            self.controller.save_profile({'platforms':{'reddit':True}})

    def test_schedule_persisted_and_no_duplicate_start(self):
        self.controller.configure_schedule({'enabled':True,'interval_minutes':5})
        recreated=Controller(self.controller.path,{'news':Fake()})
        self.assertTrue(recreated.schedule['enabled'])
        with patch.object(self.controller,'start') as start:
            due=self.controller.schedule['next_run_at']
            self.controller.tick(due)
            self.controller.tick(due)
            self.assertEqual(start.call_count,1)

    def test_invalid_schedule_rejected(self):
        for data in [{'enabled':'true','interval_minutes':10},{'enabled':True,'interval_minutes':0}]:
            with self.assertRaises(ValueError):
                self.controller.configure_schedule(data)

    def test_locale_redirect_is_same_provider_only(self):
        redirect=FeedRedirect()
        req=urllib.request.Request('https://news.google.com/rss/search?q=test')
        self.assertIsNotNone(redirect.redirect_request(req,None,302,'',{},'https://news.google.com/rss/search?q=test&hl=en-US'))
        self.assertEqual(redirect.followed,1)
        self.assertIsNone(redirect.redirect_request(req,None,302,'',{},'https://evil.example/rss/search'))

    @patch('app.connectors.web.http.socket.getaddrinfo')
    def test_crawler_rejects_private_and_mixed_dns_answers(self,get):
        for ips in [['127.0.0.1'],['93.184.216.34','10.0.0.1']]:
            get.return_value=[(2,1,6,'',(ip,443)) for ip in ips]
            with self.assertRaises(FetchError):
                public_addresses('example.org',443)

    def test_exact_duplicates_group_but_remain_unverified(self):
        event=Fake().normalize(record()).to_dict()
        groups=group_reports([{'id':'one','event':event},{'id':'two','event':event}])
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['evidence_level'],'Unverified')

    @patch('app.connectors.instagram.connector.subprocess.run')
    def test_instagram_login_block_is_not_empty_success(self,run):
        from types import SimpleNamespace
        from app.connectors.base import ConnectorError
        run.return_value=SimpleNamespace(stdout=json.dumps({'error':'instagram_login_required'}))
        with self.assertRaises(ConnectorError) as ctx:
            InstagramConnector().search(Query('"test"','keywords','test'),Policy())
        self.assertEqual(str(ctx.exception),'instagram_login_required')


if __name__=='__main__':
    unittest.main()
