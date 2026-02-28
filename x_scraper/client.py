"""
client.py - X/Twitter GraphQL API 客户端

封装 X 内部 GraphQL API 的 HTTP 请求逻辑，包括：
- 请求头构造 (Authorization, CSRF, Cookie)
- TLS 指纹伪装 (curl_cffi)
- 速率限制处理与自动重试
- 断路器 (连续失败后暂停请求)
- 用户 ID 查询与推文时间线获取
"""
import json
import time
import random
import logging
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote

from .account_pool import AccountPool, AccountState
from .parser import TweetParser
from .models import Tweet

logger = logging.getLogger("x_scraper.client")

# ─── 常量 ───

# X Web App 固定的 Bearer Token（所有登录用户共享，从前端 JS Bundle 中提取）
# 这是一个公开的 values，所有 X 的 Web 前端使用相同的 Bearer Token
WEB_BEARER_TOKEN = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# GraphQL Query IDs (从浏览器 DevTools 中提取)
# 当 X 更新前端时，这些 ID 可能会变化
# 可通过访问 x.com 并查看 Network tab 中的 GraphQL 请求获取最新值
QUERY_IDS = {
    "UserByScreenName": "xmU6X_CKVnQ5lSrCbAmJsg",
    "UserTweets": "E3opETHurmVJflFsUBVuUQ",
}

# GraphQL Features (必须与浏览器发送的完全一致，否则请求会失败)
# 这些 flags 从浏览器 Network tab 的真实请求中提取
# 如果 X 返回 400 + "features cannot be null"，需要在这里补齐对应字段
DEFAULT_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": False,
    # ─── 以下为 2026 年 X 强制要求的新 feature flags ───
    "highlights_tweets_tab_ui_enabled": True,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "subscriptions_feature_can_gift_premium": True,
}

# 默认 fieldToggles
DEFAULT_FIELD_TOGGLES = {
    "withArticlePlainText": False,
}

# ─── P3: User-Agent + TLS 指纹配置 ───
# 每次请求从同一个 profile 同时选择 UA 和 impersonate，避免两者不一致。
UA_PROFILES = [
    {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "impersonate": "chrome131",
    },
    {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "impersonate": "chrome131",
    },
    {
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "impersonate": "chrome131",
    },
]
# 兼容现有测试/调用方
UA_POOL = [p["user_agent"] for p in UA_PROFILES]


class XClientError(Exception):
    """X Client 基础异常"""
    pass


class RateLimitError(XClientError):
    """速率限制异常"""
    def __init__(self, retry_after: int = 900):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


class AuthError(XClientError):
    """认证异常 (Token 过期/无效)"""
    pass


