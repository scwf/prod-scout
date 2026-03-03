"""
pipeline.py - Main entry point and coordinator for the native Python pipeline.
"""
import os
import time
import queue
from datetime import datetime

from common.config import load_project_ini
from common.logging import setup_logger
from native_scout.stages.source_fetcher import FetcherStage
from native_scout.stages.content_enricher import EnricherStage
from native_scout.stages.llm_organizer import OrganizerStage
from native_scout.stages.result_writer import WriterStage
from common.source_loader import load_sources

logger = setup_logger("pipeline")


class NativePipeline:
    def __init__(self, config, batch_timestamp, output_dir):
        self.config = config
        self.batch_timestamp = batch_timestamp
        self.output_dir = output_dir

        # Bounded queues for backpressure between stages.
        self.fetch_queue = queue.Queue(maxsize=1000)
        self.enrich_queue = queue.Queue(maxsize=1000)
        self.organize_queue = queue.Queue(maxsize=1000)

        self.fetcher = FetcherStage(self.fetch_queue, config, batch_timestamp)
        self.enricher = EnricherStage(self.fetch_queue, self.enrich_queue, config, batch_timestamp)
        self.organizer = OrganizerStage(self.enrich_queue, self.organize_queue, config)
        self.writer = WriterStage(self.organize_queue, output_dir, batch_timestamp)

    def run(self, rss_sources):
        start_time = time.time()
        logger.info(f"Starting Pipeline Batch: {self.batch_timestamp}")

        # Start consumers downstream to upstream.
        self.writer.start()
        self.organizer.start()
        self.enricher.start()

        # Start producer.
        self.fetcher.start(rss_sources)

        # Wait fetch submission/completion first.
        self.fetcher.join()
        # Drain stage-1 queue before stopping stage-2 workers.
        self.fetch_queue.join()

        self.enricher.stop()
        # Drain stage-2 queue before stopping stage-3 workers.
        self.enrich_queue.join()

        self.organizer.stop()
        # Drain stage-3 queue before stopping writer.
        self.organize_queue.join()

        self.writer.stop()

        elapsed = time.time() - start_time
        logger.info(f"Pipeline Finished in {elapsed:.2f}s")


# ================= Configuration Loading =================

def _load_config():
    return load_project_ini(__file__, "config.ini", package_depth=0, preserve_case=True)


def _load_sources(config):
    return load_sources(config)


if __name__ == "__main__":
    config = _load_config()
    batch_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data', batch_ts)
    os.makedirs(output_dir, exist_ok=True)

    sources = _load_sources(config)
    total_sources = sum(len(v) for v in sources.values())
    breakdown = ", ".join([f"{k}: {len(v)}" for k, v in sources.items()])
    logger.info(f"Loaded {total_sources} sources ({breakdown}).")

    pipeline = NativePipeline(config, batch_ts, output_dir)
    pipeline.run(sources)
