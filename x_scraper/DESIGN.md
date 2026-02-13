# X Scraper 模块设计文档

> **版本**: v1.0  
> **日期**: 2026-02-13  
> **状态**: 设计中

## 1. 背景与目标

### 1.1 现状分析

当前 Prod Scout 项目通过 **RSSHub 自建服务** 抓取 X (Twitter) 用户推文。该方案存在以下痛点：

| 痛点 | 说明 |
|------|------|
| **基础设施依赖** | 需要维护 Docker 容器运行 RSSHub 服务，增加运维复杂度 |
| **单点认证风险** | 依赖单个 `auth_token` + `ct0`，一旦 Token 过期/被封，所有 X 源全部失效 |
| **数据受限** | RSSHub 返回的是标准 RSS Feed，部分推文元数据（浏览量、书签数、Quote 等）丢失 |
| **灵活性不足** | 无法控制抓取粒度（如仅回复、仅原创、仅含媒体的推文），也无法获取推文的上下文对话 |

### 1.2 目标

构建一个 **独立、可复用** 的 X 用户推文爬取模块 `x_scraper`，实现：

1. **去 RSSHub 依赖**：直接通过 X 内部 GraphQL API 获取用户推文，不再需要 RSSHub Docker 服务
2. **数据更丰富**：获取与网页端完全一致的数据，包括互动指标、引用推文、媒体附件等
3. **多账号轮换**：内置 Cookie 账号池管理，自动轮换，降低单账号风控风险
4. **无缝集成**：输出格式与现有 `FetcherStage` 的 post 字典兼容，可直接接入 Pipeline
5. **独立可运行**：也可作为独立工具脚本使用，不依赖 Pipeline 的其他部分

## 2. 技术选型

### 2.1 方案对比

基于参考文档《X用户推文爬取方案研究》中的五种方案，结合项目实际需求进行选型：

| 方案 | 成本 | 稳定性 | 数据丰富度 | 维护难度 | 适合本项目 |
|------|------|--------|-----------|---------|-----------|
| 官方 API v2 | ❌ Pro 层 $5000/月 | ✅ 高 | ⚠️ 中 | ✅ 低 | ❌ 成本不可接受 |
| **内部 API 逆向** | **✅ ~0** | **⚠️ 中** | **✅ 高** | **⚠️ 中** | **✅ 最佳选择** |
| AI Agent (ElizaOS) | ✅ ~0 | ⚠️ 中 | ✅ 高 | ⚠️ 中 | ❌ TypeScript 技术栈不匹配 |
| 浏览器自动化 | ✅ ~0 | ❌ 低 | ✅ 高 | ❌ 高 | ❌ 性能太差, 不适合批量抓取 |
| 商业服务 (Apify) | ⚠️ 中 | ✅ 高 | ✅ 高 | ✅ 低 | ⚠️ 备选方案 |

### 2.2 最终选择：内部 GraphQL API 逆向 (自研轻量客户端)

**理由**：
- 项目已有 `auth_token` + `ct0` 凭证（在 `rsshub-docker.env` 中）
- Python 技术栈与项目一致
- 成本为零，数据丰富度最高
- 虽然存在"军备竞赛"风险，但我们的抓取量级小（90+ 账号，日频/周频），被风控的概率低

**不使用 twscrape/twikit 等第三方库的理由**：
- 这些库功能过于庞大（含搜索、Space、Lists 等），我们只需要 User Timeline
- 第三方库的更新频率不可控，一旦 X 更新 API 而库未跟进，整个模块瘫痪
- 自研轻量客户端更易于理解、调试和快速适配 X 的 API 变更
- 核心逻辑仅需 ~200 行代码（构造请求头 + 发送 GraphQL 请求 + 解析响应）

### 2.3 关键技术点

1. **TLS 指纹伪装**：使用 `curl_cffi` 替代 `requests`，模拟真实浏览器的 TLS JA3 指纹
2. **GraphQL 请求构造**：逆向 X 前端 `UserTweets` endpoint 的请求结构
3. **Cookie 轮换**：支持多套 `auth_token` + `ct0` 凭证，自动轮换
4. **游标分页 (Cursor Pagination)**：处理 X 独特的 timeline cursor 分页机制
5. **请求限速**：可配置的随机延迟，避免触发速率限制

## 3. 架构设计

### 3.1 模块结构

