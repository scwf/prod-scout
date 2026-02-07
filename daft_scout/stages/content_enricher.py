"""
content_enricher.py - content enrichment stage for Daft pipeline.
"""
import json
import daft
from daft import col, DataType
from common import setup_logger, get_enrich_concurrency
from utils.content_fetcher import ContentFetcher

ENRICH_STRUCT = DataType.struct(
    {
        "extra_content": DataType.string(),
        "extra_urls": DataType.list(DataType.string()),
    }
)

logger = setup_logger("daft_content_enricher")

@daft.cls(max_concurrency=get_enrich_concurrency(), use_process=False)
class EnrichUDF:
    def __init__(self, config):
        self.content_fetcher = ContentFetcher(config)
        self.optimize_video = config.getboolean("llm", "enable_subtitle_optimization", fallback=False)

    @daft.method(return_dtype=ENRICH_STRUCT, unnest=True)
    def __call__(self, source_type: str, title: str, link: str, content: str) -> dict:
        extra_content = ""
        extra_urls = []
        try:
            if source_type == "X":
                embedded, extra_urls = self.content_fetcher.fetch_embedded_content(
                    content,
                    title=title,
                    optimize_video=self.optimize_video,
                )
                if embedded:
                    parts = [f"[{i.content_type}] {i.content}" for i in embedded if i.content]
                    extra_content = "\n\n".join(parts)
            elif source_type == "YouTube":
                full_context = f"{title}\n{content}" if content else title
                yt = self.content_fetcher.video_fetcher.fetch(
                    link,
                    context=full_context,
                    title=title,
                    optimize=self.optimize_video,
                )
                if yt and yt.content:
                    extra_content = yt.content
        except Exception as e:
            logger.warning(f"Enrichment failed for {link}: {e}")
            extra_content = ""
            extra_urls = []

        return {"extra_content": extra_content, "extra_urls": extra_urls}


class ContentEnricher:
    def __init__(self, config):
        self.enrich_udf = EnrichUDF(config)

    def enrich(self, df):
        return df.select(
            col("*"),
            self.enrich_udf(col("source_type"), col("title"), col("link"), col("content")),
        )
