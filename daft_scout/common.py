"""
common.py - shared helpers for daft_scout.
"""

import os

from shared.config_loader import load_ini


DAYS_LOOKBACK = 7


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


logger = setup_logger("daft_common")


def load_config(config_name: str = "config-test.ini"):
    """Load a config file from the project root."""
    return load_ini(__file__, os.path.join("..", config_name), preserve_case=True)


def get_enrich_concurrency(config=None):
    config = config or load_config()
    return config.getint("crawler", "enrich_workers", fallback=3)


def get_organize_concurrency(config=None):
    config = config or load_config()
    return config.getint("crawler", "organize_workers", fallback=5)