```
x_scraper/
├── __init__.py           # 模块导出
├── client.py             # 核心 X API 客户端（GraphQL 请求）
├── models.py             # Tweet 数据模型
├── account_pool.py       # 账号池管理（Cookie 轮换）
├── parser.py             # GraphQL 响应解析器
├── scraper.py            # 上层爬取编排逻辑（面向用户的入口）
├── DESIGN.md             # 本设计文档
└── README.md             # 使用说明
```

### 3.2 核心类设计

```
┌─────────────────────────────────────────────────────────────┐
│                     XScraper (scraper.py)                    │
│  - 面向用户的高层 API                                         │
│  - fetch_user_tweets(username, limit, since_date)            │
│  - fetch_multiple_users(usernames, ...)                      │
│  - 输出兼容 Pipeline 的 post dict                             │
├─────────────────────────────────────────────────────────────┤
│                     XClient (client.py)                      │
│  - 封装 GraphQL HTTP 请求                                     │
│  - 处理认证头、CSRF Token                                     │
│  - 使用 curl_cffi 发送请求（TLS 指纹伪装）                      │
│  - 处理限速/重试逻辑                                           │
├─────────────────────────────────────────────────────────────┤
│              AccountPool (account_pool.py)                    │
│  - 管理多个 auth_token + ct0 组合                              │
│  - 轮换策略 + 冷却机制                                         │
│  - 从 config.ini 配置加载                                     │
├─────────────────────────────────────────────────────────────┤
│              TweetParser (parser.py)                          │
│  - 解析 GraphQL Timeline 响应 JSON                            │
│  - 提取 Tweet 数据、游标(Cursor)                               │
│  - 处理 Pinned/Promoted 过滤                                  │
├─────────────────────────────────────────────────────────────┤
│              Tweet / TweetMedia (models.py)                   │
│  - Tweet dataclass 定义                                       │
│  - 序列化为 Pipeline 兼容的 post dict                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 数据流

```
config.ini [x_accounts] + [x_scraper]
            │
            ▼
    ┌──────────────┐
    │  XScraper     │ ← 读取账号列表 + 爬取配置
    │  (scraper.py) │
    └──────┬───────┘
           │ 遍历用户列表
           ▼
    ┌──────────────┐     ┌──────────────┐
    │  XClient      │◄────│ AccountPool   │ ← 提供当前可用的 auth 凭证
    │  (client.py)  │     │              │
    └──────┬───────┘     └──────────────┘
           │ GraphQL HTTP Request
           │ (curl_cffi, TLS 伪装)
           ▼
    ┌──────────────┐
    │  X Platform   │ ← UserTweets GraphQL Endpoint
    │  (x.com)      │
    └──────┬───────┘
           │ JSON Response
           ▼
    ┌──────────────┐
    │ TweetParser   │ ← 解析 timeline JSON，提取 Tweet + Cursor
    │ (parser.py)   │
    └──────┬───────┘
           │ List[Tweet]
           ▼
    ┌──────────────┐
    │ Tweet Model   │ ← to_post_dict() 转换为 Pipeline 兼容格式
    │ (models.py)   │
    └──────┬───────┘
           │ List[dict]  (与 FetcherStage 的 post 格式一致)
           ▼
    ┌──────────────────────────────────────┐
    │ 输出：                                │
    │ 1. 独立模式: 保存 JSON 文件            │
    │ 2. Pipeline 集成: 放入 fetch_queue    │
    └──────────────────────────────────────┘
```

## 4. 数据模型

### 4.1 Tweet Dataclass

```python
@dataclass
class Tweet:
    id: str                      # 推文 ID
    text: str                    # 推文全文
    created_at: datetime         # 发布时间
    user_id: str                 # 用户 ID
    username: str                # 用户名 (@handle)
    display_name: str            # 显示名称
    
    # 互动指标
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0
    view_count: int = 0
    bookmark_count: int = 0
    quote_count: int = 0
    
    # 内容附件
    urls: List[str]              # 正文中的外链
    media: List[TweetMedia]      # 图片/视频附件
    
    # 引用/转发
    is_retweet: bool = False
    is_quote: bool = False
    quoted_tweet: Optional['Tweet'] = None
    
    # 对话上下文
    in_reply_to_id: Optional[str] = None
    conversation_id: Optional[str] = None
    
    lang: str = ""               # 语言代码
    source: str = ""             # 发布客户端
    
    def to_post_dict(self, source_name: str) -> dict:
        """转换为 Pipeline FetcherStage 兼容的 post 字典"""
        return {
            "title": self.text[:100],
            "date": self.created_at.strftime("%Y-%m-%d"),
            "link": f"https://x.com/{self.username}/status/{self.id}",
            "rss_url": "",
            "source_type": "X",
            "source_name": source_name,
            "content": self._build_content_html(),
            "extra_content": "",
            "extra_urls": self.urls,
        }
