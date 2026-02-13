"""
test_x_scraper.py - x_scraper 模块自动化测试

分为两部分：
1. 单元测试 (不依赖网络): 测试模型、解析器、账号池等内部逻辑
2. 集成测试 (需要网络 + 真实凭证): 端到端测试真实 X API 调用
   使用 @pytest.mark.integration 标记，默认跳过，可通过 --run-integration 启用

运行方式:
    # 仅运行单元测试
    python -m pytest tests/test_x_scraper.py -v

    # 运行所有测试（含集成测试，需要真实凭证）
    python -m pytest tests/test_x_scraper.py -v --run-integration
"""
import os
import sys
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# 将项目根目录加入 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from x_scraper.models import Tweet, TweetMedia
from x_scraper.parser import TweetParser
from x_scraper.account_pool import AccountPool, AccountState


# pytest 配置 (--run-integration 选项等) 在 conftest.py 中定义


# ============================================================
# 测试数据: 模拟 GraphQL 响应 JSON
# ============================================================

SAMPLE_TWEET_LEGACY = {
    "id_str": "1234567890",
    "full_text": "This is a test tweet with a link https://t.co/abc123 #AI",
    "created_at": "Mon Feb 10 12:34:56 +0000 2026",
    "lang": "en",
    "conversation_id_str": "1234567890",
    "in_reply_to_status_id_str": None,
    "in_reply_to_screen_name": None,
    "reply_count": 5,
    "retweet_count": 10,
    "favorite_count": 100,
    "quote_count": 3,
    "bookmark_count": 8,
    "entities": {
        "urls": [
            {
                "url": "https://t.co/abc123",
                "expanded_url": "https://example.com/blog-post",
                "display_url": "example.com/blog-post",
            }
        ],
    },
    "extended_entities": {
        "media": [
            {
                "type": "photo",
                "media_url_https": "https://pbs.twimg.com/media/test_photo.jpg",
                "ext_alt_text": "A test image",
                "original_info": {"width": 1200, "height": 800},
            }
        ],
    },
}

SAMPLE_USER_RESULT = {
    "rest_id": "999888777",
    "legacy": {
        "screen_name": "testuser",
        "name": "Test User Display Name",
    },
}

SAMPLE_TWEET_RESULT = {
    "__typename": "Tweet",
    "rest_id": "1234567890",
    "legacy": SAMPLE_TWEET_LEGACY,
    "core": {
        "user_results": {
            "result": SAMPLE_USER_RESULT,
        },
    },
    "views": {
        "count": "5000",
        "state": "EnabledWithCount",
    },
    "source": '<a href="https://mobile.twitter.com" rel="nofollow">Twitter Web App</a>',
}

SAMPLE_TIMELINE_RESPONSE = {
    "data": {
        "user": {
            "result": {
                "timeline_v2": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-1234567890",
                                        "content": {
                                            "entryType": "TimelineTimelineItem",
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": SAMPLE_TWEET_RESULT,
                                                },
                                            },
                                        },
                                    },
                                    {
                                        "entryId": "tweet-1234567891",
                                        "content": {
                                            "entryType": "TimelineTimelineItem",
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        **SAMPLE_TWEET_RESULT,
                                                        "rest_id": "1234567891",
                                                        "legacy": {
                                                            **SAMPLE_TWEET_LEGACY,
                                                            "id_str": "1234567891",
                                                            "full_text": "Second test tweet about #DeepSeek",
                                                            "created_at": "Mon Feb 10 10:00:00 +0000 2026",
                                                        },
                                                    },
                                                },
                                            },
                                        },
                                    },
                                    {
                                        "entryId": "cursor-bottom-12345abcdef",
                                        "content": {
                                            "entryType": "TimelineTimelineCursor",
                                            "value": "DAACCgACGdy0tN_SAhAKAAMZ3LS038ICEAAAAAAAAAA",
                                            "cursorType": "Bottom",
                                        },
                                    },
                                ],
                            }
                        ],
                    },
                },
            },
        },
    },
}

SAMPLE_USER_BY_SCREEN_NAME_RESPONSE = {
    "data": {
        "user": {
            "result": {
                "__typename": "User",
                "rest_id": "999888777",
                "legacy": {
                    "screen_name": "testuser",
                    "name": "Test User",
                },
            },
        },
    },
}


