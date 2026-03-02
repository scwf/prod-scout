"""
common.py - shared helpers for native_scout.
"""

import json
import os
import threading
from datetime import datetime

from shared.config_loader import load_ini


MANIFEST_FILENAME = "latest_batch.json"


def setup_logger(name: str):
    import logging

    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


logger = setup_logger("common")


def _tid():
    """Return a simple thread identifier for logs."""
    return f"[T{threading.current_thread().name.split('_')[-1]}]"


def load_config(config_name: str = "config.ini"):
    """Load a config file from the project root."""
    return load_ini(__file__, os.path.join("..", config_name), preserve_case=True)


def save_batch_manifest(output_dir, batch_id, domain_reports, stats=None):
    """Save a batch manifest file."""
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "domain_reports": domain_reports,
    }

    if stats:
        manifest["stats"] = stats

    manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    logger.info(f"Batch manifest saved: {MANIFEST_FILENAME}")
    return manifest_path
