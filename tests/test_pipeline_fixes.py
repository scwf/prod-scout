import configparser
import os
import sys
import tempfile
import unittest
from urllib.parse import urlparse

# Ensure project modules are importable.
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRAWLER_DIR = os.path.join(ROOT_DIR, "native_scout")
sys.path.insert(0, CRAWLER_DIR)
sys.path.insert(0, ROOT_DIR)

import pipeline
from content_fetcher import GenericVideoFetcher
from stages.llm_organizer import organize_single_post
from stages.result_writer import WriterStage


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
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = WriterStage(organize_queue=None, output_dir=tmp_dir, batch_timestamp="20260207_000000")

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

            writer._write_post_file(r1)
            writer._write_post_file(r2)

            written = []
            for root, _dirs, files in os.walk(tmp_dir):
                for name in files:
                    if name.endswith(".md"):
                        written.append(os.path.join(root, name))

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
            "content": "content",
            "extra_content": "",
            "extra_urls": [],
        }

        result = organize_single_post(post, "source", llm_client=fake_client, llm_config=llm_config, max_retries=0)

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


if __name__ == "__main__":
    unittest.main()
