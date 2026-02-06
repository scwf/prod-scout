"""
result_writer.py - write outputs and stats for Daft pipeline.
"""
import os
import json
import daft
from daft import col, DataType
from datetime import datetime

from common import setup_logger


logger = setup_logger("daft_result_writer")


def _domain_dir_name(domain: str, batch_timestamp: str) -> str:
    safe_domain = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in domain)
    return f"{safe_domain}_{batch_timestamp}"


def _generate_post_markdown(post, domain):
    score = post.get("quality_score", 3)
    stars = "*" * score + "-" * (5 - score)

    lines = [
        f"# {post.get('event', 'Untitled')}",
        "",
        f"- **Date**: {post.get('date', 'Unknown')} ",
        f"- **Category**: {post.get('category', 'Unknown')}",
        f"- **Domain**: {domain}",
        f"- **Quality**: {stars} ({score}/5)",
        f"- **Reason**: {post.get('quality_reason', '')}",
        f"- **Source**: {post.get('source_name', 'Unknown')}",
        f"- **Link**: {post.get('link', '')}",
        "",
        "## Key Info",
        post.get("key_info", ""),
        "",
        "## Details",
        post.get("detail", ""),
        "",
    ]

    if post.get("extra_content"):
        lines.extend(["## Extra Content", post["extra_content"], ""])

    if post.get("extra_urls"):
        lines.append("## External Links")
        lines.extend([f"- {url}" for url in post["extra_urls"]])
        lines.append("")

    return "\n".join(lines)


@daft.cls(max_concurrency=3, use_process=False)
class PostWriterUDF:
    def __init__(self, output_dir: str, batch_timestamp: str):
        self.output_dir = output_dir
        self.batch_timestamp = batch_timestamp

    @daft.method(return_dtype=DataType.string())
    def __call__(
        self,
        domain: str,
        category: str,
        event: str,
        date_str: str,
        quality_score: int,
        quality_reason: str,
        source_name: str,
        link: str,
        key_info: str,
        detail: str,
        extra_content: str,
        extra_urls: list,
    ) -> str:
        if not domain or not event:
            return "excluded"

        dir_name = _domain_dir_name(domain, self.batch_timestamp)
        dir_path = os.path.join(self.output_dir, dir_name)
        tier = "excluded"
        if quality_score >= 4:
            tier = "high"
        elif quality_score >= 2:
            tier = "pending"
            
        os.makedirs(os.path.join(dir_path, tier), exist_ok=True)

        safe_event = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in event)[:50]
        filename = f"{safe_event}_{date_str or 'Unknown'}.md"
        filepath = os.path.join(dir_path, tier, filename)

        post = {
            "event": event,
            "date": date_str,
            "category": category or "",
            "quality_score": quality_score or 0,
            "quality_reason": quality_reason or "",
            "source_name": source_name or "",
            "link": link or "",
            "key_info": key_info or "",
            "detail": detail or "",
            "extra_content": extra_content or "",
            "extra_urls": extra_urls or [],
            "tier": tier,
        }

        md_content = _generate_post_markdown(post, domain)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        return tier


def save_batch_manifest(output_dir, batch_id, domain_reports, manifest_filename, summary_report=None, stats=None):
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "source": "daft_crawler",
        "domain_reports": domain_reports,
    }

    if summary_report:
        manifest["summary_report"] = summary_report

    if stats:
        manifest["stats"] = stats

    manifest_path = os.path.join(output_dir, manifest_filename)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"Manifest saved: {manifest_filename}")
    return manifest_path


class ResultWriter:
    def __init__(self, output_dir, batch_timestamp):
        self.output_dir = output_dir
        self.batch_timestamp = batch_timestamp
        self.manifest_filename = "latest_batch_daft.json"

    def write_and_stats(self, df):
        post_writer = PostWriterUDF(self.output_dir, self.batch_timestamp)
        df_valid = df.where(col("event").not_null())
        df_valid = df_valid.with_column(
            "quality_tier",
            post_writer(
                col("domain"),
                col("category"),
                col("event"),
                col("date"),
                col("quality_score"),
                col("quality_reason"),
                col("source_name"),
                col("link"),
                col("key_info"),
                col("detail"),
                col("extra_content"),
                col("extra_urls"),
            ),
        )

        df_valid = df_valid.collect()
        valid_count = len(df_valid)
        logger.info(f"Organized {valid_count} valid posts")

        if valid_count > 0:
            tier_counts = (
                df_valid.groupby("quality_tier")
                .agg(col("quality_tier").count().alias("count"))
                .sort("quality_tier")
                .to_pylist()
            )

            domain_counts = (
                df_valid.groupby("domain")
                .agg(col("domain").count().alias("count"))
                .sort("domain")
                .to_pylist()
            )
        else:
            tier_counts = []
            domain_counts = []

        tier_map = {row["quality_tier"]: row["count"] for row in tier_counts}
        total_high = tier_map.get("high", 0)
        total_pending = tier_map.get("pending", 0)
        total_excluded = tier_map.get("excluded", 0)

        domain_report_dirs = {
            row["domain"]: _domain_dir_name(row["domain"], self.batch_timestamp) for row in domain_counts
        }
        save_batch_manifest(
            output_dir=self.output_dir,
            batch_id=self.batch_timestamp,
            domain_reports=domain_report_dirs,
            manifest_filename=self.manifest_filename,
            stats={
                "total_posts": int(valid_count),
                "domain_count": len(domain_counts),
                "quality_distribution": {
                    "high": total_high,
                    "pending": total_pending,
                    "excluded": total_excluded,
                },
                "daft_quality_tiers": tier_counts,
                "daft_domain_counts": domain_counts,
            },
        )

        return {
            "valid_count": int(valid_count),
            "tier_counts": tier_counts,
            "domain_counts": domain_counts,
            "domain_report_dirs": domain_report_dirs,
        }
