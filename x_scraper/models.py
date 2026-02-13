"""
models.py - X/Twitter 推文数据模型

定义 Tweet 和 TweetMedia 数据类，以及与 Pipeline FetcherStage 兼容的序列化方法。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from html import escape


@dataclass
class TweetMedia:
    """推文媒体附件（图片/视频/GIF）"""
    type: str = ""             # "photo", "video", "animated_gif"
    url: str = ""              # 媒体 URL
    preview_url: str = ""      # 缩略图 URL
    alt_text: str = ""         # 无障碍描述
    width: int = 0
    height: int = 0
    duration_ms: int = 0       # 视频时长 (毫秒)


@dataclass
class Tweet:
    """X/Twitter 推文数据结构"""
    id: str = ""                           # 推文 ID
    text: str = ""                         # 推文全文 (note_tweet 时为完整文档)
    created_at: Optional[datetime] = None  # 发布时间 (UTC)
    user_id: str = ""                      # 用户 ID
    username: str = ""                     # 用户名 (@handle)
    display_name: str = ""                 # 显示名称

    # 互动指标
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0
    view_count: int = 0
    bookmark_count: int = 0
    quote_count: int = 0

    # 内容附件
    urls: List[str] = field(default_factory=list)       # 正文中的外链
    media: List[TweetMedia] = field(default_factory=list)  # 图片/视频附件

    # 引用/转发
    is_retweet: bool = False
    is_quote: bool = False
    quoted_tweet: Optional['Tweet'] = None
    retweeted_tweet: Optional['Tweet'] = None

    # 对话上下文
    in_reply_to_id: Optional[str] = None
    in_reply_to_username: Optional[str] = None
    conversation_id: Optional[str] = None

    lang: str = ""                  # 语言代码
    source: str = ""                # 发布客户端

    # 原始数据 (用于调试)
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def permalink(self) -> str:
        """推文永久链接"""
        return f"https://x.com/{self.username}/status/{self.id}"

    @property
    def date_str(self) -> str:
        """日期字符串 YYYY-MM-DD"""
        if self.created_at:
            return self.created_at.strftime("%Y-%m-%d")
        return ""

    def _build_content_html(self) -> str:
        """
        构建与 RSSHub 输出格式类似的 HTML 内容。
        用于兼容 content_enricher 阶段的链接提取逻辑。
        """
        parts = []

        # 推文正文
        text = escape(self.text) if self.text else ""
        # 将 URL 转换为 <a> 标签，便于 LinkExtractor 提取
        for url in self.urls:
            escaped_url = escape(url)
            if escaped_url in text:
                text = text.replace(escaped_url, f'<a href="{escaped_url}">{escaped_url}</a>')
            else:
                # URL 可能被 t.co 缩短，追加到末尾
                parts.append(f'<a href="{escaped_url}">{escaped_url}</a>')

        parts.insert(0, f"<p>{text}</p>")

        # 媒体附件
        for m in self.media:
            if m.type == "photo":
                parts.append(f'<img src="{escape(m.url)}" />')
            elif m.type in ("video", "animated_gif"):
                parts.append(f'<video src="{escape(m.url)}"></video>')

        # 引用推文
        if self.quoted_tweet:
            qt = self.quoted_tweet
            parts.append(
                f'<blockquote>'
                f'<p><b>@{escape(qt.username)}</b>: {escape(qt.text[:200])}</p>'
                f'<a href="{escape(qt.permalink)}">{escape(qt.permalink)}</a>'
                f'</blockquote>'
            )

        return "\n".join(parts)

    def to_post_dict(self, source_name: str) -> dict:
        """
        转换为 Pipeline FetcherStage 兼容的 post 字典。

        此格式与 source_fetcher._fetch_recent_posts() 的输出完全一致，
        可以直接放入 fetch_queue 供后续 Pipeline 阶段消费。
        """
        # 标题: 取推文前100字符
        title = self.text[:100] if self.text else "(No text)"
        if self.is_retweet and self.retweeted_tweet:
            title = f"RT @{self.retweeted_tweet.username}: {self.retweeted_tweet.text[:80]}"

        return {
            "title": title,
            "date": self.date_str,
            "link": self.permalink,
            "rss_url": "",  # 非 RSS 来源
            "source_type": "X",
            "source_name": source_name,
            "content": self._build_content_html(),
            # 预填充外链，EnricherStage 会进一步处理
            "extra_content": "",
            "extra_urls": list(self.urls),
        }

    def __str__(self) -> str:
        date = self.date_str or "?"
        text_preview = (self.text[:60] + "...") if len(self.text) > 60 else self.text
        return f"[{date}] @{self.username}: {text_preview}"