```

### 4.2 Pipeline 兼容性

输出的 `post dict` 与现有 `FetcherStage._fetch_recent_posts()` 产出的格式 **完全一致**：

```python
{
    "title": str,           # 推文文本前100字
    "date": str,            # "YYYY-MM-DD"
    "link": str,            # 推文永久链接
    "rss_url": str,         # 空字符串（非 RSS 来源）
    "source_type": "X",     # 固定为 "X"
    "source_name": str,     # 如 "X_OpenAI"
    "content": str,         # 推文 HTML 内容
    "extra_content": "",    # 由 EnricherStage 填充
    "extra_urls": [],       # 由 EnricherStage 填充 (或由 Tweet.urls 预填)
}
```

## 5. 配置设计

在 `config.ini` 中新增 `[x_scraper]` 配置节：

```ini
[x_scraper]
# 是否启用 x_scraper 替代 RSSHub 方式获取 X 推文
# true = 使用 x_scraper 直接抓取, false = 继续使用 RSSHub RSS
enabled = true

# 账号凭证（支持多个，用分号分隔进行轮换）
# 格式: auth_token:ct0
# 可配置多个凭证实现轮换，降低风控风险
auth_credentials = AUTH_TOKEN_1:CT0_1;AUTH_TOKEN_2:CT0_2

# 每个用户抓取的推文上限
max_tweets_per_user = 20

# 请求间延迟 (秒) — 随机化范围
request_delay_min = 3
request_delay_max = 8

# 用户切换间延迟 (秒) — 不同用户之间的间隔
user_switch_delay_min = 10
user_switch_delay_max = 30

# 请求超时 (秒)
request_timeout = 30

# 最大重试次数
max_retries = 3

# 是否包含转推 (Retweets)
include_retweets = false

# 是否包含回复
include_replies = false
```

## 6. 核心实现要点

### 6.1 GraphQL 请求构造

X 前端使用的 `UserTweets` GraphQL endpoint 结构如下：

```
GET https://x.com/i/api/graphql/{query_id}/UserTweets
```

关键请求头：

```python
headers = {
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xn...",  # 固定的 Web Bearer Token
    "x-csrf-token": ct0,           # 从 Cookie 中获取
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-client-language": "en",
    "content-type": "application/json",
}

cookies = {
    "auth_token": auth_token,
    "ct0": ct0,
}
```

GraphQL 查询参数（URL encoded JSON）：

```python
variables = {
    "userId": user_id,          # 需先通过 UserByScreenName 获取
    "count": 20,                # 每页推文数
    "cursor": cursor,           # 分页游标（首次请求为空）
    "includePromotedContent": False,
    "withQuickPromoteEligibilityTweetFields": True,
    "withVoice": True,
    "withV2Timeline": True,
}

features = {
    "profile_label_improvements_pcf_label_in_post_enabled": False,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    # ... (约20+ feature flags, 从浏览器 DevTools 获取)
}
```

### 6.2 TLS 指纹伪装

使用 `curl_cffi` 库替代标准 `requests`：

```python
from curl_cffi import requests as curl_requests

response = curl_requests.get(
    url,
    headers=headers,
    cookies=cookies,
    impersonate="chrome131",  # 模拟 Chrome 131 的 TLS 指纹
    timeout=30,
)
```

### 6.3 账号池轮换策略

```python
class AccountPool:
    def __init__(self, credentials: List[Tuple[str, str]]):
        self.accounts = [
            {"auth_token": at, "ct0": ct, "cooldown_until": 0, "request_count": 0}
            for at, ct in credentials
        ]
        self.current_index = 0
    
    def get_next(self) -> dict:
        """获取下一个可用账号（跳过冷却中的账号）"""
        ...
    
    def mark_rate_limited(self, index: int, cooldown_seconds: int = 900):
        """标记账号被限速，进入冷却期"""
        ...
```

### 6.4 响应解析

GraphQL 响应的 JSON 结构层级较深，需要递归解析 `TimelineEntry` → `TweetResult` → `Legacy` 对象：

```
response.data.user.result.timeline_v2.timeline.instructions[]
  → type: "TimelineAddEntries"
    → entries[]
      → content.entryType: "TimelineTimelineItem"
        → content.itemContent.tweet_results.result
          → legacy  ← 推文主体数据
          → core.user_results.result.legacy  ← 用户数据
