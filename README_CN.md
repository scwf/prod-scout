# Prod Scout - 产品洞察Agent

Prod Scout 是一个专注于 Data & AI 领域（也可扩展应用到其他领域）的产品情报侦察Agent。它基于 RSS 和 LLM 技术，能够自动从 X (Twitter)、微信公众号、YouTube、博客等多种来源抓取信息，并利用大语言模型进行深度解析与结构化整理，最终生成高质量的 Markdown 情报周报。

## ✨ 功能特性

- **多源 RSS 抓取**：支持微信公众号、X (Twitter)、YouTube、博客/新闻等多种来源
- **智能分类**：按来源类型自动分组整理
- **深度内容解析**：自动提取推文或文章中的博客链接和 YouTube 视频，进行递归抓取
- **视频智能转录**：集成 Whisper 模型将X中嵌入的视频或者YouTube视频转换为文本，并使用 DeepSeek/LLM 基于上下文进行字幕优化
- **LLM 智能整理**：调用大模型 API 对抓取内容进行结构化总结
- **Markdown 报告**：自动生成格式清晰的 Markdown 周报
- **灵活配置**：支持自定义 LLM API、时间范围、RSS 源等

## 📁 项目结构

```
prod-scout/
├── config.ini              # 配置文件（LLM API、订阅源等）
├── rsshub-docker.env       # RSSHub Docker 环境变量（用于抓取 X，需配置 TWITTER_AUTH_TOKEN 等）
├── native_scout/           # [Python 原生版] 情报侦察兵（爬虫+整理）
│   ├── pipeline.py         # 主控流水线入口
│   ├── stages/             # 独立的流水线阶段（Fetch, Enrich, Organize, Write）
│   └── utils/              # 通用工具
│       ├── web_crawler.py      # Web 页面抓取 + 截图/PDF
│       └── content_fetcher.py  # 深度内容提取与嵌入资源处理
├── x_scraper/              # [新增] 直接调用 X/Twitter GraphQL API 的爬虫（替代 RSSHub 抓取 X）
│   ├── client.py           # GraphQL API 客户端，支持 TLS 指纹模拟
│   ├── models.py           # 推文数据模型，输出兼容 Pipeline
│   ├── parser.py           # GraphQL 响应解析器
│   ├── account_pool.py     # 多账号轮换与冷却管理
│   └── scraper.py          # 高层编排器与 CLI 入口
├── daft_scout/             # [Daft 版] 高性能分布式侦察兵
│   └── pipeline.py         # Daft 数据流入口
├── video_scribe/           # [通用] 视频转录与字幕优化模块
│   ├── core.py             # 转录核心逻辑
│   ├── optimize.py         # LLM 字幕优化与对齐
│   └── run_video_scribe.py # 独立运行脚本
├── data/                   # 输出目录
│   └── {batch_timestamp}/  # 每次运行创建独立的批次目录
│       ├── raw/            # 原始数据备份 + 视频转录
│       ├── By-Domain/      # 按领域分组的帖子
│       └── By-Entity/      # 按实体分组的帖子
└── README.md
```

## 🚀 快速开始

### 0. 配置 Python 环境（使用 uv）

