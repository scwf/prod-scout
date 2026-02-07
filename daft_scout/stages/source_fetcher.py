"""
source_fetcher.py - RSS source fetching stage for Daft pipeline.
"""
import os
import json
import time
import random
import daft
from daft import col, DataType
from datetime import datetime, timezone

from common import setup_logger

logger = setup_logger("daft_source_fetcher")

POST_STRUCT = DataType.struct(
    {
        "title": DataType.string(),
        "date": DataType.string(),
        "link": DataType.string(),
        "rss_url": DataType.string(),
        "source_type": DataType.string(),
        "source_name": DataType.string(),
        "content": DataType.string(),
    }
)

def _create_source_df(sources, schema_dict):
    if not sources:
        # Create empty DF with specific schema
        return daft.from_pydict({k: [] for k in schema_dict.keys()}).select(
            *[col(k).cast(v) for k, v in schema_dict.items()]
        )
    # Inline _rows_to_pydict logic
    keys = sorted({k for row in sources for k in row.keys()})
    pydict = {k: [row.get(k) for row in sources] for k in keys}
    return daft.from_pydict(pydict)


def _save_raw_backup(posts, source_type, name, batch_timestamp):
    if not posts:
        return
    try:
        raw_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", f"raw_{batch_timestamp}")
        os.makedirs(raw_dir, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        filename = f"{source_type}_{safe_name}.json"

        with open(os.path.join(raw_dir, filename), "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.info(f"Raw backup failed: {e}")


def _fetch_posts(rss_url, source_type, name, batch_timestamp, save_raw=True):
    import feedparser
    import requests
    from dateutil import parser as date_parser

    logger.info(f"Fetching [{source_type}] {name}: {rss_url} ...")
    try:
        try:
            response = requests.get(rss_url, timeout=30)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        except requests.exceptions.Timeout:
            logger.info(f"Timeout (30s): {rss_url}")
            return []
        except requests.exceptions.RequestException as e:
            logger.info(f"Request failed: {e}")
            return []

        if feed.bozo and not feed.entries:
            logger.info(f"RSS parse failed: {feed.bozo_exception}")
            return []

        posts = []

        for entry in feed.entries:
            # Parse date
            post_date = None
            if hasattr(entry, "published"):
                try:
                    dt = date_parser.parse(entry.published)
                    post_date = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
                except Exception:
                    pass
            
            if not post_date:
                continue
            
            # Parse content (handle list format from feedparser)
            content = ""
            if hasattr(entry, "content") and entry.content:
                # Usually a list of dicts like [{'type': 'text/html', 'value': '...'}]
                # for weixin, the content is valid, for twitter and youtube, the content is invalid
                content = entry.content[0].value
            else:
                content = entry.get("description", "")

            posts.append(
                {
                    "title": entry.title,
                    "date": post_date.strftime("%Y-%m-%d"),
                    "link": entry.link,
                    "rss_url": rss_url,
                    "source_type": source_type,
                    "source_name": name,
                    "content": content,
                }
            )

        if save_raw:
            _save_raw_backup(posts, source_type, name, batch_timestamp)

        return posts
    except Exception as e:
        logger.info(f"Fetch failed: {e}")
        return []


@daft.cls(max_concurrency=2, use_process=False)
class FetchWeixin:
    def __init__(self):
        pass

    @daft.method(return_dtype=POST_STRUCT, unnest=True)
    def __call__(self, rss_url: str, source_name: str, batch_timestamp: str):
        posts = _fetch_posts(
            rss_url,
            source_type="weixin",
            name=source_name,
            batch_timestamp=batch_timestamp,
            save_raw=True,
        )
        for post in posts:
            yield post


@daft.cls(max_concurrency=2, use_process=False)
class FetchYouTube:
    def __init__(self):
        pass

    @daft.method(return_dtype=POST_STRUCT, unnest=True)
    def __call__(self, rss_url: str, source_name: str, batch_timestamp: str):
        posts = _fetch_posts(
            rss_url,
            source_type="YouTube",
            name=source_name,
            batch_timestamp=batch_timestamp,
            save_raw=True,
        )
        for post in posts:
            yield post


@daft.cls(max_concurrency=1, use_process=False)
class FetchX:
    def __init__(self, delay_min: int, delay_max: int):
        self.delay_min = delay_min
        self.delay_max = delay_max

    @daft.method(return_dtype=POST_STRUCT, unnest=True)
    def __call__(self, rss_url: str, source_name: str, batch_timestamp: str):
        # Enforce random delay for X to prevent rate-limiting
        if self.delay_min > 0 or self.delay_max > 0:
            time.sleep(random.uniform(self.delay_min, self.delay_max))

        posts = _fetch_posts(
            rss_url,
            source_type="X",
            name=source_name,
            batch_timestamp=batch_timestamp,
            save_raw=True,
        )
        for post in posts:
            yield post


class SourceFetcher:
    def __init__(self, config, batch_timestamp):
        self.config = config
        self.batch_timestamp = batch_timestamp

    def fetch_posts_df(self, rss_sources):
        if not rss_sources:
             logger.info("No sources configured; exit")
             raise SystemExit(0)

        x_delay_min = self.config.getint("crawler", "x_request_delay_min", fallback=3)
        x_delay_max = self.config.getint("crawler", "x_request_delay_max", fallback=8)

        weixin_sources = [
            {"source_name": n, "rss_url": u, "batch_timestamp": self.batch_timestamp}
            for n, u in rss_sources.get("weixin", {}).items()
        ]
        youtube_sources = [
            {"source_name": n, "rss_url": u, "batch_timestamp": self.batch_timestamp}
            for n, u in rss_sources.get("YouTube", {}).items()
        ]
        x_sources = [
            {"source_name": n, "rss_url": u, "batch_timestamp": self.batch_timestamp}
            for n, u in rss_sources.get("X", {}).items()
        ]


        # Define schemas for inputs
        base_schema_dict = {
            "source_name": DataType.string(),
            "rss_url": DataType.string(),
            "batch_timestamp": DataType.string(),
        }

        x_schema_dict = base_schema_dict

        weixin_df = _create_source_df(weixin_sources, base_schema_dict)
        youtube_df = _create_source_df(youtube_sources, base_schema_dict)
        x_df = _create_source_df(x_sources, base_schema_dict)

        # Instantiate UDF classes with configuration
        fetch_weixin = FetchWeixin()
        fetch_youtube = FetchYouTube()
        # Pass delay config to FetchX constructor
        fetch_x = FetchX(x_delay_min, x_delay_max)

        weixin_posts_df = weixin_df.select(
            fetch_weixin(
                col("rss_url"),
                col("source_name"),
                col("batch_timestamp"),
            )
        )
        youtube_posts_df = youtube_df.select(
            fetch_youtube(
                col("rss_url"),
                col("source_name"),
                col("batch_timestamp"),
            )
        )
        x_posts_df = x_df.select(
            fetch_x(
                col("rss_url"),
                col("source_name"),
                col("batch_timestamp"),
            )
        )
        
        df_all = weixin_posts_df.concat(youtube_posts_df).concat(x_posts_df)

        return df_all
