"""
source_fetcher.py - FetcherStage for Native Python Pipeline.
"""
import time
import random
import os
import json
import requests
import feedparser
from datetime import datetime, timezone
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

from common import logger

class FetcherStage:
    def __init__(self, fetch_queue: Queue, config, batch_timestamp):
        self.fetch_queue = fetch_queue
        self.config = config
        self.batch_timestamp = batch_timestamp
        
        # Pool for Weixin/YouTube (Parallel)
        self.general_workers = 5
        self.general_pool = ThreadPoolExecutor(max_workers=self.general_workers, thread_name_prefix="Weixin+YouTubeFetcher")
        
        # Pool for X/Twitter (Restricted Serial)
        # Still use ThreadPoolExecutor for consistency and extensibility
        self.restricted_workers = 1 
        self.restricted_pool = ThreadPoolExecutor(max_workers=self.restricted_workers, thread_name_prefix="XFetcher")
        
        self.futures = []

    def start(self, rss_sources):
        """
        Start fetching tasks.
        rss_sources: dict like {"weixin": {...}, "X": {...}, "YouTube": {...}}
        """
        logger.info("Starting FetcherStage...")
        
        # Flatten sources into a list of tasks
        # Task format: (category, name, url)
        
        # 1. Weixin
        for name, url in rss_sources.get("weixin", {}).items():
            self.futures.append(
                self.general_pool.submit(self._fetch_task, url, "weixin", name)
            )
            
        # 2. YouTube
        for name, url in rss_sources.get("YouTube", {}).items():
            self.futures.append(
                self.general_pool.submit(self._fetch_task, url, "YouTube", name)
            )
            
        # 3. X (Twitter) - Submitted to restricted pool
        # For X, we wrap the task to include the sleep logic seamlessly, 
        # or we rely on the single-thread nature + internal sleep.
        # Since the pool size is 1, simply submitting tasks will naturally queue them.
        # To strictly enforce "sleep BETWEEN tasks", we can add sleep at the start of the task
        # or manage it in a loop. A simple way in a pool of 1 is to sleep inside the task.
        x_items = list(rss_sources.get("X", {}).items())
        # Shuffle to randomize order each run if desired? (Optional, skipping for now)
        
        for name, url in x_items:
             self.futures.append(
                self.restricted_pool.submit(self._fetch_x_task, url, "X", name)
            )

    def join(self):
        """Wait for all fetch tasks to complete."""
        for future in as_completed(self.futures):
            try:
                future.result()
            except Exception as e:
                logger.error(f"Fetcher task exception: {e}")
        
        self.general_pool.shutdown(wait=True)
        self.restricted_pool.shutdown(wait=True)
        logger.info("FetcherStage finished.")

    def _fetch_x_task(self, rss_url, source_type, name):
        """Wrapper for X tasks to add random delay."""
        # Get delay config
        delay_min = self.config.getint('crawler', 'x_request_delay_min', fallback=30)
        delay_max = self.config.getint('crawler', 'x_request_delay_max', fallback=60)
        
        # Introduce a random delay to mitigate X (Twitter) rate limiting.
        # Since restricted_pool has max_workers=1, tasks execute sequentially;
        # sleeping at the start of each task ensures a mandatory gap between requests.
        sleep_time = random.uniform(delay_min, delay_max)
        logger.info(f"Waiting {sleep_time:.1f}s for X request...")
        time.sleep(sleep_time)
        
        self._fetch_task(rss_url, source_type, name)

    def _fetch_task(self, rss_url, source_type, name):
        """Core fetch logic."""
        # Config: Days Lookback
        days_lookback = 7 # Could read from config if needed, default 7
        
        posts = self._fetch_recent_posts(rss_url, days_lookback, source_type, name)
        
        if posts:
            logger.info(f"-> [{source_type}] {name} Fetched {len(posts)} posts")
            for post in posts:
                self.fetch_queue.put(post)

    def _fetch_recent_posts(self, rss_url, days, source_type, name):
        """
        Logic copied and adapted from rss_crawler.py
        """
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

            recent_posts = []
            now = datetime.now(timezone.utc)

            for entry in feed.entries:
                # 1. Date Check
                post_date = self._parse_date(entry)
                if not post_date or (now - post_date).days > days:
                    continue

                # 2. Extract Content. Parse content (handle list format from feedparser)
                content = ""
                if hasattr(entry, "content") and entry.content:
                    # Usually a list of dicts like [{'type': 'text/html', 'value': '...'}]
                    # for weixin, the content is valid, for twitter and youtube, the content is invalid
                    content = entry.content[0].value
                else:
                    content = entry.get("description", "")

                # 3. Create Dict (Lightweight)
                recent_posts.append({
                    "title": entry.title,
                    "date": post_date.strftime("%Y-%m-%d"),
                    "link": entry.link,
                    "rss_url": rss_url,
                    "source_type": source_type,
                    "source_name": name,
                    "content": content,
                    # Fields to be filled by Enricher
                    "extra_content": "",   
                    "extra_urls": []       
                })

            # Save Backup
            self._save_raw_backup(recent_posts, source_type, name)
            
            return recent_posts
        except Exception as e:
            logger.info(f"Fetch loop failed: {e}")
            return []

    def _parse_date(self, entry):
        if not hasattr(entry, 'published'): return None
        try:
            dt = date_parser.parse(entry.published)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except:
            return None

    def _save_raw_backup(self, posts, source_type, name):
        """Save raw data backup."""
        if not posts: return
        try:
            # stages/.. -> crawler/.. -> root
            raw_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data', f'raw_{self.batch_timestamp}')
            os.makedirs(raw_dir, exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in name)
            filename = f"{source_type}_{safe_name}.json"
            
            with open(os.path.join(raw_dir, filename), 'w', encoding='utf-8') as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.info(f"Backup failed: {e}")