推荐使用 [uv](https://github.com/astral-sh/uv) 来管理 Python 环境，它比传统的 pip/venv 更快更简单。

#### 安装 uv

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 创建项目虚拟环境

```bash
# 进入项目目录
cd prod-scout

# 创建虚拟环境（自动下载并安装 Python）
uv venv

# 激活虚拟环境
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate
```

> 💡 **提示**：uv 会自动检测并下载合适的 Python 版本，无需手动安装 Python。如需指定版本，可使用 `uv venv --python 3.12`

### 1. 安装依赖

```bash
# 使用 uv 安装依赖（推荐，速度更快）
uv pip install feedparser openai python-dateutil beautifulsoup4 selenium webdriver-manager

# 或使用传统 pip
pip install feedparser openai python-dateutil beautifulsoup4 selenium webdriver-manager
```

### 2. 配置 LLM API

创建 `config.ini` 文件：

```ini
[llm]
api_key = your_api_key_here
base_url = https://api.openai.com/v1
model = gpt-4o
```

支持 OpenAI、DeepSeek、Moonshot、豆包等兼容 OpenAI API 的服务。

### 3. 配置 RSS 源

在 `config.ini` 中配置要抓取的账户：

```ini
[rsshub]
# RSSHub 服务地址
base_url = http://127.0.0.1:1200

[weixin_accounts]
# 微信公众号列表
# 格式：显示名称 = RSS地址
腾讯技术工程 = https://wechat2rss.xlab.app/feed/xxx.xml

[x_accounts]
# X (Twitter) 账户列表
# 格式：显示名称 = 账户ID
karpathy = karpathy
OpenAI = OpenAI
Anthropic = AnthropicAI
```

### 4. 运行

```bash
cd native_scout
python pipeline.py
```

报告将保存至 `data/rss_report_YYYYMMDD_HHMMSS.md`

---

## 🎥 视频转录与深度解析

Prod Scout 内置了强大的 `video_scribe` 模块，能够对抓取内容进行深度挖掘：

### 1. 自动 Video Scribe
当爬虫在推文或文章中发现 YouTube 链接时，会自动触发以下流程：
1.  **自动下载**：提取音频流（无需下载完整视频）。
2.  **Whisper 转录**：使用 `faster-whisper` 模型（支持 GPU 加速）将音频转为字幕。
3.  **Context 感知优化**：利用推文/文章的原始文本作为**上下文 (Context)**，指导 LLM（如 DeepSeek）优化字幕。
    *   *例如：推文中提到了 "Pythagorean theorem"，LLM 会利用此信息修正字幕中识别错误的数学术语。*
    *   同时去除口语赘述（um, uh, I mean），生成如同文章般流畅的文本。

### 2. 深度链接提取
除了视频，爬虫还会自动识别并递归抓取文中嵌入的博客链接：
- 自动过滤社交媒体自身的无关链接
- 使用 Selenium 动态渲染目标网页
- 提取正文内容并合并到情报报告中

### 3. 独立使用 Video Scribe
你也可以单独使用该模块来处理本地文件或 URL：

```bash
# 进入 video_scribe 目录
cd video_scribe

# 运行工具
python run_video_scribe.py
```

> **依赖说明**：`video_scribe` 首次运行时会自动下载所需的依赖文件（如 `faster-whisper` 程序和模型），无需手动配置。Windows 用户请确保已安装 GPU 驱动以获得最佳性能。

---

## 🐦 使用 RSSHub 抓取 X (Twitter)

X 需要通过自建 RSSHub 服务来抓取，以下是配置步骤：

### 第一步：获取你的 X 账号 Cookie

RSSHub 需要模拟你的身份去访问 X。你需要从浏览器中提取几个关键参数。

1. 在 Chrome/Edge 浏览器中打开 x.com 并登录你的账号
2. 按下 `F12` 打开开发者工具，切换到 **Network (网络)** 标签页
3. 刷新一下页面，在列表中随便点一个请求（通常是 `HomeTimeline` 或 `guide.json`）
4. 在右侧的 **Headers (标头)** -> **Request Headers (请求标头)** 中找到 `cookie` 字段
5. 复制出以下两个值（注意不要包含分号）：
   - `auth_token`
   - `ct0` (有时也叫 `x-csrf-token`)

### 第二步：配置环境变量

创建 `rsshub-docker.env` 文件：

```env
TWITTER_AUTH_TOKEN=你的auth_token
TWITTER_CT0=你的ct0
XCSRF_TOKEN=你的ct0
```

### 第三步：运行 RSSHub 容器

```bash
docker run -d --name rsshub -p 1200:1200 --env-file rsshub-docker.env diygod/rsshub:chromium-bundled
```

### 第四步：使用 RSS 源

配置完成后，可以使用以下格式的 RSS 源：

```
http://127.0.0.1:1200/twitter/user/{用户名}
```

例如：`http://127.0.0.1:1200/twitter/user/karpathy`

---

## 📝 输出结构

每次流水线运行会在 `data/` 下创建一个批次目录：

```
data/20260212_210000/
├── raw/                              # 原始备份与视频转录
│   ├── X_OpenAI.json                 # X_OpenAI 的原始帖子
│   ├── WX_机器之心.json               # 微信公众号的原始帖子
│   ├── YT_Databricks.json            # YouTube 的原始帖子
│   └── YT_Databricks_dQw4w9WgXcQ/    # 视频转录文件
│       ├── dQw4w9WgXcQ.srt
│       └── dQw4w9WgXcQ.txt
├── By-Domain/                        # 按领域分组的帖子
│   ├── 大模型技术和产品/
│   │   ├── high/                     # 质量分 >= 4
│   │   │   ├── X_OpenAI_2026-02-04_e4be7e.md
│   │   │   └── WX_机器之心_2026-02-05_a3b8d1.md
│   │   ├── pending/                  # 质量分 2-3
│   │   └── excluded/                 # 质量分 <= 1
│   ├── AI平台和框架/
│   └── .../
├── By-Entity/                        # 按实体分组的帖子（来自 config.ini）
│   ├── OpenAI/
│   ├── Google/
│   ├── Databricks/
│   └── Others/                       # 未匹配到配置实体的帖子
└── batch_manifest.json               # 批次摘要与统计
```

### 帖子文件格式

每个帖子保存为名为 `{source_name}_{date}_{hash}.md` 的 Markdown 文件：

```markdown
# OpenAI开始在ChatGPT中测试广告

- **Date**: 2026-02-09
- **Category**: 产品动态
- **Domain**: 大模型技术和产品
- **Quality**: ⭐⭐⭐⭐⭐ (5/5)
- **Reason**: 重要的商业模式转变，包含全面的隐私保护和安全保障措施说明，涉及产品核心体验调整
- **Source_Type**: X
- **Source**: X_OpenAI
- **Link**: https://x.com/OpenAI/status/2020936703763153010

## Key Info
1. 测试面向美国Free和Go订阅层级用户，Plus/Pro/Business/Enterprise/Education层级无广告<br>2. 广告明确标记为赞助并与有机答案视觉分离，不影响ChatGPT答案的独立性<br>3. 广告商无法访问用户聊天记录、历史、记忆或个人详情，仅接收聚合表现数据<br>4. 不向18岁以下用户展示广告，避开敏感/受监管话题（健康、心理健康、政治）<br>5. 目标是通过广告收入支持更广泛用户免费访问ChatGPT，同时保护用户信任

## Details
OpenAI宣布开始在美国测试ChatGPT中的广告功能。测试面向Free和Go订阅层级的登录成年用户，而Plus、Pro、Business、Enterprise和Education层级不会展示广告。OpenAI强调广告不会 influence ChatGPT的答案，答案始终保持独立性和无偏见性，广告会明确标记为"赞助"并与有机答案视觉分离。在隐私保护方面，广告商无法访问用户的聊天记录、历史、记忆或个人详情，仅能接收广告表现的聚合信息（如浏览量或点击量）。系统不会向18岁以下用户或敏感/受监管话题（如健康、心理健康或政治）附近展示广告。OpenAI表示，此举旨在通过广告收入支持更广泛的用户免费访问ChatGPT，同时保持用户体验和信任。测试阶段将收集反馈以优化体验，未来计划为广告商提供更多格式和购买模式。
```

## 📚 更多 RSS 源

- RSSHub 文档：https://docs.rsshub.app/
- WeChat2RSS：https://wechat2rss.xlab.app/

## 📄 License

MIT
