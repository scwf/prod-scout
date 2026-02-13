"""
x_scraper - X/Twitter 用户推文直接爬取模块

提供基于 X 内部 GraphQL API 的推文抓取能力，无需依赖 RSSHub。

核心组件:
- XScraper: 高层爬取编排器（推荐使用）
- XClient: 底层 GraphQL API 客户端
- AccountPool: 账号凭证池管理
- Tweet / TweetMedia: 数据模型

快速开始:
    from x_scraper import XScraper

    # 方式 1: 从 config.ini 创建
    import configparser
    config = configparser.ConfigParser()
    config.read("config.ini")
    scraper = XScraper.from_config(config)

    # 方式 2: 手动创建
    from x_scraper import AccountPool
    pool = AccountPool.from_env_file("rsshub-docker.env")
    scraper = XScraper(account_pool=pool)

    # 抓取推文
    tweets = scraper.fetch_user_tweets("karpathy", limit=20)
    for tweet in tweets:
        print(tweet)

    # 转换为 Pipeline 兼容格式
    posts = scraper.fetch_user_tweets_as_posts("karpathy", "X_karpathy")
"""

from .models import Tweet, TweetMedia
from .account_pool import AccountPool
from .client import XClient
from .scraper import XScraper

__all__ = [
    "XScraper",
    "XClient",
    "AccountPool",
    "Tweet",
    "TweetMedia",
]
