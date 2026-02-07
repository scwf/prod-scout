"""
common.py - 公共配置和工具函数
"""
import os
import json
import configparser
from urllib.parse import urlparse
from datetime import datetime
import threading


# 时间范围配置,爬取最近多少天的内容
DAYS_LOOKBACK = 7

# 批次清单文件名
MANIFEST_FILENAME = "latest_batch.json"

def setup_logger(name: str):
    import logging
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger

logger = setup_logger("common")

def _tid():
    """获取当前线程标识，用于日志"""
    return f"[T{threading.current_thread().name.split('_')[-1]}]"


# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'), encoding='utf-8')

# ================= 批次清单管理 =================

def save_batch_manifest(output_dir, batch_id, domain_reports, stats=None):
    """
    保存批次清单文件
    
    参数:
        output_dir: str - 输出目录路径
        batch_id: str - 批次ID (通常是时间戳，如 20260124_123456)
        domain_reports: dict - 领域报告映射 {领域名称: 文件名}
        stats: dict - 统计信息 (可选)
    
    返回:
        str: 清单文件的完整路径
    """
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "domain_reports": domain_reports,
    }
    
    if stats:
        manifest["stats"] = stats
    
    manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    logger.info(f"批次清单已保存: {MANIFEST_FILENAME}")
    return manifest_path
    