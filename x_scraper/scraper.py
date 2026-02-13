"""
scraper.py - X/Twitter 用户推文爬取编排器

面向用户的高层 API，整合 XClient、AccountPool 和配置管理。
支持：
- 独立运行 (CLI 模式)
- 集成到 Pipeline (作为 FetcherStage 的数据源)
"""
import os
import sys
import json
import time
import random
import logging
import configparser
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple, Any

from .client import XClient
from .account_pool import AccountPool
from .models import Tweet

logger = logging.getLogger("x_scraper.scraper")


class XScraper:
    """
    X 用户推文爬取器 (High-level API)

    用法:
        # 从 config.ini 创建
        scraper = XScraper.from_config(config)

        # 抓取单个用户
        tweets = scraper.fetch_user_tweets("karpathy", limit=20)

        # 批量抓取配置中的所有用户
        all_posts = scraper.fetch_all_configured_users(days_lookback=7)
    """

    def __init__(
        self,
        account_pool: AccountPool,
        max_tweets_per_user: int = 20,
        request_delay: Tuple[float, float] = (15.0, 25.0),
        user_switch_delay: Tuple[float, float] = (30.0, 60.0),
        request_timeout: int = 30,
        max_retries: int = 3,
        include_retweets: bool = False,
        include_replies: bool = False,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: int = 60,
        query_ids: Optional[Dict[str, str]] = None,
        features: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化 X 爬取器。

        Args:
            account_pool: 账号池实例
            max_tweets_per_user: 每个用户抓取的推文上限
            request_delay: 请求间延迟范围 (秒)
            user_switch_delay: 用户切换间延迟范围 (秒)
            request_timeout: 请求超时 (秒)
            max_retries: 最大重试次数
            include_retweets: 是否包含转推
            include_replies: 是否包含回复
            circuit_breaker_threshold: 断路器阈值 (连续失败次数)
            circuit_breaker_cooldown: 断路器冷却时间 (秒)
            query_ids: 自定义 GraphQL Query IDs
            features: 自定义 GraphQL Features
        """
        self.account_pool = account_pool
        self.max_tweets_per_user = max_tweets_per_user
        self.request_delay = request_delay
        self.user_switch_delay = user_switch_delay
        self.include_retweets = include_retweets
        self.include_replies = include_replies

        self.client = XClient(
            account_pool=account_pool,
            timeout=request_timeout,
            max_retries=max_retries,
            circuit_breaker_threshold=circuit_breaker_threshold,
            circuit_breaker_cooldown=circuit_breaker_cooldown,
            query_ids=query_ids,
            features=features,
        )

    @classmethod
    def from_config(cls, config: configparser.ConfigParser) -> 'XScraper':
        """
        从 config.ini 配置创建 XScraper 实例。

        读取 [x_scraper] 节的配置参数。
        优先从 [x_scraper] auth_credentials 读取凭证，
        如找不到则尝试从 rsshub-docker.env 中读取。

        Args:
            config: ConfigParser 实例

        Returns:
            XScraper 实例
        """
        # ─── 加载账号凭证 ───
        auth_str = config.get('x_scraper', 'auth_credentials', fallback='').strip()

        if auth_str:
            pool = AccountPool.from_config_string(auth_str)
        else:
            # 回退: 尝试从 rsshub-docker.env 加载
            project_root = _find_project_root()
            env_files = [
                os.path.join(project_root, "rsshub-docker.env"),
            ]
            pool = None
            for env_file in env_files:
                if os.path.exists(env_file):
                    try:
                        pool = AccountPool.from_env_file(env_file)
                        logger.info(f"从 {os.path.basename(env_file)} 加载凭证")
                        break
                    except Exception as e:
                        logger.warning(f"加载 {env_file} 失败: {e}")

            if pool is None:
                raise ValueError(
                    "未找到 X 账号凭证。请在 config.ini [x_scraper] 中配置 auth_credentials，"
                    "或确保 rsshub-docker.env 文件存在。"
                )

        # ─── 读取其他配置 ───
        # P2: 加载可配置的 Query IDs 和 Features (覆盖代码中的默认值)
        query_ids = None
        features = None
        query_ids_str = config.get('x_scraper', 'query_ids', fallback='').strip()
        features_str = config.get('x_scraper', 'features', fallback='').strip()
        if query_ids_str:
            try:
                query_ids = json.loads(query_ids_str)
                logger.info(f"从配置加载自定义 Query IDs: {list(query_ids.keys())}")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 query_ids 配置失败: {e}，使用默认值")
        if features_str:
            try:
                features = json.loads(features_str)
                logger.info(f"从配置加载自定义 Features ({len(features)} 个)")
            except json.JSONDecodeError as e:
                logger.warning(f"解析 features 配置失败: {e}，使用默认值")

        return cls(
            account_pool=pool,
            max_tweets_per_user=config.getint('x_scraper', 'max_tweets_per_user', fallback=20),
            request_delay=(
                config.getfloat('x_scraper', 'request_delay_min', fallback=15.0),
                config.getfloat('x_scraper', 'request_delay_max', fallback=25.0),
            ),
            user_switch_delay=(
                config.getfloat('x_scraper', 'user_switch_delay_min', fallback=30.0),
                config.getfloat('x_scraper', 'user_switch_delay_max', fallback=60.0),
            ),
            request_timeout=config.getint('x_scraper', 'request_timeout', fallback=30),
            max_retries=config.getint('x_scraper', 'max_retries', fallback=3),
            include_retweets=config.getboolean('x_scraper', 'include_retweets', fallback=False),
            include_replies=config.getboolean('x_scraper', 'include_replies', fallback=False),
            # P1 & P2: 新增参数
            circuit_breaker_threshold=config.getint('x_scraper', 'circuit_breaker_threshold', fallback=5),
            circuit_breaker_cooldown=config.getint('x_scraper', 'circuit_breaker_cooldown', fallback=60),
            query_ids=query_ids,
            features=features,
        )

    # ─── 核心 API ───

    def fetch_user_tweets(
        self,
        username: str,
        limit: Optional[int] = None,
        days_lookback: Optional[int] = None,
    ) -> List[Tweet]:
        """
        抓取单个用户的推文。

        Args:
            username: X 用户名 (不含 @)
            limit: 推文数量上限 (默认使用配置值)
            days_lookback: 回溯天数 (默认不限)

        Returns:
            Tweet 对象列表
        """
        if limit is None:
            limit = self.max_tweets_per_user

        # 1. 获取 user_id
        logger.info(f"🔄 [X Scraper] 获取用户 @{username} 的 ID...")
        user_id = self.client.get_user_id(username)
        if not user_id:
            logger.warning(f"无法获取用户 @{username} 的 ID，跳过")
            return []

        # 2. 计算日期截止
        since_date = None
        if days_lookback:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_lookback)
            since_date = cutoff.strftime("%Y-%m-%d")

        # 3. 获取推文
        logger.info(f"🔄 [X Scraper] 抓取 @{username} 的推文 (limit={limit}, since={since_date})...")
        tweets = self.client.get_user_tweets_all(
            user_id=user_id,
            limit=limit,
            since_date=since_date,
            include_replies=self.include_replies,
            include_retweets=self.include_retweets,
            page_delay=self.request_delay,
        )

        logger.info(f"✅ [X Scraper] @{username}: 获取到 {len(tweets)} 条推文")
        return tweets

    def fetch_user_tweets_as_posts(
        self,
        username: str,
        source_name: str,
        limit: Optional[int] = None,
        days_lookback: Optional[int] = None,
    ) -> List[dict]:
        """
        抓取推文并转换为 Pipeline 兼容的 post dict 列表。

        这是集成到 Pipeline FetcherStage 的主要入口。

        Args:
            username: X 用户名
            source_name: 源名称 (如 "X_OpenAI")
            limit: 推文上限
            days_lookback: 回溯天数

        Returns:
            Pipeline 兼容的 post dict 列表
        """
        tweets = self.fetch_user_tweets(username, limit, days_lookback)
        return [tweet.to_post_dict(source_name) for tweet in tweets]

    def fetch_all_configured_users(
        self,
        x_accounts: Dict[str, str],
        days_lookback: int = 7,
    ) -> Dict[str, List[dict]]:
        """
        批量抓取配置中的所有 X 用户。

        Args:
            x_accounts: {source_name: username} 字典 (来自 config.ini [x_accounts])
            days_lookback: 回溯天数

        Returns:
            {source_name: [post_dict, ...]} 字典
        """
        results = {}
        total = len(x_accounts)
        logger.info(f"━━━ X Scraper: 开始批量抓取 {total} 个用户 ━━━")

        for i, (source_name, username) in enumerate(x_accounts.items(), 1):
            logger.info(f"[{i}/{total}] 处理 {source_name} (@{username})...")

            try:
                posts = self.fetch_user_tweets_as_posts(
                    username=username,
                    source_name=source_name,
                    days_lookback=days_lookback,
                )
                results[source_name] = posts

            except Exception as e:
                logger.error(f"抓取 @{username} 失败: {e}")
                results[source_name] = []

            # 用户间延迟 (最后一个用户不需要)
            if i < total:
                delay = random.uniform(*self.user_switch_delay)
                logger.info(f"⏳ 用户切换延迟 {delay:.1f}s...")
                time.sleep(delay)

        # 统计
        total_posts = sum(len(v) for v in results.values())
        success_count = sum(1 for v in results.values() if v)
        logger.info(
            f"━━━ X Scraper 完成: {success_count}/{total} 个用户成功, "
            f"共 {total_posts} 条推文 ━━━"
        )

        return results


# ─── 辅助函数 ───

def _find_project_root() -> str:
    """查找项目根目录 (包含 config.ini 的目录)"""
    # 从当前文件向上查找
    current = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):  # 最多向上 5 层
        if os.path.exists(os.path.join(current, "config.ini")):
            return current
        current = os.path.dirname(current)
    # 回退到当前工作目录
    return os.getcwd()


def _load_config() -> configparser.ConfigParser:
    """加载 config.ini"""
    config = configparser.ConfigParser()
    config.optionxform = str  # 保持 key 大小写
    project_root = _find_project_root()
    config_path = os.path.join(project_root, "config.ini")
    config.read(config_path, encoding='utf-8')
    return config


def _load_x_accounts(config: configparser.ConfigParser) -> Dict[str, str]:
    """从 config.ini 加载 X 账号列表"""
    accounts = {}
    if config.has_section('x_accounts'):
        for name in config.options('x_accounts'):
            username = config.get('x_accounts', name).strip()
            if username:
                accounts[name] = username
    return accounts


# ─── CLI 入口 ───

def main():
    """
    独立运行入口。

    读取 config.ini 中的 [x_accounts] 和 [x_scraper] 配置，
    抓取所有用户的推文并保存到 data/ 目录。
    """
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    # 加载配置
    config = _load_config()
    x_accounts = _load_x_accounts(config)

    if not x_accounts:
        logger.error("config.ini 中未找到 [x_accounts] 配置")
        sys.exit(1)

    logger.info(f"加载了 {len(x_accounts)} 个 X 账号")

    # 创建 scraper
    try:
        scraper = XScraper.from_config(config)
    except ValueError as e:
        logger.error(f"初始化失败: {e}")
        sys.exit(1)

    # 获取回溯天数
    days_lookback = config.getint('crawler', 'days_lookback', fallback=7)

    # 执行抓取
    results = scraper.fetch_all_configured_users(x_accounts, days_lookback=days_lookback)

    # 保存结果
    batch_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    project_root = _find_project_root()
    output_dir = os.path.join(project_root, 'data', f'x_scraper_{batch_ts}')
    os.makedirs(output_dir, exist_ok=True)

    for source_name, posts in results.items():
        if posts:
            filepath = os.path.join(output_dir, f"{source_name}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(posts, f, ensure_ascii=False, indent=2)

    total_posts = sum(len(v) for v in results.values())
    logger.info(f"结果已保存到: {output_dir} (共 {total_posts} 条推文)")


if __name__ == "__main__":
    main()
