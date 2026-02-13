"""
parser.py - X/Twitter GraphQL 响应解析器

将 UserTweets GraphQL endpoint 返回的复杂嵌套 JSON 解析为 Tweet 对象。
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from .models import Tweet, TweetMedia

logger = logging.getLogger("x_scraper.parser")

# X (Twitter) 的日期格式: "Mon Feb 10 12:34:56 +0000 2026"
TWITTER_DATE_FORMAT = "%a %b %d %H:%M:%S %z %Y"


class TweetParser:
    """
    GraphQL 响应解析器

    处理 X 的 UserTweets / UserByScreenName 等 endpoint 的 JSON 响应。
    将深层嵌套的 JSON 结构解析为扁平的 Tweet 对象列表。
    """

    # ─── UserByScreenName 解析 ───

    @staticmethod
    def parse_user_id(response_json: dict) -> Optional[str]:
        """
        从 UserByScreenName 响应中提取 user_id (rest_id)。

        Args:
            response_json: GraphQL 响应 JSON

        Returns:
            用户 ID 字符串，或 None
        """
        try:
            user_result = response_json["data"]["user"]["result"]
            # 处理可能的 __typename 差异
            if user_result.get("__typename") == "UserUnavailable":
                logger.warning("用户不可用 (可能已被封禁或设为私密)")
                return None
            return user_result["rest_id"]
        except (KeyError, TypeError) as e:
            logger.error(f"解析 user_id 失败: {e}")
            return None

    # ─── UserTweets 解析 ───

    def parse_timeline(self, response_json: dict) -> Tuple[List[Tweet], Optional[str]]:
        """
        解析 UserTweets GraphQL 响应。

        Args:
            response_json: GraphQL 响应 JSON

        Returns:
            (tweets, next_cursor):
            - tweets: 解析出的 Tweet 列表
            - next_cursor: 下一页游标，None 表示已到末尾
        """
        tweets = []
        next_cursor = None
        seen_ids = set()  # Task 4: 去重 (置顶推文可能与时间线重复)

        try:
            # 通用路径：data.user.result.timeline_v2.timeline.instructions
            instructions = (
                response_json
                .get("data", {})
                .get("user", {})
                .get("result", {})
                .get("timeline_v2", {})
                .get("timeline", {})
                .get("instructions", [])
            )

            for instruction in instructions:
                inst_type = instruction.get("type", "")

                if inst_type == "TimelineAddEntries":
                    entries = instruction.get("entries", [])
                    for entry in entries:
                        entry_id = entry.get("entryId", "")

                        # 推文条目
                        if entry_id.startswith("tweet-"):
                            tweet = self._parse_tweet_entry(entry)
                            if tweet and tweet.id not in seen_ids:
                                seen_ids.add(tweet.id)
                                tweets.append(tweet)

                        # 分页游标
                        elif entry_id.startswith("cursor-bottom-"):
                            cursor_value = (
                                entry.get("content", {})
                                .get("value", "")
                            )
                            if cursor_value:
                                next_cursor = cursor_value

                        # 置顶推文模块 (moduleItems)
                        elif entry_id.startswith("profile-conversation-") or entry_id.startswith("homeConversation-"):
                            module_tweets = self._parse_module_entry(entry)
                            for t in module_tweets:
                                if t.id not in seen_ids:
                                    seen_ids.add(t.id)
                                    tweets.append(t)

                elif inst_type == "TimelinePinEntry":
                    # 置顶推文
                    entry = instruction.get("entry", {})
                    tweet = self._parse_tweet_entry(entry)
                    if tweet and tweet.id not in seen_ids:
                        seen_ids.add(tweet.id)
                        tweets.append(tweet)

        except Exception as e:
            logger.error(f"解析 timeline 失败: {e}", exc_info=True)

        return tweets, next_cursor

    def _parse_tweet_entry(self, entry: dict) -> Optional[Tweet]:
        """
        解析单个 timeline entry 为 Tweet 对象。

        Args:
            entry: TimelineTimelineItem entry dict

        Returns:
            Tweet 对象，解析失败返回 None
        """
        try:
            content = entry.get("content", {})
            item_content = content.get("itemContent", {})

            # 跳过 promoted content
            if item_content.get("promotedMetadata"):
                return None

            tweet_results = item_content.get("tweet_results", {})
            result = tweet_results.get("result", {})

            return self._parse_tweet_result(result)

        except Exception as e:
            entry_id = entry.get("entryId", "unknown")
            logger.debug(f"跳过无法解析的 entry [{entry_id}]: {e}")
            return None

    def _parse_module_entry(self, entry: dict) -> List[Tweet]:
        """解析 module 类型的 entry（可能包含多个推文，如对话线程）"""
        tweets = []
        try:
            items = (
                entry.get("content", {})
                .get("items", [])
            )
            for item in items:
                item_content = item.get("item", {}).get("itemContent", {})
                tweet_results = item_content.get("tweet_results", {})
                result = tweet_results.get("result", {})
                tweet = self._parse_tweet_result(result)
                if tweet:
                    tweets.append(tweet)
        except Exception as e:
            logger.debug(f"解析 module entry 失败: {e}")
        return tweets

    def _parse_tweet_result(self, result: dict) -> Optional[Tweet]:
        """
        解析 tweet_results.result 对象。

        处理:
        - 普通推文
        - TweetWithVisibilityResults (含 tweet 字段的包装)
        - 转推 (Retweet)
        - 引用推文 (Quote Tweet)

        Args:
            result: tweet_results.result dict

        Returns:
            Tweet 对象，或 None
        """
        if not result:
            return None

        typename = result.get("__typename", "")

        # TweetWithVisibilityResults 需要解包
        if typename == "TweetWithVisibilityResults":
            result = result.get("tweet", {})

        # 竞选标签或 TweetTombstone
        if typename in ("TweetTombstone", "TweetUnavailable"):
            return None

        try:
            legacy = result.get("legacy", {})
            if not legacy:
                return None

            # ─── 基本信息 ───
            tweet = Tweet(
                id=legacy.get("id_str", result.get("rest_id", "")),
                text=self._extract_full_text(result, legacy),
                created_at=self._parse_date(legacy.get("created_at", "")),
                lang=legacy.get("lang", ""),
                source=self._clean_source(result.get("source", "")),
                conversation_id=legacy.get("conversation_id_str"),
                in_reply_to_id=legacy.get("in_reply_to_status_id_str"),
                in_reply_to_username=legacy.get("in_reply_to_screen_name"),
                _raw=result,
            )

            # ─── 用户信息 ───
            user_result = (
                result.get("core", {})
                .get("user_results", {})
                .get("result", {})
            )
            user_legacy = user_result.get("legacy", {})
            tweet.user_id = user_result.get("rest_id", "")
            tweet.username = user_legacy.get("screen_name", "")
            tweet.display_name = user_legacy.get("name", "")

            # ─── 互动指标 ───
            tweet.reply_count = legacy.get("reply_count", 0)
            tweet.retweet_count = legacy.get("retweet_count", 0)
            tweet.like_count = legacy.get("favorite_count", 0)
            tweet.quote_count = legacy.get("quote_count", 0)
            tweet.bookmark_count = legacy.get("bookmark_count", 0)
            # view_count 在 views 字段中
            views = result.get("views", {})
            tweet.view_count = int(views.get("count", 0)) if views.get("count") else 0

            # ─── 外链提取 ───
            tweet.urls = self._extract_urls(legacy)

            # ─── 媒体附件 ───
            tweet.media = self._extract_media(legacy)

            # ─── 转推检测 ───
            retweeted_status = legacy.get("retweeted_status_result", {}).get("result")
            if retweeted_status:
                tweet.is_retweet = True
                tweet.retweeted_tweet = self._parse_tweet_result(retweeted_status)

            # ─── 引用推文 ───
            quoted_status = result.get("quoted_status_result", {}).get("result")
            if quoted_status:
                tweet.is_quote = True
                tweet.quoted_tweet = self._parse_tweet_result(quoted_status)

            return tweet

        except Exception as e:
            tweet_id = result.get("rest_id", "unknown")
            logger.debug(f"解析推文 [{tweet_id}] 失败: {e}")
            return None

    # ─── 字段提取辅助方法 ───

    def _extract_full_text(self, result: dict, legacy: dict) -> str:
        """
        提取推文全文。

        优先使用 note_tweet（长推文），否则回退到 legacy.full_text。
        """
        # 检查是否有 note_tweet (长推文 / Twitter Blue)
        note_tweet = (
            result.get("note_tweet", {})
            .get("note_tweet_results", {})
            .get("result", {})
        )
        if note_tweet:
            note_text = note_tweet.get("text", "")
            if note_text:
                return note_text

        return legacy.get("full_text", "")

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析 Twitter 日期格式"""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, TWITTER_DATE_FORMAT)
        except ValueError:
            logger.debug(f"无法解析日期: {date_str}")
            return None

    def _clean_source(self, source_html: str) -> str:
        """从 HTML <a> 标签中提取客户端名称"""
        if not source_html:
            return ""
        # 如 '<a href="..." rel="nofollow">Twitter Web App</a>'
        import re
        match = re.search(r'>(.+?)</a>', source_html)
        return match.group(1) if match else source_html

    def _extract_urls(self, legacy: dict) -> List[str]:
        """
        提取推文中的外链 URL (展开后的)。

        过滤掉:
        - 推文自身的链接 (t.co -> x.com)
        - 媒体链接
        """
        urls = []
        entities = legacy.get("entities", {})

        for url_entity in entities.get("urls", []):
            expanded = url_entity.get("expanded_url", "")
            if expanded:
                # 过滤掉推文自身引用 (x.com/.../status/...)
                if "/status/" in expanded and ("x.com" in expanded or "twitter.com" in expanded):
                    # 保留引用推文的链接
                    if expanded.split("/status/")[-1].split("?")[0] != legacy.get("id_str", ""):
                        urls.append(expanded)
                else:
                    urls.append(expanded)

        return urls

    def _extract_media(self, legacy: dict) -> List[TweetMedia]:
        """提取推文的媒体附件"""
        media_list = []
        extended_entities = legacy.get("extended_entities", {})
        media_items = extended_entities.get("media", [])

        for item in media_items:
            media = TweetMedia(
                type=item.get("type", ""),
                alt_text=item.get("ext_alt_text", ""),
            )

            if media.type == "photo":
                media.url = item.get("media_url_https", "")
                media.preview_url = media.url
            elif media.type in ("video", "animated_gif"):
                # 获取最高质量的视频 URL
                variants = item.get("video_info", {}).get("variants", [])
                mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
                if mp4_variants:
                    best = max(mp4_variants, key=lambda v: v.get("bitrate", 0))
                    media.url = best.get("url", "")
                media.preview_url = item.get("media_url_https", "")
                # 视频时长
                duration = item.get("video_info", {}).get("duration_millis", 0)
                media.duration_ms = duration

            # 尺寸
            sizes = item.get("original_info", {})
            media.width = sizes.get("width", 0)
            media.height = sizes.get("height", 0)

            media_list.append(media)

        return media_list
