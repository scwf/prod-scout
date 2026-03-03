import configparser
import os
import sys
import unittest
from urllib.parse import urlparse
from unittest.mock import mock_open, patch

# Ensure project modules are importable.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from native_scout import pipeline
from native_scout.utils.content_fetcher import GenericVideoFetcher
from native_scout.stages.llm_organizer import organize_single_post
from native_scout.stages.result_writer import WriterStage
from common.source_loader import load_sources


class _DummyStage:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def start(self, *_args, **_kwargs):
        self.events.append(f"{self.name}.start")

    def join(self):
        self.events.append(f"{self.name}.join")

    def stop(self):
        self.events.append(f"{self.name}.stop")


class _DummyQueue:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def join(self):
        self.events.append(f"{self.name}.join")


class _FakeCompletions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **kwargs):
        self.owner.called = True
        self.owner.kwargs = kwargs

        class _Message:
            content = (
                '{"event":"evt","key_info":"k","detail":"d","category":"cat",'
                '"domain":"dom","quality_score":4,"quality_reason":"ok"}'
            )

        class _Choice:
            message = _Message()
            finish_reason = "stop"

        class _Response:
            choices = [_Choice()]

        return _Response()


class _FakeClient:
    def __init__(self):
        self.called = False
        self.kwargs = None

        class _Chat:
            def __init__(self, owner):
                self.completions = _FakeCompletions(owner)

        self.chat = _Chat(self)


class TestPipelineFixes(unittest.TestCase):
    def test_pipeline_shutdown_order_waits_for_queue_drain(self):
        events = []

        p = pipeline.NativePipeline.__new__(pipeline.NativePipeline)
        p.batch_timestamp = "20260207_000000"
        p.fetch_queue = _DummyQueue("fetch_queue", events)
        p.enrich_queue = _DummyQueue("enrich_queue", events)
        p.organize_queue = _DummyQueue("organize_queue", events)
        p.writer = _DummyStage("writer", events)
        p.organizer = _DummyStage("organizer", events)
        p.enricher = _DummyStage("enricher", events)
        p.fetcher = _DummyStage("fetcher", events)

        p.run({"X": {}})

        self.assertEqual(
            events,
            [
                "writer.start",
                "organizer.start",
                "enricher.start",
                "fetcher.start",
                "fetcher.join",
                "fetch_queue.join",
                "enricher.stop",
                "enrich_queue.join",
                "organizer.stop",
                "organize_queue.join",
                "writer.stop",
            ],
        )

    def test_writer_uses_unique_filename_suffix_for_same_event_and_date(self):
        writer = WriterStage(organize_queue=None, output_dir="D:\\virtual-output", batch_timestamp="20260207_000000")

        base = {
            "domain": "AI",
            "event": "Same Event",
            "date": "2026-02-07",
            "quality_score": 4,
            "quality_reason": "ok",
            "source_name": "src",
            "category": "cat",
            "key_info": "k",
            "detail": "d",
        }

        r1 = dict(base)
        r1["link"] = "https://example.com/a"
        r2 = dict(base)
        r2["link"] = "https://example.com/b"

        open_mock = mock_open()
        with patch("native_scout.stages.result_writer.os.makedirs"), patch(
            "native_scout.stages.result_writer.shutil.copy2"
        ), patch("builtins.open", open_mock):
            writer._write_post_file(r1)
            writer._write_post_file(r2)

        written = [call.args[0] for call in open_mock.call_args_list]
        self.assertEqual(len(written), 2)
        self.assertNotEqual(os.path.basename(written[0]), os.path.basename(written[1]))

    def test_organize_single_post_uses_injected_client_and_config(self):
        fake_client = _FakeClient()

        llm_config = configparser.ConfigParser()
        llm_config.add_section("llm")
        llm_config.set("llm", "model", "unit-test-model")

        post = {
            "title": "title",
            "date": "2026-02-07",
            "link": "https://example.com",
            "source_type": "X",
            "source_name": "source",
            "content": "content",
            "extra_content": "",
            "extra_urls": [],
        }

        result = organize_single_post(
            post,
            prompt_template="{title}",
            llm_client=fake_client,
            llm_config=llm_config,
            max_retries=0,
        )

        self.assertTrue(fake_client.called)
        self.assertEqual(fake_client.kwargs["model"], "unit-test-model")
        self.assertEqual(result["source_name"], "source")
        self.assertEqual(result["link"], "https://example.com")

    def test_extract_youtube_id_non_youtube_and_non_video_paths_do_not_crash(self):
        fetcher = GenericVideoFetcher()

        parsed_non_yt = urlparse("https://example.com/path")
        self.assertIsNone(fetcher._extract_youtube_id(parsed_non_yt, parsed_non_yt.netloc.lower()))

        parsed_channel = urlparse("https://www.youtube.com/channel/abc")
        self.assertIsNone(fetcher._extract_youtube_id(parsed_channel, parsed_channel.netloc.lower()))

    def test_shared_source_loader_matches_native_scout_shape(self):
        config = configparser.ConfigParser()
        config.optionxform = str
        config.add_section("rsshub")
        config.set("rsshub", "base_url", "http://rsshub.local")
        config.add_section("weixin_accounts")
        config.set("weixin_accounts", "WX_A", "https://wx.example/feed.xml")
        config.set("weixin_accounts", "WX_Empty", "  ")
        config.add_section("x_accounts")
        config.set("x_accounts", "X_A", "openai")
        config.add_section("youtube_channels")
        config.set("youtube_channels", "YT_A", "channel123")

        sources = load_sources(config)

        self.assertEqual(
            sources,
            {
                "weixin": {"WX_A": "https://wx.example/feed.xml"},
                "X": {"X_A": "http://rsshub.local/twitter/user/openai"},
                "YouTube": {"YT_A": "https://www.youtube.com/feeds/videos.xml?channel_id=channel123"},
            },
        )


if __name__ == "__main__":
    unittest.main()
