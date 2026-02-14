#!/usr/bin/env python
"""
运行 X Scraper 的入口脚本。
直接在根目录执行: python run_x_scraper.py
"""
import sys
import os

# 确保当前目录在 path 中 (防止有些环境没加)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from x_scraper.scraper import main

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n(用户中断执行)")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n(错误: {e})")
        sys.exit(1)
