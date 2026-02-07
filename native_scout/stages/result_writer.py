"""
result_writer.py - WriterStage for Native Python Pipeline.
"""
import os
import time
import threading
import hashlib
from queue import Queue
from datetime import datetime

from common import logger, save_batch_manifest

def group_posts_by_domain(all_posts):
    """
    按所属领域对文章进行分组
    
    参数:
        all_posts: list[dict] - 所有整理后的文章数据列表
    
    返回:
        dict: {domain: list[dict]} - 按领域分组的文章
    """
    grouped = {}
    for post in all_posts:
        domain = post.get('domain', '其他')
        if domain not in grouped:
            grouped[domain] = []
        grouped[domain].append(post)
    return grouped


class WriterStage:
    def __init__(self, organize_queue: Queue, output_dir, batch_timestamp):
        self.organize_queue = organize_queue
        self.output_dir = output_dir
        self.batch_timestamp = batch_timestamp
        
        self.thread = None
        
        # Stats tracking
        # {domain: {'path': ..., 'name': ..., 'high': 0, ...}}
        self.domain_dirs = {} 
        self.total_posts = 0

    def start(self):
        logger.info("Starting WriterStage...")
        self.thread = threading.Thread(target=self._worker_loop, name="WriterThread")
        self.thread.start()

    def stop(self):
        logger.info("Stopping WriterStage... Sending poison pill.")
        self.organize_queue.put(None)
        self.thread.join()
        logger.info("WriterStage stopped.")

    def _worker_loop(self):
        while True:
            result = self.organize_queue.get()
            
            if result is None:
                self._finalize_batch()
                self.organize_queue.task_done()
                break
            
            try:
                self._write_post_file(result)
                self.total_posts += 1
            except Exception as e:
                logger.error(f"Writer error: {e}")
            finally:
                self.organize_queue.task_done()

    def _get_quality_tier(self, score):
        if score >= 4: return "high"
        elif score >= 2: return "pending"
        else: return "excluded"

    def _get_domain_dir(self, domain):
        if domain not in self.domain_dirs:
            safe_domain = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in domain)
            dir_name = f"{safe_domain}_{self.batch_timestamp}"
            dir_path = os.path.join(self.output_dir, dir_name)
            
            for tier in ['high', 'pending', 'excluded']:
                os.makedirs(os.path.join(dir_path, tier), exist_ok=True)
            
            self.domain_dirs[domain] = {
                'path': dir_path,
                'name': dir_name,
                'high': 0, 'pending': 0, 'excluded': 0
            }
        return self.domain_dirs[domain]

    def _generate_post_markdown(self, post, domain):
        score = post.get('quality_score', 3)
        stars = '⭐' * score + '☆' * (5 - score)
        
        lines = [
            f"# {post.get('event', 'Untitled')}",
            "",
            f"- **Date**: {post.get('date', 'Unknown')}",
            f"- **Category**: {post.get('category', 'Uncategorized')}",
            f"- **Domain**: {domain}",
            f"- **Quality**: {stars} ({score}/5)",
            f"- **Reason**: {post.get('quality_reason', 'None')}",
            f"- **Source**: {post.get('source_name', 'Unknown')}",
            f"- **Link**: {post.get('link', '')}",
            "",
            "## Key Info",
            post.get('key_info', ''),
            "",
            "## Details",
            post.get('detail', ''),
            "",
        ]
        
        if post.get('extra_content'):
            lines.extend(["## Extra Content", post['extra_content'], ""])
        
        if post.get('extra_urls'):
            lines.append("## External Links")
            lines.extend([f"- {url}" for url in post['extra_urls']])
            lines.append("")
        
        return "\n".join(lines)

    def _write_post_file(self, result):
        domain = result.get('domain', 'Other')
        event = result.get('event', 'Untitled event')
        date_str = result.get('date', 'Unknown date')
        quality_score = result.get('quality_score', 3)
        
        domain_info = self._get_domain_dir(domain)
        tier = self._get_quality_tier(quality_score)
        
        safe_event = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in event)[:50]
        link = result.get('link', '')
        unique_suffix = hashlib.md5(link.encode('utf-8')).hexdigest()[:8] if link else "nolink"
        filename = f"{safe_event}_{date_str}_{unique_suffix}.md"
        filepath = os.path.join(domain_info['path'], tier, filename)
        
        md_content = self._generate_post_markdown(result, domain)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        domain_info[tier] += 1
        return tier

    def _finalize_batch(self):
        """Save stats and manifest."""
        total_high = sum(info['high'] for info in self.domain_dirs.values())
        total_pending = sum(info['pending'] for info in self.domain_dirs.values())
        total_excluded = sum(info['excluded'] for info in self.domain_dirs.values())
        
        domain_reports = {domain: info['name'] for domain, info in self.domain_dirs.items()}
        
        save_batch_manifest(
            output_dir=self.output_dir,
            batch_id=self.batch_timestamp,
            domain_reports=domain_reports,
            stats={
                "total_posts": self.total_posts,
                "domain_count": len(self.domain_dirs),
                "quality_distribution": {
                    "high": total_high,
                    "pending": total_pending,
                    "excluded": total_excluded
                }
            }
        )
        
        self._print_summary(total_high, total_pending, total_excluded)

    def _print_summary(self, high, pending, excluded):
        print("\n" + "="*60)
        print("Execution Summary")
        print("="*60)
        print(f"Total Valid Posts: {self.total_posts}")
        print(f"\nQuality Distribution:")
        print(f"  High:     {high}")
        print(f"  Pending:  {pending}")
        print(f"  Excluded: {excluded}")
        print(f"\nDomains:")
        for domain, info in self.domain_dirs.items():
            print(f"  - {domain}: {info['high']} H / {info['pending']} P / {info['excluded']} E")
        print("="*60)
