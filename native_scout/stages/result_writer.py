"""
result_writer.py - WriterStage for Native Python Pipeline.
"""
import os
import json
import time
import threading
import hashlib
import shutil
from queue import Queue
from datetime import datetime

from common import setup_logger, save_batch_manifest

logger = setup_logger("result_writer")

class WriterStage:
    def __init__(self, organize_queue: Queue, output_dir, batch_timestamp):
        self.organize_queue = organize_queue
        self.output_dir = output_dir
        self.batch_timestamp = batch_timestamp
        
        self.thread = None
        
        # Stats tracking
        # {domain: {'path': ..., 'name': ..., 'high': 0, ...}}
        self.domain_info_map = {} 
        self.total_posts = 0
        
        # Entity Mapping
        self.entity_mapping = self._load_entity_mapping()
        self.source_to_entity = self._build_source_index()
        self.entity_stats = {}  # {entity_name: count}

    def _load_entity_mapping(self):
        """
        Load entity mapping from config.ini [entity_mapping] section.
        Format: CanonicalEntity = alias1, alias2, ...
        """
        mapping = {}
        try:
            import configparser
            
            # Resolve config.ini path (Assume in project root)
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(base_dir, "config.ini")
            
            if not os.path.exists(config_path):
                logger.warning(f"Config file not found at {config_path}")
                return {}
            
            # Use optionxform=str to preserve key case (e.g. "OpenAI" instead of "openai")
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(config_path, encoding='utf-8')
            
            if 'entity_mapping' in config:
                for entity, aliases_str in config['entity_mapping'].items():
                    aliases = [a.strip() for a in aliases_str.split(',') if a.strip()]
                    if entity not in aliases:
                        aliases.append(entity)
                    mapping[entity] = aliases
                    
            return mapping
            
        except Exception as e:
            logger.error(f"Failed to load entity mapping from config.ini: {e}")
            return {}    

    def _build_source_index(self):
        """Build reverse index: source_key -> canonical_entity"""
        index = {}
        for entity_name, sources in self.entity_mapping.items():
            for source in sources:
                index[source.lower()] = entity_name
        return index

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

    def _get_domain_info(self, domain):
        if domain not in self.domain_info_map:
            safe_domain = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in domain)
            
            # New Structure: 1-By-Domain/{Domain}
            dir_name = safe_domain
            dir_path = os.path.join(self.output_dir, "By-Domain", dir_name)
            
            for tier in ['high', 'pending', 'excluded']:
                os.makedirs(os.path.join(dir_path, tier), exist_ok=True)
            
            self.domain_info_map[domain] = {
                'path': dir_path,
                'name': dir_name,
                'high': 0, 'pending': 0, 'excluded': 0,
                'posts': []
            }
        return self.domain_info_map[domain]

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
            f"- **Source_Type**: {post.get('source_type', 'Unknown')}",
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
        source_name = result.get('source_name', 'Unknown')
        
        # 1. Write to Domain View (Master Copy)
        domain_info = self._get_domain_info(domain)
        tier = self._get_quality_tier(quality_score)
        
        link = result.get('link', '')
        unique_suffix = hashlib.md5(link.encode('utf-8')).hexdigest()[:6] if link else "nolink"
        filename = f"{source_name}_{date_str}_{unique_suffix}.md"
        
        domain_filepath = os.path.join(domain_info['path'], tier, filename)
        
        md_content = self._generate_post_markdown(result, domain)
        with open(domain_filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)

        # Collect for JSON
        post_json = {
            "title": event,
            "summary": result.get('key_info', ''),
            "quality_score": quality_score,
            "quality_reason": result.get('quality_reason', ''),
            "link": link,
            "date": date_str,
            "category": result.get('category', 'Uncategorized'),
            "primary_entity": result.get('primary_entity'),
            "source_name": source_name,
            "source_type": result.get('source_type', 'Unknown')
        }
        domain_info['posts'].append(post_json)
        domain_info[tier] += 1
        
        # 2. Write to Entity View
        # Priority: Source Mapping > LLM primary_entity (already constrained by prompt)
        canonical_entity = None
        
        # A. Source Mapping (High Confidence)
        if source_name:
            canonical_entity = self.source_to_entity.get(source_name.lower())
        
        # B. Fallback to LLM primary_entity (constrained to entity list + "Others")
        if not canonical_entity:
            canonical_entity = result.get('primary_entity', 'Others')
        
        if tier in ['high', 'pending']:
            self._write_to_entity_view(canonical_entity, domain_filepath, filename)

        logger.info(f"💾 [Saved] [{tier.upper()}] {filename}") # Reduce log noise
        return tier

    def _write_to_entity_view(self, entity_name, original_path, filename):
        """
        Link/Copy file to 3-By-Entity/{EntityName}/
        """
        if not entity_name:
            return

        # Sanitize entity name for filesystem
        safe_entity = "".join(c if c.isalnum() or c in ('-', '_', ' ') else '_' for c in entity_name).strip()
        
        entity_dir = os.path.join(self.output_dir, "By-Entity", safe_entity)
        os.makedirs(entity_dir, exist_ok=True)
        
        target_path = os.path.join(entity_dir, filename)
        
        try:
            shutil.copy2(original_path, target_path)
            # Update stats
            self.entity_stats[safe_entity] = self.entity_stats.get(safe_entity, 0) + 1
        except Exception as e:
            logger.error(f"Failed to copy to entity view {safe_entity}: {e}")

    def _finalize_batch(self):
        """Save stats and manifest."""
        # Save JSON for each domain
        for domain, info in self.domain_info_map.items():
            json_path = os.path.join(info['path'], 'posts.json')
            try:
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(info['posts'], f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Failed to save posts.json for {domain}: {e}")

        total_high = sum(info['high'] for info in self.domain_info_map.values())
        total_pending = sum(info['pending'] for info in self.domain_info_map.values())
        total_excluded = sum(info['excluded'] for info in self.domain_info_map.values())
        
        domain_reports = {domain: info['name'] for domain, info in self.domain_info_map.items()}
        
        # Manifest
        save_batch_manifest(
            output_dir=self.output_dir,
            batch_id=self.batch_timestamp,
            domain_reports=domain_reports,
            stats={
                "total_posts": self.total_posts,
                "domain_count": len(self.domain_info_map),
                "quality_distribution": {
                    "high": total_high,
                    "pending": total_pending,
                    "excluded": total_excluded
                },
                "top_entities": self.entity_stats
            }
        )
        
        self._print_summary(total_high, total_pending, total_excluded)

    def _print_summary(self, high, pending, excluded):
        print("\n" + "="*60)
        print("Execution Summary")
        print("="*60)
        print(f"Total Valid Posts: {self.total_posts}")
        print(f"Quality Distribution: H:{high} / P:{pending} / E:{excluded}")
        
        print(f"\nDomains:")
        for domain, info in self.domain_info_map.items():
            print(f"  - {domain}: {info['high']} H / {info['pending']} P")
            
        print(f"\nEntities (Auto-Grouped):")
        sorted_entities = sorted(self.entity_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        if not sorted_entities:
            print("  (None detected)")
        for ent, count in sorted_entities:
            print(f"  - {ent}: {count} posts")
        print("="*60)
