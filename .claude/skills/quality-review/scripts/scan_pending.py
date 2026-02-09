"""
scan_pending.py - 扫描 pending 目录并提取情报元数据

用法:
    python scan_pending.py <pending_directory>
    
输出:
    JSON 格式的元数据列表，包含每个文件的标题、评分、理由等信息
"""

import os
import re
import sys
import json
from pathlib import Path


def extract_metadata(filepath: str) -> dict:
    """
    从 MD 文件头部提取元数据（仅读取前 20 行）
    
    返回:
        dict: 包含 filename, title, score, reason, source, date, category, domain
    """
    metadata = {
        "filename": os.path.basename(filepath),
        "filepath": filepath,
        "title": "",
        "score": 0,
        "score_display": "",
        "reason": "",
        "source": "",
        "date": "",
        "category": "",
        "domain": ""
    }
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            # 只读取前 20 行
            lines = []
            for i, line in enumerate(f):
                if i >= 20:
                    break
                lines.append(line)
            
            content = ''.join(lines)
            
            # 提取标题 (# 开头的第一行)
            title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
            if title_match:
                metadata["title"] = title_match.group(1).strip()
            
            # 提取质量评分 (⭐ 格式)
            score_match = re.search(r'\*\*质量评分\*\*:\s*([⭐☆]+)\s*\((\d)/5\)', content)
            if score_match:
                metadata["score_display"] = score_match.group(1)
                metadata["score"] = int(score_match.group(2))
            
            # 提取评分理由
            reason_match = re.search(r'\*\*评分理由\*\*:\s*(.+?)(?:\r?\n|$)', content)
            if reason_match:
                metadata["reason"] = reason_match.group(1).strip()
            
            # 提取来源
            source_match = re.search(r'\*\*来源\*\*:\s*(.+?)(?:\r?\n|$)', content)
            if source_match:
                metadata["source"] = source_match.group(1).strip()
            
            # 提取日期
            date_match = re.search(r'\*\*日期\*\*:\s*(.+?)(?:\r?\n|$)', content)
            if date_match:
                metadata["date"] = date_match.group(1).strip()
            
            # 提取事件分类
            category_match = re.search(r'\*\*事件分类\*\*:\s*(.+?)(?:\r?\n|$)', content)
            if category_match:
                metadata["category"] = category_match.group(1).strip()
            
            # 提取所属领域
            domain_match = re.search(r'\*\*所属领域\*\*:\s*(.+?)(?:\r?\n|$)', content)
            if domain_match:
                metadata["domain"] = domain_match.group(1).strip()
                
    except Exception as e:
        metadata["error"] = str(e)
    
    return metadata


def scan_pending_directory(pending_dir: str) -> dict:
    """
    扫描 pending 目录，提取所有 MD 文件的元数据
    
    返回:
        dict: 包含 summary（统计）和 files（文件列表）
    """
    pending_path = Path(pending_dir)
    
    if not pending_path.exists():
        return {"error": f"目录不存在: {pending_dir}"}
    
    if not pending_path.is_dir():
        return {"error": f"不是目录: {pending_dir}"}
    
    # 扫描所有 .md 文件
    md_files = list(pending_path.glob("*.md"))
    
    result = {
        "directory": str(pending_path.absolute()),
        "summary": {
            "total": len(md_files),
            "by_score": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        },
        "files": []
    }
    
    for md_file in md_files:
        metadata = extract_metadata(str(md_file))
        result["files"].append(metadata)
        
        # 统计评分分布
        score = metadata.get("score", 0)
        if score in result["summary"]["by_score"]:
            result["summary"]["by_score"][score] += 1
    
    # 按评分排序（低分优先，便于快速处理）
    result["files"].sort(key=lambda x: (x.get("score", 0), x.get("title", "")))
    
    return result


def main():
    if len(sys.argv) < 2:
        print("用法: python scan_pending.py <pending_directory>")
        print("示例: python scan_pending.py data/大模型技术和产品_20260204_100000/pending")
        sys.exit(1)
    
    pending_dir = sys.argv[1]
    result = scan_pending_directory(pending_dir)
    
    # 输出 JSON
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
