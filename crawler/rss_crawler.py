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
from concurrent.futures import ThreadPoolExecutor, as_completed
from common import organize_single_post, group_posts_by_domain, save_batch_manifest, DAYS_LOOKBACK, setup_logger

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
}

# ================= 内容增强模块 =================
# 用于从X推文中提取嵌入链接内容，以及从YouTube视频中提取字幕
content_fetcher = ContentFetcher()
# ===========================================


def generate_post_markdown(post, domain):
    """生成单篇文章的 Markdown 内容"""
    lines = [
        f"# {post.get('event', '未命名事件')}",
        "",
        f"- **日期**: {post.get('date', '未知日期')}",
        f"- **事件分类**: {post.get('category', '未分类')}",
        f"- **所属领域**: {domain}",
        f"- **是否属于洞察范围**: {'✅ 是' if post.get('is_in_scope') else '❌ 否'}",
        f"- **判断理由**: {post.get('scope_reason', '无')}",
        f"- **来源**: {post.get('source_name', '未知')}",
        f"- **原文链接**: {post.get('link', '')}",
        "",
        "## 关键信息",
        post.get('key_info', ''),
        "",
        "## 详细内容",
        post.get('detail', ''),
        "",
    ]
    
    if post.get('extra_content'):
        lines.extend(["​## 补充内容", post['extra_content'], ""])
    
    if post.get('extra_urls'):
        lines.append("## 外部链接")
        lines.extend([f"- {url}" for url in post['extra_urls']])
        lines.append("")
    
    return "\n".join(lines)


# ================= 辅助函数 =================

def _parse_date(entry):
    """解析并标准化时间"""
    if not hasattr(entry, 'published'): return None
    dt = date_parser.parse(entry.published)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt

def _enrich_x_content(content, title):
    """提取 X 推文的嵌入内容"""
    try:
        enable_opt = config.getboolean('llm', 'enable_subtitle_optimization', fallback=False)
        embedded, extra_urls = content_fetcher.fetch_embedded_content(content, title=title, optimize_video=enable_opt)
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
        # 从配置读取是否启用字幕优化
        enable_opt = config.getboolean('llm', 'enable_subtitle_optimization', fallback=False)
        yt = content_fetcher.video_fetcher.fetch(link, context=full_context, title=title, optimize=enable_opt)
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
    MAX_WORKERS = config.getint('crawler', 'organize_workers', fallback=5)
    
    # 准备输出目录
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs(output_dir, exist_ok=True)
    
    # 用于追踪已创建的领域目录 {domain: (dir_path, file_count)}
    domain_dirs = {}
    
    def get_domain_dir(domain):
        """获取领域目录路径，不存在则创建"""
        if domain not in domain_dirs:
            safe_domain = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in domain)
            dir_name = f"{safe_domain}_{timestamp}"
            dir_path = os.path.join(output_dir, dir_name)
            os.makedirs(dir_path, exist_ok=True)
            domain_dirs[domain] = {'path': dir_path, 'name': dir_name, 'count': 0}
        return domain_dirs[domain]
    
    def write_post_file(result):
        """将单篇文章写入对应领域目录"""
        domain = result.get('domain', '其他')
        event = result.get('event', '未命名事件')
        date_str = result.get('date', '未知日期')
        
        domain_info = get_domain_dir(domain)
        
        safe_event = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in event)[:50]
        filename = f"{safe_event}_{date_str}.md"
        filepath = os.path.join(domain_info['path'], filename)
        
        md_content = generate_post_markdown(result, domain)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(md_content)
        
        domain_info['count'] += 1
    
    # 1. 准备源列表
    sources_list = [
        (category, name, url) 
        for category, sources in rss_sources.items()
        for name, url in sources.items()
    ]
    
    logger.info(f"🚀 开始处理 {len(sources_list)} 个订阅源 (顺序抓取 -> 并行整理)...")
    
    all_organized_posts = []
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # 2. 串行抓取所有源
        all_posts = []
        for category, name, url in sources_list:
            posts = fetch_recent_posts(url, DAYS_LOOKBACK, source_type=category, name=name)
            if posts:
                logger.info(f"-> [{name}] 获取 {len(posts)} 条")
                all_posts.extend((post, name) for post in posts)
        
        logger.info(f"共获取 {len(all_posts)} 篇文章，提交并行整理...")
        
        # 3. 并行整理（每篇文章一个任务）
        futures = {
            executor.submit(organize_single_post, post, name): (post, name)
            for post, name in all_posts
        }
        
        # 4. 获取结果 & 即时写入
        completed = 0
        for future in as_completed(futures):
            post, name = futures[future]
            completed += 1
            try:
                result = future.result()
                if result:
                    all_organized_posts.append(result)
                    write_post_file(result)  # 即时写入
            except Exception as e:
                logger.error(f"❌ [{name}] 整理失败: {e}")
            
            if completed % 10 == 0:
                logger.info(f"进度: {completed}/{len(futures)}")
    
    logger.info(f"所有任务执行完成，共获取 {len(all_organized_posts)} 条有效内容")
    
    # 5. 保存批次清单
    domain_report_dirs = {domain: info['name'] for domain, info in domain_dirs.items()}
    save_batch_manifest(
        output_dir=output_dir,
        batch_id=timestamp,
        domain_reports=domain_report_dirs,
        stats={
            "total_posts": len(all_organized_posts),
            "domain_count": len(domain_dirs)
        }
    )
    
    # 打印执行结果摘要
    print("\n" + "="*50)
    print("📊 执行结果摘要")
    print("="*50)
    print(f"总共处理: {len(all_organized_posts)} 条有效内容")
    print(f"领域分布:")
    for domain, info in domain_dirs.items():
        print(f"  - {domain}: {info['count']} 条")
        logger.info(f"✅ 领域 [{domain}] 已保存 {info['count']} 个文件")
    print(f"\n生成目录:")
    for domain, info in domain_dirs.items():
        print(f"  - {info['name']}")
    
    elapsed_time = time.time() - start_time
    print(f"\n{'='*50}")
    print(f"✅ 执行完成，总耗时: {elapsed_time:.2f} 秒")
    print("="*50)
