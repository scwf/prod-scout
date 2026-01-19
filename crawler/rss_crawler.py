"""
rss_crawler.py - RSS 订阅抓取工具

功能：
- 从 RSSHub 等源抓取最新更新（如 Twitter, YouTube, 博客）
- 调用 LLM 对抓取内容进行结构化整理

依赖：feedparser, openai, python-dateutil
"""
import os
import json
import configparser
import feedparser
from datetime import datetime, timezone
from dateutil import parser as date_parser
from common import organize_data, DAYS_LOOKBACK, log

# ================= 配置加载 =================
# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.optionxform = str  # 保留 key 的大小写
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'), encoding='utf-8')

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
# ===========================================


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
    log(f"正在抓取 [{source_type}] {name}: {rss_url} ...")
    try:
        feed = feedparser.parse(rss_url)
        
        # 检查 RSS 解析是否出错
        if feed.bozo and not feed.entries:
            log(f"RSS 解析失败: {feed.bozo_exception}")
            return []
        
        recent_posts = []
        
        # 获取当前时间 (带时区感知，默认为 UTC 以便比较)
        now = datetime.now(timezone.utc)
        
        for entry in feed.entries:
            # 解析发布时间
            if hasattr(entry, 'published'):
                post_date = date_parser.parse(entry.published)
            else:
                log(f"没有时间戳: {entry}")
                continue # 没有时间戳跳过

            # 确保 post_date 有时区信息，如果没有则设为 UTC
            if post_date.tzinfo is None:
                post_date = post_date.replace(tzinfo=timezone.utc)
            
            # 计算时间差
            if (now - post_date).days <= days:
                # 清洗数据，提取标题、链接和摘要
                content = entry.get('content', '') or entry.get('description', '')
                
                recent_posts.append({
                    "title": entry.title,
                    "date": post_date.strftime("%Y-%m-%d"),
                    "link": entry.link,
                    "rss_url": rss_url,
                    "source_type": source_type,  # 来源类型
                    "content": content  # 保留原始内容
                })
        
        # 保存原始数据为 JSON 备份（用于回溯和问题定位）
        if save_raw and recent_posts:
            raw_dir = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
            os.makedirs(raw_dir, exist_ok=True)
            # 使用安全的文件名：source_type + name + 时间戳
            safe_name = "".join(c if c.isalnum() or c in ('-', '_') else '_' for c in name)
            raw_filename = f"{source_type}_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            raw_path = os.path.join(raw_dir, raw_filename)
            with open(raw_path, 'w', encoding='utf-8') as f:
                json.dump(recent_posts, f, ensure_ascii=False, indent=2)
                
        return recent_posts
    except Exception as e:
        log(f"抓取失败: {e}")
        return []


# ================= 主程序入口 =================
if __name__ == "__main__":
    final_report = "# 🌍 Data&AI 情报周报 (Automated RSS Crawler)\n\n"
    
    for category, sources in rss_sources.items():
        if not sources:  # 跳过空分类
            continue
        
        final_report += f"## 📂 {category}\n\n"
        
        for name, url in sources.items():
            posts = fetch_recent_posts(url, DAYS_LOOKBACK, source_type=category, name=name)
            log(f" -> 发现 {len(posts)} 条相关内容，正在整理...")
            
            organized_content = organize_data(posts, name)
            
            final_report += f"### {name}\n{organized_content}\n\n"
        
        final_report += "---\n\n"
    
    # 保存报告为 Markdown 文件
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)
    
    report_filename = f"rss_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(output_dir, report_filename)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(final_report)
    
    log(f"报告已保存至: {report_path}")
    
    # 打印最终报告
    print("\n" + "="*30 + " 最终报告 " + "="*30 + "\n")
    print(final_report)
