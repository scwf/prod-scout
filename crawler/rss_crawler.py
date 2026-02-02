"""
rss_crawler.py - RSS 订阅抓取工具

功能：
- 从 RSSHub 等源抓取最新更新（如 Twitter, YouTube, 博客）
- 调用 LLM 对抓取内容进行结构化整理

依赖：feedparser, openai, python-dateutil
"""
import os
import json
import time
import configparser
import feedparser
from datetime import datetime, timezone
from dateutil import parser as date_parser
from common import organize_data, posts_to_markdown_table, group_posts_by_domain, save_batch_manifest, DAYS_LOOKBACK, setup_logger

logger = setup_logger("rss_crawler")
from content_fetcher import ContentFetcher

# ================= 配置加载 =================
# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.optionxform = str  # 保留 key 的大小写
config.read(os.path.join(os.path.dirname(__file__), '..', 'config-test.ini'), encoding='utf-8')

def load_weixin_accounts_from_config():
    """
    从配置文件加载微信公众号列表
    
    配置格式：显示名称 = RSS地址
    
    返回：
        dict: {显示名称: RSS地址}
    """
    weixin_accounts = {}
    
    if config.has_section('weixin_accounts'):
        for display_name in config.options('weixin_accounts'):
            rss_url = config.get('weixin_accounts', display_name).strip()
            if rss_url:
                weixin_accounts[display_name] = rss_url
    
    return weixin_accounts

def load_x_accounts_from_config():
    """
    从配置文件加载 X (Twitter) 账户列表
    
    配置格式：显示名称 = 账户ID
    
    返回：
        dict: {显示名称: RSS地址}
    """
    x_accounts = {}
    rsshub_base_url = config.get('rsshub', 'base_url', fallback='http://127.0.0.1:1200')
    
    if config.has_section('x_accounts'):
        for display_name in config.options('x_accounts'):
            account_id = config.get('x_accounts', display_name).strip()
            if account_id:
                x_accounts[display_name] = f"{rsshub_base_url}/twitter/user/{account_id}"
    
    return x_accounts

def load_youtube_channels_from_config():
    """
    从配置文件加载 YouTube 频道列表
    
    配置格式：显示名称 = 频道ID (以UC开头)
    
    返回：
        dict: {显示名称: RSS地址}
    """
    youtube_channels = {}
    
    if config.has_section('youtube_channels'):
        for display_name in config.options('youtube_channels'):
            channel_id = config.get('youtube_channels', display_name).strip()
            if channel_id:
                youtube_channels[display_name] = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    
    return youtube_channels

# ================= 配置区域 =================
# 设置 RSSHub 的订阅源 (按来源类型分组)
# 提示：X (Twitter) 和 YouTube 的路由可以在 https://docs.rsshub.app/ 找到
rss_sources = {
    "weixin": load_weixin_accounts_from_config(),  # 从配置文件读取微信公众号
    "X": load_x_accounts_from_config(),  # 从配置文件读取 X 账户
    "YouTube": load_youtube_channels_from_config(),  # 从配置文件读取 YouTube 频道
    "blog": {
        # "36Kr_News": "https://rsshub.app/36kr/newsflashes",
        # "OpenAI_Blog": "https://rsshub.app/openai/blog",
    },
}

# ================= 内容增强模块 =================
# 用于从X推文中提取嵌入链接内容，以及从YouTube视频中提取字幕
content_fetcher = ContentFetcher()
# ===========================================


# ================= 辅助函数 =================

def _parse_date(entry):
    """解析并标准化时间"""
    if not hasattr(entry, 'published'): return None
    dt = date_parser.parse(entry.published)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _enrich_x_content(content, title):
    """提取 X 推文的嵌入内容"""
    try:
        embedded, extra_urls = content_fetcher.fetch_embedded_content(content, title=title)
        extra_content = ""
        if embedded:
            parts = [f"[{'博客' if i.content_type == 'blog' else '视频字幕'}] {i.content}" 
                     for i in embedded if i.content]
            extra_content = "\n\n".join(parts)
        
        if embedded or extra_urls:
            t = (title or "无标题")
            t = t[:30] + "..." if len(t) > 30 else t
            logger.info(f"[{t}] 嵌入: {len(embedded)}, 外链: {len(extra_urls)}")
        return extra_content, extra_urls
    except Exception as e:
        logger.info(f"X内容提取失败: {e}")
        return "", []

