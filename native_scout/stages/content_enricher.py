"""
content_enricher.py - EnricherStage for Native Python Pipeline.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

from common import logger
from content_fetcher import ContentFetcher

class EnricherStage:
    def __init__(self, fetch_queue: Queue, enrich_queue: Queue, config, batch_timestamp):
        self.fetch_queue = fetch_queue
        self.enrich_queue = enrich_queue
        self.config = config
        
        self.max_workers = config.getint('crawler', 'enrich_workers', fallback=5)
        self.pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="Content-Enricher")
        
        self.content_fetcher = ContentFetcher(batch_timestamp)
        self.futures = []

    def start(self):
        """Start consumer workers."""
        logger.info(f"Starting EnricherStage with {self.max_workers} workers...")
        for _ in range(self.max_workers):
            self.futures.append(
                self.pool.submit(self._worker_loop)
            )

    def stop(self):
        """
        Graceful Shutdown (Sentinel/Poison Pill).
        Inject 'max_workers' sentinels into input queue to signal workers to exit.
        """
        logger.info("Stopping EnricherStage... Sending poison pills.")
        for _ in range(self.max_workers):
            self.fetch_queue.put(None)
            
        # Wait for workers
        self.pool.shutdown(wait=True)
        logger.info("EnricherStage stopped.")

    def _worker_loop(self):
        while True:
            item = self.fetch_queue.get()
            
            if item is None:
                # Poison Pill
                self.fetch_queue.task_done()
                break
            
            try:
                logger.info(f"Enriching {item['source_type']}: {item['title']}, {item['link']}")
                self._process_item(item)
                self.enrich_queue.put(item)
            except Exception as e:
                logger.error(f"Enricher error: {e}")
            finally:
                self.fetch_queue.task_done()

    def _process_item(self, post):
        """
        Enrich logic adapted from rss_crawler.py
        """
        source_type = post.get('source_type', '')
        title = post.get('title', '')
        
        # Only enrich X and YouTube
        if source_type not in ('X', 'YouTube'):
            return

        try:
            if source_type == "X":
                content = post.get('content', '')
                extra_content, extra_urls = self._enrich_x_content(content, title)
                post['extra_content'] = extra_content
                post['extra_urls'] = extra_urls
                
            elif source_type == "YouTube":
                link = post.get('link', '')
                content = post.get('content', '')
                extra_content = self._enrich_youtube_content(link, title, content)
                post['extra_content'] = extra_content
                
        except Exception as e:
            t = title[:30] + "..." if len(title) > 30 else title
            logger.info(f"[{t}] Enrichment failed: {e}")

    def _enrich_x_content(self, content, title):
        try:
            enable_opt = self.config.getboolean('llm', 'enable_subtitle_optimization', fallback=False)
            embedded, extra_urls = self.content_fetcher.fetch_embedded_content(
                content, title=title, optimize_video=enable_opt
            )
            extra_content = ""
            if embedded:
                parts = [f"[{'Blog' if i.content_type == 'blog' else 'Subtitle'}] {i.content}" 
                         for i in embedded if i.content]
                extra_content = "\n\n".join(parts)
            
            if embedded or extra_urls:
                t = (title or "Untitled")
                logger.info(f"[{t[:30]}] X Enrich: {len(embedded)} items, {len(extra_urls)} urls")
            return extra_content, extra_urls
        except Exception as e:
            logger.warning(f"X enrich error: {e}")
            return "", []

    def _enrich_youtube_content(self, link, title, context=""):
        try:
            full_context = f"{title}\n{context}" if context else title
            enable_opt = self.config.getboolean('llm', 'enable_subtitle_optimization', fallback=False)
            yt = self.content_fetcher.video_fetcher.fetch(
                link, context=full_context, title=title, optimize=enable_opt
            )
            if yt and yt.content:
                logger.info(f"[{title[:30]}] YT Enrich: {len(yt.content)} chars")
                return yt.content
        except Exception as e:
            logger.warning(f"Youtube enrich error: {e}")
            pass
        return ""
