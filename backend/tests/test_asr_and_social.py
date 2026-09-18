"""Tests for AI4Bharat IndicConformer ASR and hardened Meta/Instagram social connectors."""
from unittest.mock import MagicMock, patch
import unittest

from app.connectors.base import Policy, Query
from app.connectors.instagram.connector import InstagramConnector
from app.connectors.instagram.selenium_engine import SeleniumInstagramEngine
from app.connectors.meta.connector import MetaConnector
from app.normalization.models import WatchtowerEvent
from app.services.asr import (
    SUPPORTED_INDIC_LANGUAGES,
    get_asr_service,
    is_supported_indic_language,
    normalize_language_code,
)
from app.services.asr.base import (
    TranscriptionResult,
    TranscriptionSegment,
    validate_indic_language_code,
)
from app.services.asr.indic_conformer import IndicConformerASRService


class TestASRAndSocial(unittest.TestCase):
    def test_22_scheduled_indian_languages(self):
        expected_codes = {
            "as", "bn", "brx", "doi", "gu", "hi", "kn", "kok", "ks", "mai",
            "ml", "mni", "mr", "ne", "or", "pa", "sa", "sat", "sd", "ta", "te", "ur"
        }
        self.assertEqual(set(SUPPORTED_INDIC_LANGUAGES.keys()), expected_codes)
        self.assertEqual(len(SUPPORTED_INDIC_LANGUAGES), 22)

        for code in expected_codes:
            self.assertTrue(is_supported_indic_language(code))
            self.assertEqual(normalize_language_code(code), code)
            self.assertEqual(validate_indic_language_code(code), code)

        self.assertEqual(validate_indic_language_code(None), "hi")
        self.assertEqual(validate_indic_language_code("HINDI"), "hi")
        self.assertEqual(validate_indic_language_code("telugu"), "te")

        with self.assertRaises(ValueError):
            validate_indic_language_code("unsupported_xyz")

    def test_indic_conformer_capabilities(self):
        service = IndicConformerASRService()
        caps = service.get_capabilities()
        self.assertEqual(caps["provider"], "indic_conformer")
        self.assertEqual(caps["license"], "MIT")
        self.assertIn("rnnt", caps["decoders"])
        self.assertIn("ctc", caps["decoders"])
        self.assertEqual(caps["sample_rate"], 16000)
        self.assertEqual(len(caps["supported_languages"]), 22)

    def test_asr_factory_resolution(self):
        indic = get_asr_service("indic_conformer")
        self.assertIsInstance(indic, IndicConformerASRService)

        whisper = get_asr_service("whisper")
        self.assertEqual(whisper.provider_name, "whisper")

        cloud = get_asr_service("whisperflow_api", {"api_key": "test-key"})
        self.assertEqual(cloud.provider_name, "whisper")

    def test_indic_conformer_mock_transcribe(self):
        service = IndicConformerASRService()

        # Mock loading and audio normalization
        mock_model = MagicMock()
        mock_model.transcribe.return_value = "भारतीय सेना सुरक्षा ब्रीफिंग"

        with patch.object(service, "_load_model", return_value=(mock_model, "cpu")), \
             patch.object(service, "_load_and_normalize_audio") as mock_audio:
            import torch
            # Synthetic 10s audio at 16kHz
            fake_waveform = torch.zeros((1, 16000 * 10), dtype=torch.float32)
            mock_audio.return_value = (fake_waveform, 16000)

            res = service.transcribe("fake.wav", language="hi", decoder="rnnt")
            self.assertEqual(res.status, "collected")
            self.assertEqual(res.language, "hi")
            self.assertEqual(res.decoder, "rnnt")
            self.assertIn("भारतीय सेना", res.text)
            self.assertEqual(len(res.segments), 1)

    def test_meta_connector_search_and_normalize(self):
        connector = MetaConnector()
        avail, reason = connector.available()
        self.assertTrue(avail)
        self.assertEqual(connector.platform, "meta")

        # Mock RSS XML response with facebook post
        mock_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Google News</title>
                <item>
                    <title>Secunderabad Army Camp Arms Heist - facebook.com</title>
                    <link>https://news.google.com/rss/articles/TEST12345</link>
                    <guid>TEST12345</guid>
                    <pubDate>Sat, 12 Sep 2026 21:44:51 GMT</pubDate>
                    <description>Investigation into weapons stolen from 20 Madras Regiment.</description>
                    <source url="https://www.facebook.com">facebook.com</source>
                </item>
            </channel>
        </rss>"""

        with patch("urllib.request.build_opener") as mock_opener:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_xml
            mock_resp.__enter__.return_value = mock_resp
            mock_opener.return_value.open.return_value = mock_resp

            q = Query("army secunderabad", "keywords", "army secunderabad")
            batch = connector.search(q, Policy(items_per_query=5))
            self.assertEqual(len(batch.records), 1)
            rec = batch.records[0]
            self.assertNotIn("- facebook.com", rec["title"])

            event = connector.normalize(rec)
            self.assertIsInstance(event, WatchtowerEvent)
            self.assertEqual(event.platform, "meta")
            self.assertEqual(event.published_at, "2026-09-12T21:44:51+00:00")
            self.assertIn("Secunderabad Army Camp", event.content)

    def test_instagram_connector_public_discovery_fallback(self):
        connector = InstagramConnector()
        self.assertEqual(connector.platform, "instagram")

        # Mock worker returning indexed records
        mock_result = {
            "records": [{
                "id": "INSTA123",
                "shortcode": "INSTA123",
                "owner_id": "instagram",
                "username": "indianarmy",
                "caption": "Indian Army operational update from border zone",
                "url": "https://www.instagram.com/p/INSTA123/",
                "published_at": "2026-09-18T10:00:00+00:00",
                "media": [{"type": "image", "url": "https://example.org/photo.jpg"}],
                "engagement": {"likes": 500, "comments": 25},
                "discovery_method": "indexed_public_discovery"
            }],
            "warnings": [],
            "notes": ["public_indexed_mode"]
        }

        with patch.object(connector, "operation", return_value=mock_result):
            batch = connector.search(Query("Indian Army", "keywords", "Indian Army"), Policy())
            self.assertEqual(len(batch.records), 1)

            event = connector.normalize(batch.records[0])
            self.assertIsInstance(event, WatchtowerEvent)
            self.assertEqual(event.platform, "instagram")
            self.assertEqual(event.url, "https://www.instagram.com/p/INSTA123/")
            self.assertIn("Indian Army", event.content)

    def test_selenium_engine_availability(self):
        engine = SeleniumInstagramEngine()
        self.assertTrue(engine.is_available())
        self.assertEqual(engine._parse_count("4M"), 4000000)
        self.assertEqual(engine._parse_count("150K"), 150000)
        self.assertEqual(engine._parse_count("8,787"), 8787)


if __name__ == "__main__":
    unittest.main()