```

### 6.5 错误处理与容错

| 错误类型 | 处理策略 |
|---------|---------|
| 429 Too Many Requests | 当前账号进入冷却期(15min)，切换下一个账号 |
| 401 Unauthorized | Token 过期，标记账号失效，输出警告日志 |
| 403 Forbidden | 目标用户可能已设为私密，跳过并记录 |
| JSON 解析失败 | 可能 API 结构变更，记录原始响应用于调试 |
| 网络超时 | 重试 (最多 3 次)，指数退避 |

## 7. 集成方案

### 7.1 独立使用 (CLI 模式)

```bash
cd x_scraper
python scraper.py
```

将读取 `config.ini` 中的 `[x_accounts]` 列表，逐个抓取推文并保存到 `data/` 目录。

### 7.2 集成到 Pipeline

在 `native_scout/stages/source_fetcher.py` 中，根据 `[x_scraper] enabled` 配置决定数据来源：

```python
# source_fetcher.py
def start(self, rss_sources):
    # ... weixin, youtube 部分不变
    
    # X (Twitter)
    if self.config.getboolean('x_scraper', 'enabled', fallback=False):
        # 使用 x_scraper 直接抓取
        from x_scraper import XScraper
        self.futures.append(
            self.restricted_pool.submit(self._fetch_x_via_scraper, rss_sources.get("X", {}))
        )
    else:
        # 原有 RSSHub 方式
        for name, url in rss_sources.get("X", {}).items():
            self.futures.append(
                self.restricted_pool.submit(self._fetch_x_task, url, "X", name)
            )
```

### 7.3 数据流集成图

```
                    ┌─ config.ini [x_scraper] enabled = true ──┐
                    │                                           │
                    ▼                                           ▼
            ┌──────────────┐                          ┌──────────────┐
 新路径 ─►  │  XScraper     │              旧路径 ─►   │  RSSHub       │
            │  (x_scraper/) │                          │  (Docker)     │
            └──────┬───────┘                          └──────┬───────┘
                   │ List[post_dict]                         │ RSS Feed
                   ▼                                         ▼
            ┌─────────────────────────────────────────────────┐
            │              FetcherStage.fetch_queue            │
            │         (统一的 post dict 格式)                    │
            └──────────────────┬──────────────────────────────┘
                               ▼
            ┌─────────────────────────────────────────────────┐
            │  EnricherStage → OrganizerStage → WriterStage   │
            │         (后续 Pipeline 完全不变)                   │
            └─────────────────────────────────────────────────┘
```

## 8. 依赖管理

新增的 Python 依赖：

```
curl_cffi>=0.7.0       # TLS 指纹伪装的 HTTP 客户端 (替代 requests)
```

> `curl_cffi` 是唯一的新依赖。数据解析、模型等均使用 Python 标准库。

## 9. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| X 更新 GraphQL query_id | 高 (每月数次) | 临时失效 | 实现自动从 JS Bundle 中提取最新 query_id 的逻辑 |
| X 更新 feature flags | 中 | 请求失败 | 记录错误响应，feature flags 配置外置便于快速更新 |
| 账号被封/限速 | 中 | 部分账号不可用 | 多账号轮换 + 冷却机制 + 保守的请求间隔 |
| TLS 指纹检测升级 | 低 | 全部失效 | curl_cffi 持续更新；备选方案：Playwright stealth |
| 法律合规风险 | 低 | / | 仅抓取公开推文，用于个人情报分析，不做商业转售 |

## 10. 实施计划

### Phase 1: 核心模块 (本次实现)
- [x] `models.py` - Tweet 数据模型
- [x] `client.py` - GraphQL 客户端
- [x] `parser.py` - 响应解析器
- [x] `account_pool.py` - 账号池
- [x] `scraper.py` - 上层编排 + CLI
- [x] `__init__.py` - 模块导出

### Phase 2: Pipeline 集成 (后续)
- [ ] 修改 `source_fetcher.py` 增加 x_scraper 路径
- [ ] 修改 `pipeline.py` 的 `_load_sources()` 适配新配置
- [ ] 端到端测试

### Phase 3: 增强功能 (长期)
- [ ] 自动从 X 前端 JS Bundle 提取最新 `query_id`
- [ ] 支持抓取 Quote Tweets / Replies
- [ ] 支持关键词搜索
- [ ] 支持 Webhook 通知 (新推文告警)