def _enrich_youtube_content(link, title, context=""):
    """提取 YouTube 字幕
    
    参数:
        link: 视频链接
        title: 视频标题
        context: 上下文（通常是RSS摘要/描述）
    """
    try:
        # 传递 title 和 context 到 fetch，context 用作补充信息
        full_context = f"{title}\n{context}" if context else title
        # 使用 content_fetcher.video_fetcher
        yt = content_fetcher.video_fetcher.fetch(link, context=full_context, title=title)
        if yt and yt.content:
            logger.info(f"提取到字幕: {len(yt.content)} 字符")
            return yt.content
    except Exception as e:
        logger.info(f"字幕提取失败: {e}")
    return ""

def _save_raw_backup(posts, source_type, name):
    """保存原始数据备份"""
    if not posts: return
    try:
        raw_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
        os.makedirs(raw_dir, exist_ok=True)
        safe_name = "".join(c if c.isalnum() or c in '-_' else '_' for c in name)
        filename = f"{source_type}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(os.path.join(raw_dir, filename), 'w', encoding='utf-8') as f:
            json.dump(posts, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.info(f"备份失败: {e}")


def fetch_recent_posts(rss_url, days, source_type="未知", name="", save_raw=True):
    """
    抓取 RSS 并筛选指定天数内的内容
    
    参数：
        rss_url: RSS 源地址
        days: 抓取最近多少天的内容
        source_type: 来源类型（微信公众号、X (Twitter)、YouTube、博客/新闻等）
        name: 源名称
        save_raw: 是否保存原始数据为 JSON 备份文件
    """
    logger.info(f"正在抓取 [{source_type}] {name}: {rss_url} ...")
    try:
        feed = feedparser.parse(rss_url)
        
        # 检查 RSS 解析是否出错
        if feed.bozo and not feed.entries:
            logger.info(f"RSS 解析失败: {feed.bozo_exception}")
            return []
        
        recent_posts = []
        
        # 获取当前时间 (带时区感知，默认为 UTC 以便比较)
        now = datetime.now(timezone.utc)
        
        for entry in feed.entries:
            # 1. 时间检查
            post_date = _parse_date(entry)
            if not post_date or (now - post_date).days > days:
                continue

            # 2. 基础内容提取
            content = entry.get('content', '') or entry.get('description', '')
            extra_content, extra_urls = '', []

            logger.info(f"标题: {entry.title}")

            # 3. 内容增强 (X/YouTube)
            if source_type == "X":
                extra_content, extra_urls = _enrich_x_content(content, entry.title)
            elif source_type == "YouTube":
                extra_content = _enrich_youtube_content(entry.link, entry.title, content)

            recent_posts.append({
                "title": entry.title,
                "date": post_date.strftime("%Y-%m-%d"),
                "link": entry.link,
                "rss_url": rss_url,
                "source_type": source_type,
                "content": content,
                "extra_content": extra_content,
                "extra_urls": extra_urls
            })
        
        # 保存备份
        if save_raw:
            _save_raw_backup(recent_posts, source_type, name)
                
        return recent_posts
    except Exception as e:
        logger.info(f"抓取失败: {e}")
        return []


# ================= 主程序入口 =================
if __name__ == "__main__":
    start_time = time.time()
    
    # 收集所有整理后的文章
    all_organized_posts = []
    
    for category, sources in rss_sources.items():
        if not sources:  # 跳过空分类
            continue
        
        logger.info(f"📂 处理分类: {category}")
        
        for name, url in sources.items():
            posts = fetch_recent_posts(url, DAYS_LOOKBACK, source_type=category, name=name)
            logger.info(f"-> 发现 {len(posts)} 条相关内容，使用LLM进行整理...")
            
            # organize_data 现在返回 list[dict]
            organized_posts = organize_data(posts, name)
            all_organized_posts.extend(organized_posts)
            
            logger.info(f"-> 整理完成，有效内容 {len(organized_posts)} 条")
    
    # 按领域分组
    logger.info(f"\n📊 整理完，共 {len(all_organized_posts)} 条有效内容，按领域分组...")
    grouped_posts = group_posts_by_domain(all_organized_posts)
    
    # 准备输出目录
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    saved_files = []
    domain_report_dirs = {}  # 用于清单: {领域名称: 文件夹名}
    
    # 为每个领域生成单独的文件夹
    for domain, posts in grouped_posts.items():
        if not posts:
            continue
        
        # 生成安全的领域名
        safe_domain = "".join(c if c.isalnum() or c in ('-', '_', '（', '）') else '_' for c in domain)
        domain_dir_name = f"{safe_domain}_{timestamp}"
        domain_dir_path = os.path.join(output_dir, domain_dir_name)
        os.makedirs(domain_dir_path, exist_ok=True)
        
        files_count = 0
        for post in posts:
            # 获取必要信息
            event = post.get('event', '未命名事件')
            date_str = post.get('date', '未知日期')
            
            # 生成安全的文件名
            safe_event = "".join(c if c.isalnum() or c in ('-', '_', '（', '）') else '_' for c in event)
            # 截断过长的文件名
            if len(safe_event) > 50:
                safe_event = safe_event[:50]
                
            post_filename = f"{safe_event}_{date_str}.md"
            post_path = os.path.join(domain_dir_path, post_filename)
            
            # 生成 Markdown 内容
            md_content = f"# {event}\n\n"
            md_content += f"- **日期**: {date_str}\n"
            md_content += f"- **事件分类**: {post.get('category', '未分类')}\n"
            md_content += f"- **所属领域**: {domain}\n"
            md_content += f"- **来源**: {post.get('source_name', '未知')}\n"
            md_content += f"- **原文链接**: {post.get('link', '')}\n\n"
            
            md_content += "## 关键信息\n"
            md_content += f"{post.get('key_info', '')}\n\n"
            
            md_content += "## 详细内容\n"
            md_content += f"{post.get('detail', '')}\n\n"
            
            if post.get('extra_content'):
                md_content += "## 补充内容\n"
                md_content += f"{post.get('extra_content', '')}\n\n"
                
            if post.get('extra_urls'):
                md_content += "## 外部链接\n"
                for url in post.get('extra_urls', []):
                    md_content += f"- {url}\n"
                md_content += "\n"
            
            # 写入文件
            with open(post_path, 'w', encoding='utf-8') as f:
                f.write(md_content)
            
            files_count += 1
            
        saved_files.append((domain, domain_dir_path, files_count))
        domain_report_dirs[domain] = domain_dir_name
        logger.info(f"✅ 领域 [{domain}] 已保存 {files_count} 个文件到目录: {domain_dir_name}")
    
    # 保存批次清单文件
    save_batch_manifest(
        output_dir=output_dir,
        batch_id=timestamp,
        domain_reports=domain_report_dirs,
        stats={
            "total_posts": len(all_organized_posts),
            "domain_count": len(domain_report_dirs)
        }
    )
    
    # 打印执行结果摘要
    print("\n" + "="*50)
    print("📊 执行结果摘要")
    print("="*50)
    print(f"总共处理: {len(all_organized_posts)} 条有效内容")
    print(f"领域分布:")
    for domain, path, count in saved_files:
        print(f"  - {domain}: {count} 条")
    print(f"\n生成文件:")
    for domain, path, count in saved_files:
        print(f"  - {os.path.basename(path)}")
    
    # 打印时间开销
    elapsed_time = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ 执行完成，总耗时: {elapsed_time:.2f} 秒")
    print("="*50)
