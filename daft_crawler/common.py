"""
common.py - shared helpers for daft_crawler.
"""

# Time window config: look back N days.
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


def get_enrich_concurrency():
    import os
    import configparser
    
    config_path = os.path.join(os.path.dirname(__file__), "..", "config-test.ini")
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    return config.getint("crawler", "enrich_workers", fallback=3)


def get_organize_concurrency():
    import os
    import configparser
    
    config_path = os.path.join(os.path.dirname(__file__), "..", "config-test.ini")
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    return config.getint("crawler", "organize_workers", fallback=5)