# ============================================================
# 单元测试: Tweet 模型
# ============================================================

class TestTweetModel:
    """测试 Tweet 数据模型"""

    def test_create_tweet(self):
        """测试基本 Tweet 创建"""
        tweet = Tweet(
            id="123",
            text="Hello World",
            username="testuser",
            created_at=datetime(2026, 2, 10, 12, 0, 0, tzinfo=timezone.utc),
        )
        assert tweet.id == "123"
        assert tweet.text == "Hello World"
        assert tweet.username == "testuser"

    def test_permalink(self):
        """测试永久链接生成"""
        tweet = Tweet(id="456", username="karpathy")
        assert tweet.permalink == "https://x.com/karpathy/status/456"

    def test_date_str(self):
        """测试日期格式化"""
        tweet = Tweet(
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc)
        )
        assert tweet.date_str == "2026-02-10"

    def test_date_str_none(self):
        """测试空日期"""
        tweet = Tweet()
        assert tweet.date_str == ""

    def test_to_post_dict_basic(self):
        """测试转换为 Pipeline 兼容的 post dict"""
        tweet = Tweet(
            id="789",
            text="Test tweet with important content",
            username="testuser",
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
            urls=["https://example.com/article"],
        )
        post = tweet.to_post_dict("X_TestUser")

        assert post["source_type"] == "X"
        assert post["source_name"] == "X_TestUser"
        assert post["date"] == "2026-02-10"
        assert post["link"] == "https://x.com/testuser/status/789"
        assert "Test tweet" in post["title"]
        assert "extra_content" in post
        assert "extra_urls" in post
        assert isinstance(post["extra_urls"], list)

    def test_to_post_dict_retweet(self):
        """测试转推的 post dict 标题格式"""
        rt_tweet = Tweet(id="100", text="Original", username="origuser")
        tweet = Tweet(
            id="789",
            text="RT @origuser: Original",
            username="testuser",
            is_retweet=True,
            retweeted_tweet=rt_tweet,
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        post = tweet.to_post_dict("X_TestUser")
        assert "RT @origuser" in post["title"]

    def test_build_content_html_with_urls(self):
        """测试 HTML 内容构建包含链接"""
        tweet = Tweet(
            text="Check this out https://example.com",
            urls=["https://example.com"],
        )
        html = tweet._build_content_html()
        assert "href" in html
        assert "example.com" in html

    def test_build_content_html_with_media(self):
        """测试 HTML 内容构建包含媒体"""
        tweet = Tweet(
            text="Photo tweet",
            media=[TweetMedia(type="photo", url="https://img.example.com/pic.jpg")],
        )
        html = tweet._build_content_html()
        assert "<img" in html
        assert "pic.jpg" in html

    def test_build_content_html_with_quoted_tweet(self):
        """测试 HTML 内容包含引用推文"""
        qt = Tweet(id="100", text="Quoted content", username="quoteduser")
        tweet = Tweet(
            text="Look at this",
            is_quote=True,
            quoted_tweet=qt,
        )
        html = tweet._build_content_html()
        assert "<blockquote>" in html
        assert "quoteduser" in html

    def test_str_representation(self):
        """测试 __str__ 输出"""
        tweet = Tweet(
            text="Short text",
            username="user",
            created_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
        )
        s = str(tweet)
        assert "@user" in s
        assert "2026-02-10" in s

    def test_str_long_text_truncated(self):
        """测试长文本在 __str__ 中被截断"""
        tweet = Tweet(text="A" * 100, username="user")
        s = str(tweet)
        assert "..." in s


# ============================================================
# 单元测试: TweetMedia 模型
# ============================================================

class TestTweetMediaModel:
    """测试 TweetMedia 数据模型"""

    def test_create_photo(self):
        media = TweetMedia(type="photo", url="https://example.com/img.jpg", width=800, height=600)
        assert media.type == "photo"
        assert media.width == 800

    def test_create_video(self):
        media = TweetMedia(type="video", url="https://example.com/vid.mp4", duration_ms=30000)
        assert media.duration_ms == 30000


# ============================================================
# 单元测试: TweetParser (GraphQL 响应解析)
# ============================================================

class TestTweetParser:
    """测试 GraphQL 响应解析器"""

    def setup_method(self):
        self.parser = TweetParser()

    def test_parse_user_id(self):
        """测试从 UserByScreenName 响应解析 user_id"""
        user_id = TweetParser.parse_user_id(SAMPLE_USER_BY_SCREEN_NAME_RESPONSE)
        assert user_id == "999888777"

    def test_parse_user_id_unavailable(self):
        """测试用户不可用的情况"""
        response = {
            "data": {
                "user": {
                    "result": {
                        "__typename": "UserUnavailable",
                    }
                }
            }
        }
        user_id = TweetParser.parse_user_id(response)
        assert user_id is None

    def test_parse_user_id_empty(self):
        """测试空响应"""
        user_id = TweetParser.parse_user_id({})
        assert user_id is None

    def test_parse_timeline_tweets(self):
        """测试解析 timeline 返回推文列表"""
        tweets, cursor = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        assert len(tweets) == 2
        assert tweets[0].id == "1234567890"
        assert tweets[1].id == "1234567891"

    def test_parse_timeline_cursor(self):
        """测试解析 timeline 返回分页游标"""
        tweets, cursor = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        assert cursor is not None
        assert "DAACCgACGdy0tN" in cursor

    def test_parse_timeline_tweet_content(self):
        """测试推文内容字段完整性"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]

        assert tweet.text == "This is a test tweet with a link https://t.co/abc123 #AI"
        assert tweet.username == "testuser"
        assert tweet.display_name == "Test User Display Name"
        assert tweet.user_id == "999888777"

    def test_parse_timeline_tweet_metrics(self):
        """测试互动指标解析"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]

        assert tweet.reply_count == 5
        assert tweet.retweet_count == 10
        assert tweet.like_count == 100
        assert tweet.quote_count == 3
        assert tweet.bookmark_count == 8
        assert tweet.view_count == 5000

    def test_parse_timeline_urls(self):
        """测试外链解析"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]

        assert "https://example.com/blog-post" in tweet.urls

    def test_parse_timeline_media(self):
        """测试媒体附件解析"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]

        assert len(tweet.media) == 1
        assert tweet.media[0].type == "photo"
        assert tweet.media[0].width == 1200
        assert tweet.media[0].alt_text == "A test image"

    def test_parse_timeline_source(self):
        """测试发布客户端解析"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]
        assert tweet.source == "Twitter Web App"

    def test_parse_timeline_date(self):
        """测试日期解析"""
        tweets, _ = self.parser.parse_timeline(SAMPLE_TIMELINE_RESPONSE)
        tweet = tweets[0]

        assert tweet.created_at is not None
        assert tweet.created_at.year == 2026
        assert tweet.created_at.month == 2
        assert tweet.created_at.day == 10

    def test_parse_empty_timeline(self):
        """测试空 timeline"""
        response = {"data": {"user": {"result": {"timeline_v2": {"timeline": {"instructions": []}}}}}}
        tweets, cursor = self.parser.parse_timeline(response)
        assert tweets == []
        assert cursor is None

    def test_parse_timeline_skips_promoted(self):
        """测试跳过广告推文"""
        promoted_response = {
            "data": {
                "user": {
                    "result": {
                        "timeline_v2": {
                            "timeline": {
                                "instructions": [
                                    {
                                        "type": "TimelineAddEntries",
                                        "entries": [
                                            {
                                                "entryId": "tweet-promo-123",
                                                "content": {
                                                    "entryType": "TimelineTimelineItem",
                                                    "itemContent": {
                                                        "promotedMetadata": {"advertiser_results": {}},
                                                        "tweet_results": {
                                                            "result": SAMPLE_TWEET_RESULT,
                                                        },
                                                    },
                                                },
                                            }
                                        ],
                                    }
                                ],
                            },
                        },
                    },
                },
            },
        }
        tweets, _ = self.parser.parse_timeline(promoted_response)
        assert len(tweets) == 0

    def test_parse_tweet_with_visibility_results(self):
        """测试 TweetWithVisibilityResults 类型解包"""
        visibility_result = {
            "__typename": "TweetWithVisibilityResults",
            "tweet": SAMPLE_TWEET_RESULT,
        }
        tweet = self.parser._parse_tweet_result(visibility_result)
        assert tweet is not None
        assert tweet.id == "1234567890"

    def test_parse_tweet_tombstone(self):
        """测试 TweetTombstone 返回 None"""
        tombstone = {"__typename": "TweetTombstone"}
        tweet = self.parser._parse_tweet_result(tombstone)
        assert tweet is None

    def test_parse_note_tweet_long_text(self):
        """测试长推文 (note_tweet) 全文提取"""
        long_text = "A" * 500
        result_with_note = {
            **SAMPLE_TWEET_RESULT,
            "note_tweet": {
                "note_tweet_results": {
                    "result": {
                        "text": long_text,
                    }
                }
            },
        }
        tweet = self.parser._parse_tweet_result(result_with_note)
        assert tweet.text == long_text

    def test_parse_retweet(self):
        """测试转推解析"""
        rt_result = {
            **SAMPLE_TWEET_RESULT,
            "legacy": {
                **SAMPLE_TWEET_LEGACY,
                "retweeted_status_result": {
                    "result": {
                        **SAMPLE_TWEET_RESULT,
                        "rest_id": "9999",
                        "legacy": {
                            **SAMPLE_TWEET_LEGACY,
                            "id_str": "9999",
                            "full_text": "Original tweet",
                        },
                    },
                },
            },
        }
        tweet = self.parser._parse_tweet_result(rt_result)
        assert tweet.is_retweet is True
        assert tweet.retweeted_tweet is not None
        assert tweet.retweeted_tweet.id == "9999"

    def test_parse_quote_tweet(self):
        """测试引用推文解析"""
        qt_result = {
            **SAMPLE_TWEET_RESULT,
            "quoted_status_result": {
                "result": {
                    **SAMPLE_TWEET_RESULT,
                    "rest_id": "8888",
                    "legacy": {
                        **SAMPLE_TWEET_LEGACY,
                        "id_str": "8888",
                        "full_text": "Quoted tweet content",
                    },
                },
            },
        }
        tweet = self.parser._parse_tweet_result(qt_result)
        assert tweet.is_quote is True
        assert tweet.quoted_tweet is not None
        assert tweet.quoted_tweet.text == "Quoted tweet content"


# ============================================================
# 单元测试: AccountPool
# ============================================================

class TestAccountPool:
    """测试账号池管理"""

    def test_create_from_credentials(self):
        """测试直接创建"""
        pool = AccountPool([("token1", "ct01"), ("token2", "ct02")])
        assert pool.total_count == 2
        assert pool.available_count == 2

    def test_create_empty_raises(self):
        """测试空凭证列表报错"""
        with pytest.raises(ValueError):
            AccountPool([])

    def test_from_config_string(self):
        """测试从配置字符串解析"""
        pool = AccountPool.from_config_string("tok1:ct01;tok2:ct02")
        assert pool.total_count == 2

    def test_from_config_string_single(self):
        """测试单个凭证"""
        pool = AccountPool.from_config_string("tok1:ct01")
        assert pool.total_count == 1

    def test_from_config_string_with_spaces(self):
        """测试带空格和空段"""
        pool = AccountPool.from_config_string(" tok1:ct01 ; tok2:ct02 ; ; ")
        assert pool.total_count == 2

    def test_get_next_round_robin(self):
        """测试轮换获取"""
        pool = AccountPool([("t1", "c1"), ("t2", "c2"), ("t3", "c3")])

        a1 = pool.get_next()
        a2 = pool.get_next()
        a3 = pool.get_next()
        a4 = pool.get_next()  # 回到第一个

        assert a1.auth_token == "t1"
        assert a2.auth_token == "t2"
        assert a3.auth_token == "t3"
        assert a4.auth_token == "t1"

    def test_mark_rate_limited(self):
        """测试限速标记"""
        pool = AccountPool([("t1", "c1"), ("t2", "c2")])

        a1 = pool.get_next()
        pool.mark_rate_limited(a1, cooldown_seconds=60)

        assert not a1.is_available
        assert a1.cooldown_remaining > 0
        assert pool.available_count == 1

        # 下一次获取应跳过 a1
        a2 = pool.get_next()
        assert a2.auth_token == "t2"

    def test_mark_dead(self):
        """测试永久失效标记"""
        pool = AccountPool([("t1", "c1"), ("t2", "c2")])

        a1 = pool.get_next()
        pool.mark_dead(a1, "Token expired")

        assert a1.is_dead
        assert not a1.is_available
        assert pool.available_count == 1

    def test_all_unavailable_returns_none(self):
        """测试所有账号不可用时返回 None"""
        pool = AccountPool([("t1", "c1")])
        a1 = pool.get_next()
        pool.mark_dead(a1)

        result = pool.get_next()
        assert result is None

    def test_get_status(self):
        """测试状态摘要"""
        pool = AccountPool([("t1", "c1"), ("t2", "c2")])
        a1 = pool.get_next()
        pool.mark_dead(a1, "expired")

        status = pool.get_status()
        assert len(status) == 2
        assert status[0]["status"] == "dead"
        assert status[1]["status"] == "available"

    def test_request_count_incremented(self):
        """测试请求计数递增"""
        pool = AccountPool([("t1", "c1")])

        a = pool.get_next()
        assert a.request_count == 1

        a = pool.get_next()
        assert a.request_count == 2

    def test_from_env_file(self, tmp_path):
        """测试从 .env 文件加载"""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            'TWITTER_AUTH_TOKEN="test_auth_token_here"\n'
            'TWITTER_CT0="test_ct0_value_here"\n'
            'XCSRF_TOKEN="test_ct0_value_here"\n'
        )
        pool = AccountPool.from_env_file(str(env_file))
        assert pool.total_count == 1
        a = pool.get_next()
        assert a.auth_token == "test_auth_token_here"
        assert a.ct0 == "test_ct0_value_here"

    def test_from_env_file_not_found(self):
        """测试文件不存在报错"""
        with pytest.raises(FileNotFoundError):
            AccountPool.from_env_file("/nonexistent/path.env")


# ============================================================
# 单元测试: XClient (核心逻辑，使用 mock)
# ============================================================

class TestXClient:
    """测试 X 客户端 (使用 mock，不需要网络)"""

    def _make_client(self):
        """创建一个用于测试的 XClient"""
        from x_scraper.client import XClient
        pool = AccountPool([("test_token", "test_ct0")])
        client = XClient(account_pool=pool, max_retries=2)
        return client

    def test_build_headers(self):
        """测试请求头构建"""
        client = self._make_client()
        account = client.account_pool.get_next()
        headers = client._build_headers(account)

        assert "authorization" in headers
        assert "Bearer" in headers["authorization"]
        assert headers["x-csrf-token"] == "test_ct0"
        assert headers["x-twitter-auth-type"] == "OAuth2Session"

    def test_build_cookies(self):
        """测试 Cookie 构建"""
        client = self._make_client()
        account = client.account_pool.get_next()
        cookies = client._build_cookies(account)

        assert cookies["auth_token"] == "test_token"
        assert cookies["ct0"] == "test_ct0"

    def test_user_id_cache(self):
        """测试 user_id 缓存机制"""
        client = self._make_client()
        # 预填缓存
        client._user_id_cache["testuser"] = "12345"

        # 不应该发出网络请求
        user_id = client.get_user_id("testuser")
        assert user_id == "12345"


# ============================================================
# 单元测试: XScraper (高层编排)
# ============================================================

class TestXScraper:
    """测试 XScraper 高层 API (使用 mock)"""

    def test_from_config_with_env_file(self, tmp_path):
        """测试从配置 + env 文件创建"""
        import configparser

        # 创建 env 文件
        env_file = tmp_path / "rsshub-docker.env"
        env_file.write_text(
            'TWITTER_AUTH_TOKEN="mock_token"\n'
            'TWITTER_CT0="mock_ct0"\n'
        )

        config = configparser.ConfigParser()
        config.optionxform = str
        config.add_section('x_scraper')
        config.set('x_scraper', 'auth_credentials', '')
        config.set('x_scraper', 'max_tweets_per_user', '10')

        # Mock _find_project_root to return tmp_path
        with patch('x_scraper.scraper._find_project_root', return_value=str(tmp_path)):
            scraper = __import__('x_scraper').XScraper.from_config(config)
            assert scraper.max_tweets_per_user == 10
            assert scraper.account_pool.total_count == 1

    def test_from_config_with_inline_credentials(self):
        """测试从内联凭证创建"""
        import configparser

        config = configparser.ConfigParser()
        config.optionxform = str
        config.add_section('x_scraper')
        config.set('x_scraper', 'auth_credentials', 'tok1:ct01;tok2:ct02')
        config.set('x_scraper', 'max_tweets_per_user', '50')
        config.set('x_scraper', 'include_retweets', 'true')

        scraper = __import__('x_scraper').XScraper.from_config(config)
        assert scraper.max_tweets_per_user == 50
        assert scraper.include_retweets is True
        assert scraper.account_pool.total_count == 2


# ============================================================
# 单元测试: Code Review 修复验证
# ============================================================

class TestReviewFixes:
    """验证 Code Review 发现的 Bug 修复"""

    def test_retry_after_non_integer(self):
        """Task 2: retry-after 为 HTTP-date 时不应崩溃"""
        from x_scraper.client import XClient, RateLimitError

        pool = AccountPool([("test_token", "test_ct0")])
        client = XClient(account_pool=pool, max_retries=1)

        # mock 一个 429 响应，retry-after 是 HTTP-date 格式
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"retry-after": "Thu, 01 Jan 2099 00:00:00 GMT"}

        with patch.object(client, '_curl_requests' if client._use_curl_cffi else '_requests') as mock_req:
            mock_req.get.return_value = mock_response
            # 应该抛出 RateLimitError（使用默认 900s），而不是 ValueError
            with pytest.raises(RateLimitError) as exc_info:
                account = pool.get_next()
                client._make_request("https://x.com/test", {}, account)
            assert exc_info.value.retry_after == 900

    def test_graphql_error_detected(self):
        """Task 3: HTTP 200 + GraphQL errors 应被检测"""
        from x_scraper.client import XClient, XClientError

        pool = AccountPool([("test_token", "test_ct0")])
        client = XClient(account_pool=pool)

        # mock 一个 HTTP 200 但内容含 errors 的响应
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [{"message": "Rate limit exceeded", "code": 88}]
        }

        with patch.object(client, '_curl_requests' if client._use_curl_cffi else '_requests') as mock_req:
            mock_req.get.return_value = mock_response
            with pytest.raises(XClientError, match="GraphQL error"):
                account = pool.get_next()
                client._make_request("https://x.com/test", {}, account)

    def test_graphql_error_with_partial_data_ok(self):
        """Task 3: HTTP 200 + errors + data 应正常返回 (某些 field 错误但主数据可用)"""
        from x_scraper.client import XClient

        pool = AccountPool([("test_token", "test_ct0")])
        client = XClient(account_pool=pool)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "errors": [{"message": "some warning"}],
            "data": {"user": {"result": {"rest_id": "123"}}}
        }

        with patch.object(client, '_curl_requests' if client._use_curl_cffi else '_requests') as mock_req:
            mock_req.get.return_value = mock_response
            account = pool.get_next()
            result = client._make_request("https://x.com/test", {}, account)
            assert "data" in result  # 有 data 时应正常返回

    def test_pinned_tweet_dedup(self):
        """Task 4: 置顶推文与时间线推文重复时应去重"""
        parser = TweetParser()
        # 构造一个 pinned + timeline 都包含同一 tweet 的响应
        response = {
            "data": {
                "user": {
                    "result": {
                        "timeline_v2": {
                            "timeline": {
                                "instructions": [
                                    {
                                        "type": "TimelinePinEntry",
                                        "entry": {
                                            "entryId": "tweet-1234567890",
                                            "content": {
                                                "entryType": "TimelineTimelineItem",
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": SAMPLE_TWEET_RESULT,
                                                    }
                                                }
                                            }
                                        }
                                    },
                                    {
                                        "type": "TimelineAddEntries",
                                        "entries": [
                                            {
                                                "entryId": "tweet-1234567890",
                                                "content": {
                                                    "entryType": "TimelineTimelineItem",
                                                    "itemContent": {
                                                        "tweet_results": {
                                                            "result": SAMPLE_TWEET_RESULT,
                                                        }
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        }
        tweets, _ = parser.parse_timeline(response)
        # 应该只有 1 条，不是 2 条
        assert len(tweets) == 1
        assert tweets[0].id == "1234567890"

    def test_env_exact_key_match(self, tmp_path):
        """Task 5: .env 应精确匹配 key，不匹配带后缀的键"""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            'TWITTER_AUTH_TOKEN_BACKUP="wrong_token"\n'
            'TWITTER_AUTH_TOKEN="correct_token"\n'
            'TWITTER_CT0="correct_ct0"\n'
        )
        pool = AccountPool.from_env_file(str(env_file))
        a = pool.get_next()
        assert a.auth_token == "correct_token"
        assert a.ct0 == "correct_ct0"

    def test_env_xcsrf_token_fallback(self, tmp_path):
        """Task 5: 支持 XCSRF_TOKEN 作为 ct0 的替代键"""
        env_file = tmp_path / "test.env"
        env_file.write_text(
            'TWITTER_AUTH_TOKEN="my_token"\n'
            'XCSRF_TOKEN="my_csrf"\n'
        )
        pool = AccountPool.from_env_file(str(env_file))
        a = pool.get_next()
        assert a.ct0 == "my_csrf"

    def test_status_token_masked(self):
        """Task 6: get_status 中的 token 应被脱敏"""
        pool = AccountPool([("abcdefghijklmnop", "ct0_value")])
        status = pool.get_status()
        hint = status[0]["auth_token_hint"]
        assert hint == "abcd****"
        assert "abcdefgh" not in hint  # 不应暴露 8 字符前缀


# ============================================================
# 单元测试: 抓取风险增强 (P1/P2/P3)
# ============================================================

class TestRiskEnhancements:
    """验证断路器、可配置 Query IDs/Features、UA 轮换"""

    def test_circuit_breaker_triggers(self):
        """P1: 连续失败达到阈值时断路器应打开"""
        from x_scraper.client import XClient

        pool = AccountPool([("tok", "ct0")])
        client = XClient(
            account_pool=pool,
            circuit_breaker_threshold=3,
            circuit_breaker_cooldown=10,
        )

        # 模拟 3 次连续失败
        for _ in range(3):
            client._record_failure()

        assert client._cb_consecutive_failures == 3
        assert client._cb_open_until > 0, "断路器应已打开"

    def test_circuit_breaker_resets_on_success(self):
        """P1: 成功后断路器应重置"""
        from x_scraper.client import XClient

        pool = AccountPool([("tok", "ct0")])
        client = XClient(account_pool=pool, circuit_breaker_threshold=3)

        # 模拟 2 次失败 + 1 次成功
        client._record_failure()
        client._record_failure()
        assert client._cb_consecutive_failures == 2

        client._record_success()
        assert client._cb_consecutive_failures == 0
        assert client._cb_open_until == 0

    def test_custom_query_ids(self):
        """P2: 自定义 Query IDs 应覆盖默认值"""
        from x_scraper.client import XClient, QUERY_IDS

        pool = AccountPool([("tok", "ct0")])
        custom_ids = {"UserTweets": "NEW_QUERY_ID_123"}
        client = XClient(account_pool=pool, query_ids=custom_ids)

        # UserTweets 应被覆盖
        assert client._query_ids["UserTweets"] == "NEW_QUERY_ID_123"
        # UserByScreenName 应保持默认
        assert client._query_ids["UserByScreenName"] == QUERY_IDS["UserByScreenName"]

    def test_custom_features(self):
        """P2: 自定义 Features 应合并到默认值"""
        from x_scraper.client import XClient, DEFAULT_FEATURES

        pool = AccountPool([("tok", "ct0")])
        custom_features = {"new_feature_flag": True, "rweb_tipjar_consumption_enabled": False}
        client = XClient(account_pool=pool, features=custom_features)

        # 新 flag 应存在
        assert client._features["new_feature_flag"] is True
        # 覆盖的 flag 应生效
        assert client._features["rweb_tipjar_consumption_enabled"] is False
        # 其他默认 flag 应保留
        assert "view_counts_everywhere_api_enabled" in client._features

    def test_ua_rotation(self):
        """P3: 每次构建请求头应使用不同 UA（概率性）"""
        from x_scraper.client import XClient, UA_POOL

        pool = AccountPool([("tok", "ct0")])
        client = XClient(account_pool=pool)
        account = pool.accounts[0]

        # 多次构建请求头，收集 UA
        uas = set()
        for _ in range(30):
            headers = client._build_headers(account)
            uas.add(headers["user-agent"])

        # 应该看到多个不同的 UA (概率性测试，30 次中至少应有 2 个不同)
        assert len(uas) >= 2, f"UA 应有变化，但只看到: {uas}"
        # 所有 UA 应来自 UA_POOL
        for ua in uas:
            assert ua in UA_POOL, f"UA '{ua}' 不在 UA_POOL 中"


# ============================================================
# 集成测试: 端到端 (需要真实凭证和网络)
# ============================================================

@pytest.mark.integration
class TestIntegration:
    """
    端到端集成测试。
    
    需要:
    1. 项目根目录存在 rsshub-docker.env (含有效凭证)
    2. 网络连通
    
    运行方式:
        python -m pytest tests/test_x_scraper.py -v --run-integration -k TestIntegration
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """加载真实配置"""
        import configparser
        project_root = os.path.join(os.path.dirname(__file__), '..')
        config_path = os.path.join(project_root, 'config.ini')

        self.config = configparser.ConfigParser()
        self.config.optionxform = str
        self.config.read(config_path, encoding='utf-8')

        # 确保 env 文件存在
        self.env_file = os.path.join(project_root, 'rsshub-docker.env')
        if not os.path.exists(self.env_file):
            pytest.skip("rsshub-docker.env 不存在，跳过集成测试")

    def test_e2e_get_user_id(self):
        """端到端: 获取用户 ID"""
        from x_scraper import AccountPool, XClient

        pool = AccountPool.from_env_file(self.env_file)
        client = XClient(account_pool=pool)

        # OpenAI 是一个稳定存在的大账号
        user_id = client.get_user_id("OpenAI")
        assert user_id is not None
        assert user_id.isdigit()
        print(f"\n  @OpenAI user_id = {user_id}")

    def test_e2e_get_user_tweets(self):
        """端到端: 获取用户推文"""
        from x_scraper import AccountPool, XClient

        pool = AccountPool.from_env_file(self.env_file)
        client = XClient(account_pool=pool)

        user_id = client.get_user_id("OpenAI")
        assert user_id is not None

        tweets, cursor = client.get_user_tweets(user_id, count=5)
        assert len(tweets) > 0
        assert cursor is not None  # 应该有下一页

        # 验证推文字段
        tweet = tweets[0]
        print(f"\n  第一条推文: {tweet}")
        assert tweet.id != ""
        assert tweet.text != ""
        assert tweet.username != ""
        assert tweet.created_at is not None

    def test_e2e_scraper_fetch_user(self):
        """端到端: 使用 XScraper 抓取用户推文"""
        from x_scraper import XScraper

        scraper = XScraper.from_config(self.config)

        # 只抓取 5 条，加速测试
        tweets = scraper.fetch_user_tweets("OpenAI", limit=5)
        assert len(tweets) > 0

        print(f"\n  获取到 {len(tweets)} 条推文:")
        for t in tweets:
            print(f"    {t}")

    def test_e2e_scraper_as_post_dict(self):
        """端到端: Pipeline 兼容格式输出"""
        from x_scraper import XScraper

        scraper = XScraper.from_config(self.config)
        posts = scraper.fetch_user_tweets_as_posts("OpenAI", "X_OpenAI", limit=3)

        assert len(posts) > 0

        # 验证 post dict 格式兼容 Pipeline
        post = posts[0]
        required_keys = ["title", "date", "link", "source_type", "source_name", "content", "extra_content", "extra_urls"]
        for key in required_keys:
            assert key in post, f"缺少字段: {key}"

        assert post["source_type"] == "X"
        assert post["source_name"] == "X_OpenAI"
        assert post["link"].startswith("https://x.com/")

        print(f"\n  Post dict 示例:")
        print(f"    title: {post['title'][:60]}...")
        print(f"    date: {post['date']}")
        print(f"    link: {post['link']}")
        print(f"    source: {post['source_name']}")
        print(f"    content length: {len(post['content'])} chars")

    def test_e2e_date_filter(self):
        """端到端: 日期过滤"""
        from x_scraper import XScraper

        scraper = XScraper.from_config(self.config)
        tweets = scraper.fetch_user_tweets("OpenAI", limit=10, days_lookback=3)

        print(f"\n  最近 3 天推文: {len(tweets)} 条")
        assert len(tweets) > 0, "最近 3 天应有推文 (OpenAI 是高频发布账号)"

        for t in tweets:
            print(f"    {t}")
            assert t.created_at is not None
            # 推文日期应该在最近 3 天之内 (给 1 天误差余量)
            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=4)
            assert t.created_at >= cutoff, f"推文日期 {t.created_at} 超出范围"
