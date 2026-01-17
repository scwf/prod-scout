"""
rss_crawler.py - RSS 订阅抓取工具

功能：
- 从 RSSHub 等源抓取最新更新（如 Twitter, YouTube, 博客）
- 调用 LLM 对抓取内容进行结构化整理

依赖：feedparser, openai, python-dateutil
"""
import feedparser
from datetime import datetime, timezone
from dateutil import parser as date_parser
from common import organize_data, DAYS_LOOKBACK

# ================= 配置区域 =================
# 设置 RSSHub 的订阅源 (按来源类型分组)
# 提示：X (Twitter) 和 YouTube 的路由可以在 https://docs.rsshub.app/ 找到
rss_sources = {
    "weixin": {
        "腾讯技术工程": "https://wechat2rss.xlab.app/feed/9685937b45fe9c7a526dbc32e4f24ba879a65b9a.xml",
    },
    "X": {
        # 注意：X 可能需要自建 RSSHub 服务或配置 Cookie 才能稳定抓取
        "databricks": "http://127.0.0.1:1200/twitter/user/databricks",
        "andrejkarpathy": "http://127.0.0.1:1200/twitter/user/karpathy",
    },
    "YouTube": {
        # "GoogleAI": "https://rsshub.app/youtube/channel/xxx",
    },
    "blog": {
        # "36Kr_News": "https://rsshub.app/36kr/newsflashes",
        # "OpenAI_Blog": "https://rsshub.app/openai/blog",
    },
}
# ===========================================


def fetch_recent_posts(rss_url, days, source_type="未知"):
    """
    抓取 RSS 并筛选指定天数内的内容
    
    参数：
        rss_url: RSS 源地址
        days: 抓取最近多少天的内容
        source_type: 来源类型（微信公众号、X (Twitter)、YouTube、博客/新闻等）
    """
    print(f"正在抓取 [{source_type}]: {rss_url} ...")
    try:
        feed = feedparser.parse(rss_url)
        recent_posts = []
        
        # 获取当前时间 (带时区感知，默认为 UTC 以便比较)
        now = datetime.now(timezone.utc)
        
        for entry in feed.entries:
            # 解析发布时间
            if hasattr(entry, 'published'):
                post_date = date_parser.parse(entry.published)
            else:
                print(f"没有时间戳: {entry}")
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
                
        return recent_posts
    except Exception as e:
        print(f"抓取失败: {e}")
        return []


# ================= 主程序入口 =================
if __name__ == "__main__":
    final_report = "# 🌍 RSS 情报周报 (Automated)\n\n"
    
    for category, sources in rss_sources.items():
        if not sources:  # 跳过空分类
            continue
        
        final_report += f"## 📂 {category}\n\n"
        
        for name, url in sources.items():
            posts = fetch_recent_posts(url, DAYS_LOOKBACK, source_type=category)
            print(f" -> 发现 {len(posts)} 条相关内容，正在整理...")
            
            organized_content = organize_data(posts, name)
            
            final_report += f"### {name}\n{organized_content}\n\n"
        
        final_report += "---\n\n"
    
    # 保存报告为 Markdown 文件
    import os
    output_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(output_dir, exist_ok=True)
    
    report_filename = f"rss_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = os.path.join(output_dir, report_filename)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(final_report)
    
    print(f"\n报告已保存至: {report_path}")
    
    # 打印最终报告
    print("\n" + "="*30 + " 最终报告 " + "="*30 + "\n")
    print(final_report)
