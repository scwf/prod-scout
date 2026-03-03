"""
pipeline.py - main Daft pipeline for RSS crawling.
"""
import os
import time
import daft
from daft import col, lit
from datetime import datetime, timezone, timedelta

from common.config import load_project_ini
from common.logging import setup_logger
from daft_scout.stages.source_fetcher import SourceFetcher
from daft_scout.stages.content_enricher import ContentEnricher
from daft_scout.stages.llm_organizer import LLMOrganizer
from daft_scout.stages.result_writer import ResultWriter
from common.source_loader import load_sources

logger = setup_logger("daft_pipeline")
DAYS_LOOKBACK = 7

class DaftPipeline:
    def __init__(self, config, batch_timestamp, output_dir):
        self.config = config
        self.batch_timestamp = batch_timestamp
        self.output_dir = output_dir

        self.fetcher = SourceFetcher(config, batch_timestamp)
        self.enricher = ContentEnricher(config)
        self.organizer = LLMOrganizer(config)
        self.writer = ResultWriter(output_dir, batch_timestamp)

    def run(self, rss_sources):
        df = self.fetcher.fetch_posts_df(rss_sources)

        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_LOOKBACK)).date().isoformat()
        
        # Use native Daft comparison which is much faster than running a Python UDF per row
        # Since date strings are ISO format (YYYY-MM-DD), string comparison is equivalent to date comparison
        df = df.where(col("date") >= lit(cutoff_date))

        df = self.enricher.enrich(df)
        df = self.organizer.organize(df)

        return self.writer.write_and_stats(df)

def _load_config():
    return load_project_ini(__file__, "config-test.ini", package_depth=0, preserve_case=True)


def _load_sources(config):
    return load_sources(config)


if __name__ == "__main__":
    import ray
    # ray.init(address=None, num_cpus=10, ignore_reinit_error=True)
    # daft.set_runner_ray(noop_if_initialized=True)
    daft.set_runner_native()
    start_time = time.time()
    batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config = _load_config()
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(output_dir, exist_ok=True)

    logger.info("Starting Daft pipeline...")
    pipeline = DaftPipeline(
        config=config,
        batch_timestamp=batch_timestamp,
        output_dir=output_dir,
    )
    result = pipeline.run(_load_sources(config))

    tier_counts = result["tier_counts"]
    domain_counts = result["domain_counts"]
    valid_count = result["valid_count"]

    tier_map = {row["quality_tier"]: row["count"] for row in tier_counts}
    total_high = tier_map.get("high", 0)
    total_pending = tier_map.get("pending", 0)
    total_excluded = tier_map.get("excluded", 0)

    print("\n" + "=" * 60)
    print("RUN SUMMARY")
    print("=" * 60)
    print(f"Total valid posts: {valid_count}")
    print("\nQuality distribution:")
    print(f"  high:     {total_high}")
    print(f"  pending:  {total_pending}")
    print(f"  excluded: {total_excluded}")
    print("\nDomains:")
    for row in domain_counts:
        domain = row["domain"]
        total = row["count"]
        print(f"  - {domain}: {total}")
    print("\nOutput dirs:")
    for domain, dir_name in result["domain_report_dirs"].items():
        print(f"  - {dir_name}/")
        print("      high/     (see manifest stats)")
        print("      pending/  (see manifest stats)")
        print("      excluded/ (see manifest stats)")

    elapsed_time = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"Done in {elapsed_time:.2f}s")
    print("=" * 60)