class XClient:
    """
    X/Twitter GraphQL API 客户端。

    通过模拟浏览器的 GraphQL 请求获取推文数据。
    使用 curl_cffi 确保 TLS 指纹与真实浏览器一致。
    """

    GRAPHQL_BASE = "https://x.com/i/api/graphql"

    def __init__(
        self,
        account_pool: AccountPool,
        timeout: int = 30,
        max_retries: int = 3,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: int = 60,
        query_ids: Optional[Dict[str, str]] = None,
        features: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化 X 客户端。

        Args:
            account_pool: 账号池实例
            timeout: 请求超时时间 (秒)
            max_retries: 最大重试次数
            circuit_breaker_threshold: 断路器阈值 (连续失败次数)
            circuit_breaker_cooldown: 断路器冷却时间 (秒)
            query_ids: 自定义 GraphQL Query IDs (覆盖默认值)
            features: 自定义 GraphQL Features (覆盖默认值)
        """
        self.account_pool = account_pool
        self.timeout = timeout
        self.max_retries = max_retries
        self.parser = TweetParser()

        # P2: 可配置的 Query IDs 和 Features
        self._query_ids = {**QUERY_IDS, **(query_ids or {})}
        self._features = {**DEFAULT_FEATURES, **(features or {})}

        # P1: 断路器状态
        self._cb_threshold = circuit_breaker_threshold
        self._cb_cooldown = circuit_breaker_cooldown
        self._cb_consecutive_failures = 0
        self._cb_open_until = 0.0  # epoch timestamp, 0 = closed

        # 用户名 -> user_id 的缓存
        self._user_id_cache: Dict[str, str] = {}

        # 尝试导入 curl_cffi，如果失败则回退到 requests
        self._session = None
        self._use_curl_cffi = False
        try:
            from curl_cffi import requests as curl_requests
            self._curl_requests = curl_requests
            self._use_curl_cffi = True
            logger.info("使用 curl_cffi (TLS 指纹伪装已启用)")
        except ImportError:
            import requests
            self._requests = requests
            logger.warning(
                "curl_cffi 未安装，回退到 requests (TLS 指纹伪装未启用，可能被风控)。"
                "安装方法: pip install curl_cffi"
            )

    def _pick_client_profile(self) -> Dict[str, str]:
        """选择一个 UA/TLS profile。"""
        return random.choice(UA_PROFILES)

    def _build_headers(self, account: AccountState, user_agent: Optional[str] = None) -> Dict[str, str]:
        """构造请求头 (P3: 每次请求随机选取 UA)"""
        return {
            "authorization": WEB_BEARER_TOKEN,
            "x-csrf-token": account.ct0,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "x-twitter-client-language": "en",
            "content-type": "application/json",
            "user-agent": user_agent or random.choice(UA_POOL),
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "referer": "https://x.com/",
            "origin": "https://x.com",
        }

    def _build_cookies(self, account: AccountState) -> Dict[str, str]:
        """构造 Cookie"""
        return {
            "auth_token": account.auth_token,
            "ct0": account.ct0,
        }

    def _make_request(
        self,
        url: str,
        params: Dict[str, str],
        account: AccountState,
    ) -> Dict[str, Any]:
        """
        发送 HTTP GET 请求并返回 JSON 响应。

        Args:
            url: 请求 URL
            params: 查询参数
            account: 当前使用的账号

        Returns:
            解析后的 JSON dict

        Raises:
            RateLimitError: 429 状态码
            AuthError: 401/403 状态码
            XClientError: 其他错误
        """
        profile = self._pick_client_profile()
        headers = self._build_headers(account, user_agent=profile["user_agent"])
        cookies = self._build_cookies(account)

        try:
            if self._use_curl_cffi:
                response = self._curl_requests.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    impersonate=profile["impersonate"],
                    timeout=self.timeout,
                )
            else:
                response = self._requests.get(
                    url,
                    params=params,
                    headers=headers,
                    cookies=cookies,
                    timeout=self.timeout,
                )

            status = response.status_code

            if status == 200:
                data = response.json()
                # Task 3: 检测 GraphQL 业务错误 (HTTP 200 但返回 errors)
                errors = data.get("errors") or []
                if errors and not data.get("data"):
                    first = errors[0] if isinstance(errors[0], dict) else {}
                    error_code = first.get("code")
                    error_msg = first.get("message", "")
                    error_text = f"{error_msg}".lower()
                    error_msgs = "; ".join(
                        e.get("message", str(e)) if isinstance(e, dict) else str(e)
                        for e in errors[:3]
                    )

                    # GraphQL 业务限流: code=88 或 message 含 rate limit
                    if error_code == 88 or "rate limit" in error_text:
                        raise RateLimitError(900)

                    # GraphQL 业务鉴权失败: 常见 code 或 message 关键字
                    if error_code in (32, 64, 89):
                        raise AuthError(f"GraphQL auth error: {error_msgs}")
                    if any(k in error_text for k in ("unauthorized", "forbidden", "auth")):
                        raise AuthError(f"GraphQL auth error: {error_msgs}")

                    raise XClientError(f"GraphQL error: {error_msgs}")
                return data
            elif status == 429:
                # Task 2: 健壮解析 retry-after
                raw_retry = response.headers.get("retry-after", "")
                try:
                    retry_after = int(raw_retry)
                except (ValueError, TypeError):
                    logger.warning(f"无法解析 retry-after 头: '{raw_retry}'，使用默认 900s")
                    retry_after = 900
                raise RateLimitError(retry_after)
            elif status in (401, 403):
                raise AuthError(f"HTTP {status}: Token 可能已过期或被封")
            else:
                raise XClientError(f"HTTP {status}: {response.text[:200]}")

        except (RateLimitError, AuthError):
            raise
        except Exception as e:
            if "RateLimitError" in str(type(e).__name__) or "AuthError" in str(type(e).__name__):
                raise
            raise XClientError(f"请求失败: {e}")

    def _check_circuit_breaker(self) -> bool:
        """
        P1: 检查断路器状态。

        Returns:
            True = 可以发请求, False = 断路器打开，需要等待
        """
        if self._cb_open_until > 0:
            remaining = self._cb_open_until - time.time()
            if remaining > 0:
                logger.warning(f"⚡ 断路器已打开，等待 {remaining:.0f}s 后重试...")
                time.sleep(min(remaining, self._cb_cooldown))
            # 半开状态: 允许一次试探请求
            self._cb_open_until = 0
            logger.info("⚡ 断路器半开，尝试恢复...")
        return True

    def _record_success(self):
        """P1: 记录请求成功，重置断路器"""
        if self._cb_consecutive_failures > 0:
            logger.info(f"⚡ 断路器恢复 (此前连续失败 {self._cb_consecutive_failures} 次)")
        self._cb_consecutive_failures = 0
        self._cb_open_until = 0

    def _record_failure(self) -> bool:
        """
        P1: 记录请求失败，判断是否触发断路器。

        Returns:
            True = 本次调用触发了断路器
        """
        self._cb_consecutive_failures += 1
        if self._cb_consecutive_failures >= self._cb_threshold:
            self._cb_open_until = time.time() + self._cb_cooldown
            logger.error(
                f"⚡ 断路器触发: 连续失败 {self._cb_consecutive_failures} 次，"
                f"暂停请求 {self._cb_cooldown}s"
            )
            return True
        return False

    def _request_with_retry(
        self,
        url: str,
        params: Dict[str, str],
    ) -> Optional[Dict[str, Any]]:
        """
        带重试、账号轮换和断路器保护的请求。

        Args:
            url: 请求 URL
            params: 查询参数

        Returns:
            JSON 响应 dict，或 None (全部失败)
        """
        # P1: 断路器检查
        self._check_circuit_breaker()

        for attempt in range(self.max_retries):
            account = self.account_pool.get_next()
            if account is None:
                # 尝试等待可用账号
                account = self.account_pool.wait_for_available(timeout=300)
                if account is None:
                    logger.error("无可用账号，请求终止")
                    return None

            try:
                result = self._make_request(url, params, account)
                self._record_success()  # P1: 成功，重置断路器
                return result

            except RateLimitError as e:
                self.account_pool.mark_rate_limited(account, e.retry_after)
                cb_opened = self._record_failure()  # P1
                logger.warning(f"账号 #{account.index} 被限速 (尝试 {attempt+1}/{self.max_retries})")
                if cb_opened:
                    break

            except AuthError as e:
                self.account_pool.mark_dead(account, str(e))
                cb_opened = self._record_failure()  # P1
                logger.error(f"账号 #{account.index} 认证失败: {e}")
                if cb_opened:
                    break

            except XClientError as e:
                cb_opened = self._record_failure()  # P1
                logger.warning(f"请求失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                if cb_opened:
                    break
                if attempt < self.max_retries - 1:
                    wait = (attempt + 1) * 2
                    time.sleep(wait)

        logger.error(f"请求在 {self.max_retries} 次重试后仍然失败")
        return None

    # ─── 公开 API ───

    def get_user_id(self, username: str) -> Optional[str]:
        """
        获取用户的 rest_id (数字 ID)。

        Args:
            username: 用户名 (不含 @)

        Returns:
            User ID 字符串，或 None
        """
        # 检查缓存
        if username in self._user_id_cache:
            return self._user_id_cache[username]

        # P2: 使用可配置的 query_ids 和 features
        query_id = self._query_ids["UserByScreenName"]
        url = f"{self.GRAPHQL_BASE}/{query_id}/UserByScreenName"

        variables = {
            "screen_name": username,
            "withSafetyModeUserFields": True,
        }

        params = {
            "variables": json.dumps(variables, separators=(',', ':')),
            "features": json.dumps(self._features, separators=(',', ':')),
            "fieldToggles": json.dumps(DEFAULT_FIELD_TOGGLES, separators=(',', ':')),
        }

        response = self._request_with_retry(url, params)
        if response is None:
            return None

        user_id = TweetParser.parse_user_id(response)
        if user_id:
            self._user_id_cache[username] = user_id
            logger.debug(f"用户 @{username} -> ID: {user_id}")

        return user_id

    def get_user_tweets(
        self,
        user_id: str,
        count: int = 20,
        cursor: Optional[str] = None,
        include_replies: bool = False,
    ) -> Tuple[List[Tweet], Optional[str]]:
        """
        获取指定用户的推文时间线（单页）。

        Args:
            user_id: 用户 ID (rest_id)
            count: 每页推文数量 (最大 100)
            cursor: 分页游标 (首次请求传 None)
            include_replies: 是否包含回复

        Returns:
            (tweets, next_cursor):
            - tweets: Tweet 对象列表
            - next_cursor: 下一页游标，None 表示没有更多
        """
        # P2: 使用可配置的 query_ids 和 features
        query_id = self._query_ids["UserTweets"]
        url = f"{self.GRAPHQL_BASE}/{query_id}/UserTweets"

        variables = {
            "userId": user_id,
            "count": min(count, 100),
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }

        if cursor:
            variables["cursor"] = cursor

        params = {
            "variables": json.dumps(variables, separators=(',', ':')),
            "features": json.dumps(self._features, separators=(',', ':')),
            "fieldToggles": json.dumps(DEFAULT_FIELD_TOGGLES, separators=(',', ':')),
        }

        response = self._request_with_retry(url, params)
        if response is None:
            return [], None

        tweets, next_cursor = self.parser.parse_timeline(response)

        # 过滤回复 (保留推文串/自回复: 用户回复自己的推文)
        if not include_replies:
            tweets = [
                t for t in tweets
                if t.in_reply_to_id is None  # 非回复
                or t.in_reply_to_username == t.username  # 自回复 (thread)
            ]

        return tweets, next_cursor

    def get_user_tweets_all(
        self,
        user_id: str,
        limit: int = 100,
        since_date: Optional[str] = None,
        include_replies: bool = False,
        include_retweets: bool = False,
        page_delay: Tuple[float, float] = (2.0, 5.0),
    ) -> List[Tweet]:
        """
        获取用户的所有推文 (自动分页)。

        Args:
            user_id: 用户 ID
            limit: 最大推文数量
            since_date: 只获取此日期之后的推文 ("YYYY-MM-DD")
            include_replies: 是否包含回复
            include_retweets: 是否包含转推
            page_delay: 分页请求间的延迟范围 (min, max) 秒

        Returns:
            Tweet 对象列表 (按时间倒序)
        """
        from datetime import datetime, timezone

        all_tweets = []
        cursor = None
        page = 0
        seen_tweet_ids = set()   # 跨页去重，避免置顶/重叠数据反复进入结果
        seen_cursors = set()     # 防止 next_cursor 循环导致重复翻同一页
        duplicate_hit_counts: Dict[str, int] = {}
        empty_add_pages = 0      # 连续 0 新增页计数，用于避免 pinned 等导致长时间不收敛
        max_empty_add_pages = 3
        near_all_old_threshold = 0.9  # 当页过期占比阈值，超过则认为继续翻页收益极低

        # 解析 since_date
        cutoff_date = None
        if since_date:
            try:
                cutoff_date = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"无效的日期格式: {since_date}，忽略日期过滤")

        while len(all_tweets) < limit:
            page += 1
            # 每页上限 20, 不要设太高避免触发异常检测
            per_page = min(20, limit - len(all_tweets))
            request_cursor = cursor

            tweets, next_cursor = self.get_user_tweets(
                user_id,
                count=per_page,
                cursor=cursor,
                include_replies=include_replies,
            )

            if not tweets:
                logger.info(
                    f"[X Scraper][Page {page}] cursor={request_cursor or '<start>'} "
                    "返回 0 条，停止分页"
                )
                break

            # 日期过滤 & 业务过滤 (转推/回复)
            # 重要: 分页终止判断只看日期，不受转推/回复过滤影响
            # 否则一个全是转推的页面会被误判为"整页过旧"而提前终止
            page_has_new_enough = False  # 本页是否有日期范围内的推文 (不论是否被业务过滤)
            raw_count = len(tweets)
            skipped_old = 0
            skipped_retweet = 0
            skipped_duplicate = 0
            added_count = 0
            duplicate_sample_id = ""
            for tweet in tweets:
                # 先做日期判断 (影响分页终止)
                tweet_in_date_range = True
                if cutoff_date and tweet.created_at:
                    if tweet.created_at < cutoff_date:
                        tweet_in_date_range = False
                
                if tweet_in_date_range:
                    page_has_new_enough = True

                # 再做业务过滤 (只影响是否加入结果，不影响分页终止)
                if not tweet_in_date_range:
                    skipped_old += 1
                    continue
                if not include_retweets and tweet.is_retweet:
                    skipped_retweet += 1
                    continue
                if tweet.id in seen_tweet_ids:
                    skipped_duplicate += 1
                    if tweet.id:
                        duplicate_hit_counts[tweet.id] = duplicate_hit_counts.get(tweet.id, 0) + 1
                        if not duplicate_sample_id:
                            duplicate_sample_id = tweet.id
                    continue

                seen_tweet_ids.add(tweet.id)
                all_tweets.append(tweet)
                added_count += 1

                if len(all_tweets) >= limit:
                    break

            logger.info(
                f"[X Scraper][Page {page}] cursor={request_cursor or '<start>'} "
                f"next={next_cursor or '<none>'} raw={raw_count} add={added_count} "
                f"skip_old={skipped_old} skip_rt={skipped_retweet} "
                f"skip_dup={skipped_duplicate} total={len(all_tweets)}"
                + (
                    f" dup_sample={duplicate_sample_id}"
                    if duplicate_sample_id
                    else ""
                )
            )

            if added_count == 0:
                empty_add_pages += 1
            else:
                empty_add_pages = 0

            # A) pinned/重复主导 + 无新增：立即停，避免被固定重复条目拖住
            if (
                added_count == 0
                and skipped_duplicate > 0
                and duplicate_sample_id
                and (skipped_old + skipped_retweet + skipped_duplicate) >= raw_count
            ):
                logger.info(
                    f"[X Scraper] 检测到重复条目主导且本页无新增 "
                    f"(dup_sample={duplicate_sample_id})，停止分页"
                )
                break

            # B) 当页几乎全是过期内容且无新增：立即停
            old_ratio = (skipped_old / raw_count) if raw_count else 0.0
            if added_count == 0 and cutoff_date and old_ratio >= near_all_old_threshold:
                logger.info(
                    f"[X Scraper] 当页过期占比过高 ({old_ratio:.0%}) 且无新增，停止分页"
                )
                break

            if empty_add_pages >= max_empty_add_pages:
                logger.info(
                    f"[X Scraper] 连续 {empty_add_pages} 页无新增有效推文，"
                    "停止分页以避免低效空跑"
                )
                break

            # 如果整页推文都早于 cutoff，说明已翻到更早的时间段
            if cutoff_date and not page_has_new_enough:
                logger.debug(f"整页推文均早于 {since_date}，停止分页")
                break

            # 没有下一页
            if not next_cursor:
                break
            if next_cursor == cursor:
                logger.warning("检测到重复分页游标，停止翻页以避免重复抓取")
                break
            if next_cursor in seen_cursors:
                logger.warning("检测到游标循环，停止翻页以避免重复抓取")
                break

            seen_cursors.add(next_cursor)
            cursor = next_cursor

            # 分页间延迟
            delay = random.uniform(*page_delay)
            logger.debug(f"分页延迟 {delay:.1f}s...")
            time.sleep(delay)

        if duplicate_hit_counts:
            top_dup = sorted(
                duplicate_hit_counts.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )[:3]
            top_dup_str = ", ".join(f"{tid}({cnt})" for tid, cnt in top_dup)
            logger.info(f"[X Scraper] 跨页重复命中 Top IDs: {top_dup_str}")

        logger.info(f"共获取 {len(all_tweets)} 条推文 (共 {page} 页)")
        return all_tweets
