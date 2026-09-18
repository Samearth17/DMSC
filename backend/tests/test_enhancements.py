import time
import json
import unittest
from unittest.mock import patch, MagicMock
from app.intelligence.boolean import eval_boolean_match, is_boolean_query, format_search_query
from app.intelligence.rules import analyze
from app.config.profile import Profile, Policy
from app.normalization.models import WatchtowerEvent
from app.auditing.engine import AuditEngine
from app.storage.repository import Repository
from app.connectors.base import SourceConnector, Batch

class EnhancementsTests(unittest.TestCase):
    def test_complex_multilingual_boolean_matching(self):
        query = '("Ooty" OR "ऊटी" OR "உட்டி") AND ("Indian Army" OR "भारतीय सेना") -filter:retweets'
        
        # Matches Ooty + Indian Army
        text1 = "Heavy snowfall in Ooty as Indian Army assists relief operations."
        self.assertTrue(eval_boolean_match(query, text1))
        
        # Matches Hindi terms: ऊटी + भारतीय सेना
        text2 = "ऊटी में भारतीय सेना ने मोर्चा संभाला।"
        self.assertTrue(eval_boolean_match(query, text2))
        
        # Matches Tamil term: உட்டி + Indian Army
        text3 = "உட்டி பகுதியில் Indian Army patrolling."
        self.assertTrue(eval_boolean_match(query, text3))
        
        # Missing second clause (no Indian Army / भारतीय सेना)
        text4 = "Beautiful weather in Ooty today."
        self.assertFalse(eval_boolean_match(query, text4))
        
        # Contains excluded term: filter:retweets
        text5 = "Ooty updates with Indian Army filter:retweets"
        self.assertFalse(eval_boolean_match(query, text5))
        text5_rt = "RT @mod_india: Ooty updates with Indian Army"
        self.assertFalse(eval_boolean_match(query, text5_rt))

    def test_multi_term_or_search(self):
        query = "a or b or c or d"
        self.assertTrue(eval_boolean_match(query, "this contains c and other stuff"))
        self.assertTrue(eval_boolean_match(query, "apple b banana"))
        self.assertFalse(eval_boolean_match(query, "xyz nothing here"))

    def test_phrase_search_in_quotes(self):
        query = '"United Nations" AND "peace keeping"'
        self.assertTrue(eval_boolean_match(query, "The United Nations announced new peace keeping missions."))
        self.assertFalse(eval_boolean_match(query, "United states and Nations in peace."))

    def test_transcript_relevance_analysis(self):
        profile = Profile.parse({
            'name': 'Transcript test',
            'platforms': {'youtube': True},
            'dimensions': {'keywords': {'enabled': True, 'values': ['rescue operation']}}
        })
        # Video title and content do NOT contain 'rescue operation', but transcript does!
        event = WatchtowerEvent(
            platform='youtube', source_id='yt-channel-1', source_type='channel',
            item_id='v123', url='https://youtube.com/watch?v=v123', published_at='2026-09-12T10:00:00Z',
            account='NewsChannel', title='Breaking news broadcast today',
            content='Watch today video broadcast covering local events.',
            metadata={'transcript_text': 'Spoken dialogue: The rescue operation has commenced in the affected district.'}
        )
        analysis = analyze(event, profile)
        self.assertTrue(analysis['relevant'])
        self.assertIn('rescue operation', analysis['matches']['keywords'])

    def test_default_platform_policy_values(self):
        profile = Profile.parse({
            'name': 'Policy defaults test',
            'platforms': {'instagram': True, 'web': True}
        })
        self.assertEqual(profile.policies['instagram'].timeout_seconds, 60)
        self.assertEqual(profile.policies['web'].pages_per_query, 5)

    def test_parallel_platform_execution(self):
        class DelayedConnector(SourceConnector):
            def __init__(self, platform):
                super().__init__()
                self.platform = platform
            def available(self):
                return True, ""
            def search(self, query, policy):
                time.sleep(0.25)
                return Batch(records=[], raw_response={})
            def normalize(self, raw):
                pass

        profile = Profile.parse({
            'name': 'Parallel test',
            'platforms': {'youtube': True, 'instagram': True},
            'dimensions': {'keywords': {'enabled': True, 'values': ['test']}}
        })
        repo = MagicMock()
        repo.begin.return_value = 'test-run'
        repo.cache_get.return_value = None
        repo.incremental_state.return_value = None
        
        connectors = {
            'youtube': DelayedConnector('youtube'),
            'instagram': DelayedConnector('instagram')
        }
        engine = AuditEngine(repo, connectors)
        
        t0 = time.time()
        report = engine.run(profile)
        elapsed = time.time() - t0
        
        # Both delayed connectors took 0.25s. If executed sequentially, total would be >= 0.5s.
        # In parallel, total should be under 0.45s.
        self.assertLess(elapsed, 0.45)
        self.assertEqual(report['status'], 'complete')

    def test_instagram_worker_returns_partial_on_time_budget(self):
        from app.connectors.instagram.worker import collect
        from unittest.mock import MagicMock
        import datetime

        # Mock instaloader
        mock_post1 = MagicMock()
        mock_post1.mediaid = 1001
        mock_post1.shortcode = 'ABC1'
        mock_post1.owner_id = 99
        mock_post1.owner_username = 'user1'
        mock_post1.caption = 'post 1'
        mock_post1.date_utc = datetime.datetime(2026, 9, 12, tzinfo=datetime.timezone.utc)
        mock_post1.is_video = False
        mock_post1.url = 'https://instagr.am/p/ABC1'
        mock_post1.likes = 10
        mock_post1.comments = 2
        mock_post1._asdict.return_value = {}
        mock_post1.owner_profile.is_private = False

        mock_post2 = MagicMock()
        mock_post2.mediaid = 1002
        mock_post2.shortcode = 'ABC2'
        mock_post2.owner_id = 99
        mock_post2.owner_username = 'user1'
        mock_post2.caption = 'post 2'
        mock_post2.date_utc = datetime.datetime(2026, 9, 12, tzinfo=datetime.timezone.utc)
        mock_post2.is_video = False
        mock_post2.url = 'https://instagr.am/p/ABC2'
        mock_post2.likes = 5
        mock_post2.comments = 1
        mock_post2._asdict.return_value = {}
        mock_post2.owner_profile.is_private = False

        with patch('instaloader.Instaloader') as MockIL, \
             patch('instaloader.Hashtag.from_name') as MockHT, \
             patch('app.connectors.instagram.access.read_cookies', return_value={}):
            mock_loader = MagicMock()
            MockIL.return_value = mock_loader
            mock_loader.load_session.return_value = None

            mock_hashtag = MagicMock()
            MockHT.return_value = mock_hashtag
            mock_hashtag.get_posts.return_value = [mock_post1, mock_post2]

            # Set a very small timeout budget so time_budget_approaching() is triggered
            # or mock time.monotonic so 2nd post triggers timeout
            monotonic_values = [0.0, 0.0, 59.0, 59.0, 59.0]
            with patch('time.monotonic', side_effect=monotonic_values):
                result = collect({
                    'query': {'dimension': 'hashtags', 'term': 'ooty'},
                    'policy': {'timeout_seconds': 60, 'items_per_query': 10},
                    'access': {'session_file': '/fake/session', 'username': 'testuser'}
                })

            self.assertIn('records', result)
            self.assertIn('instagram_time_budget_reached', result.get('notes', []))

    def test_save_session_cookies(self):
        import tempfile, json
        from pathlib import Path
        from app.connectors.instagram.access import save_session_cookies

        with tempfile.TemporaryDirectory() as tmpdir:
            res = save_session_cookies(tmpdir, 'testuser', {'sessionid': 'sess123', 'csrftoken': 'csrf456'})
            self.assertEqual(res['username'], 'testuser')
            session_file = Path(res['session_file'])
            self.assertTrue(session_file.exists())
            with open(session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(data.get('sessionid'), 'sess123')
            self.assertEqual(data.get('csrftoken'), 'csrf456')

    def test_instagram_scrape_controller(self):
        from app.api.controller import Controller
        from unittest.mock import MagicMock
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_connector = MagicMock()
            mock_connector.available.return_value = (True, 'ready')
            mock_connector.access = {'username': 'testuser'}
            mock_connector.operation.return_value = {
                'profile': {'username': 'indianarmy'},
                'records': [{'id': '123', 'shortcode': 'abc'}]
            }
            import os
            db_path = os.path.join(tmpdir, 'test.db')
            c = Controller(db_path, {'instagram': mock_connector})
            mock_connector.access = {'username': 'testuser'}

            res = c.instagram_scrape({'type': 'profile', 'target': 'indianarmy', 'limit': 5})
            self.assertIn('profile', res)
            self.assertEqual(res['profile']['username'], 'indianarmy')
            mock_connector.operation.assert_called_once_with({
                'operation': 'scrape',
                'scrape_type': 'profile',
                'target': 'indianarmy',
                'limit': 5
            }, timeout=90)

            # Test with timeline parameters (hours, since, until)
            mock_connector.operation.reset_mock()
            c.instagram_scrape({'type': 'profile', 'target': 'indianarmy', 'limit': 5, 'hours': 24, 'since': '2026-09-14T00:00:00Z'})
            mock_connector.operation.assert_called_once_with({
                'operation': 'scrape',
                'scrape_type': 'profile',
                'target': 'indianarmy',
                'limit': 5,
                'hours': 24,
                'since': '2026-09-14T00:00:00Z'
            }, timeout=90)

            # Test transcription status & configure
            status = c.transcription_status()
            self.assertTrue(status['local_installed'])
            self.assertIn('provider', status)

            # Test targeted single desired video transcribe & save
            with patch('app.intelligence.transcription.transcribe_audio') as mock_transcribe, \
                 patch('app.intelligence.transcription.fetch_single_video_metadata') as mock_meta:
                mock_transcribe.return_value = {
                    'status': 'collected',
                    'text': 'Breaking intelligence briefing on Northern border region',
                    'provider': 'whisper (base)'
                }
                mock_meta.return_value = {
                    'id': 'vid12345',
                    'extractor': 'youtube',
                    'title': 'Targeted Intelligence Video',
                    'description': 'Field report description',
                    'uploader': 'AnalystHQ',
                    'view_count': 10500,
                    'timestamp': 1726000000
                }

                saved_res = c.transcribe_record({
                    'url': 'https://www.youtube.com/watch?v=vid12345',
                    'save_to_watchtower': True
                })
                self.assertEqual(saved_res['status'], 'collected')
                self.assertEqual(saved_res['text'], 'Breaking intelligence briefing on Northern border region')
                self.assertIn('event_id', saved_res)
                self.assertIn('analysis', saved_res)

                # Verify it is now saved in SQLite events table
                with c.repository() as r:
                    row = r.db.execute("SELECT normalized FROM events WHERE id=?", (saved_res['event_id'],)).fetchone()
                    self.assertIsNotNone(row)
                    ev = json.loads(row[0])
                    self.assertEqual(ev['metadata']['collection_scope'], 'targeted_single_video')
                    self.assertEqual(ev['metadata']['transcript_text'], 'Breaking intelligence briefing on Northern border region')

    def test_dimension_resilience_and_auto_enable(self):
        from app.config.profile import Profile
        from app.discovery.queries import generate
        # Scenario: user selected keywords in Setup Profile, but enabled was left False
        raw = {
            'name': 'Test Profile',
            'dimensions': {
                'geography': {'enabled': False, 'values': []},
                'entities': {'enabled': False, 'values': []},
                'keywords': {'enabled': False, 'values': ['secunderabad', 'bollaram']},
                'hashtags': {'enabled': False, 'values': []},
                'incident_types': {'enabled': False, 'values': []}
            },
            'platforms': {'youtube': True, 'instagram': True, 'x': False, 'reddit': False, 'meta': False, 'news': False, 'web': False}
        }
        p = Profile.parse(raw)
        # queries.generate should fall back to dimensions with values rather than returning []
        queries = generate(p, 'youtube')
        self.assertGreater(len(queries), 0)
        self.assertEqual(queries[0].dimension, 'keywords')

        # Controller auto-heal test
        import tempfile
        from app.api.controller import Controller
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            db_path = os.path.join(tmpdir, 'test.db')
            c = Controller(db_path, {})
            saved = c.save_profile(raw)
            # Should have auto-healed keywords.enabled to True
            self.assertTrue(saved['dimensions']['keywords']['enabled'])
            self.assertIn('secunderabad', c.profile.active_terms()['keywords'])

    def test_related_coverage_and_clear_all_values(self):
        import tempfile
        import os
        from app.api.controller import Controller
        from app.intelligence.related import suggest_anchors, validate_seed, compare_seed

        # Test anchor suggestion
        news_text = "Heavy monsoon floods hit northern Telangana region, damaging critical road infrastructure near Hyderabad and Nizamabad highway."
        anchors = suggest_anchors(news_text)
        self.assertGreater(len(anchors), 0)

        # Test seed validation
        seed = validate_seed({
            'text': news_text,
            'url': 'https://example.com/news/123',
            'anchors': ['Telangana', 'Hyderabad', 'floods']
        })
        self.assertEqual(len(seed['anchors']), 3)

        # Test seed comparison
        matching_text = "Rescue teams deployed in Telangana following heavy floods across Hyderabad suburbs."
        comp = compare_seed(seed, matching_text, 'https://different.com/report/456')
        self.assertTrue(comp['candidate'])
        self.assertGreater(comp['score'], 0.6)

        # Test controller related preview & clear_all_values
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.db')
            c = Controller(db_path, {})
            preview = c.related_preview({
                'seed': {
                    'text': news_text,
                    'anchors': ['Telangana', 'floods']
                },
                'platforms': {'news': True, 'web': True}
            })
            self.assertIn('queries', preview)
            self.assertIn('news', preview['queries'])

            # Test clear_all_values
            c.save_profile({
                'name': 'Test',
                'dimensions': {'keywords': {'enabled': True, 'values': ['abc', 'def']}},
                'platforms': {'news': True}
            })
            self.assertEqual(len(c.profile.dimensions['keywords'].values), 2)
            c.clear_all_values()
            self.assertEqual(len(c.profile.dimensions['keywords'].values), 0)


            # Test analyze with profile.investigation
            from app.normalization.models import WatchtowerEvent
            from app.intelligence.rules import analyze
            c.profile.investigation = seed
            test_ev = WatchtowerEvent(
                platform='news', source_type='test', source_id='s-1', item_id='item-1',
                account='LocalDesk', title='Floods hit Telangana',
                content='Heavy floods submerge Telangana low-lying zones in Hyderabad.',
                url='https://example2.com/news/789'
            )
            ev_analysis = analyze(test_ev, c.profile)
            self.assertTrue(ev_analysis['relevant'])
            self.assertEqual(ev_analysis['decision'], 'related_candidate')

    def test_domain_agnostic_keyword_required_relevance(self):
        # Disaster / non-defense monitoring profile
        profile = Profile.parse({
            'name': 'Disaster Response Monitor',
            'platforms': {'news': True},
            'dimensions': {
                'geography': {'enabled': True, 'values': ['Odisha', 'Puri']},
                'keywords': {'enabled': True, 'values': ['cyclone', 'relief camps']}
            },
            'relevance': {'mode': 'keyword_required', 'exclude_terms': ['shopping', 'tourism']}
        })
        self.assertEqual(profile.relevance['mode'], 'keyword_required')

        # 1. Event with location + keyword signal -> Relevant
        ev_relevant = WatchtowerEvent(
            platform='news', source_type='feed', source_id='feed-1', item_id='item-1',
            account='DisasterDesk', title='Cyclone warning issued',
            content='Severe cyclone alert issued for Odisha coastal belt; relief camps activated.',
            url='https://example.com/cyclone-1'
        )
        res_rel = analyze(ev_relevant, profile)
        self.assertTrue(res_rel['relevant'])
        self.assertIn('keywords', res_rel['matches'])
        self.assertIn('geography', res_rel['matches'])

        # 2. Event with location only, no topic keyword -> Irrelevant (lacks topic signal)
        ev_loc_only = WatchtowerEvent(
            platform='news', source_type='feed', source_id='feed-1', item_id='item-2',
            account='CityDesk', title='Beautiful sunset in Odisha',
            content='Visitors enjoyed the evening view across beaches in Odisha today.',
            url='https://example.com/odisha-2'
        )
        res_loc = analyze(ev_loc_only, profile)
        self.assertFalse(res_loc['relevant'])
        self.assertIn('geography', res_loc['matches'])
        self.assertNotIn('keywords', res_loc['matches'])

        # 3. Backwards compatibility: 'defense_focus' parses to 'keyword_required'
        legacy_profile = Profile.parse({
            'name': 'Legacy Profile',
            'platforms': {'news': True},
            'dimensions': {
                'keywords': {'enabled': True, 'values': ['army']}
            },
            'relevance': {'mode': 'defense_focus'}
        })
        self.assertEqual(legacy_profile.relevance['mode'], 'keyword_required')


if __name__ == '__main__':
    unittest.main()


