# Prod Scout - Product Insight Agent

Prod Scout is a product intelligence reconnaissance agent focused on the Data & AI domain (extensible to other fields). Based on RSS and LLM technologies, it automatically fetches information from various sources such as X (Twitter), WeChat Official Accounts, YouTube, and blogs. It utilizes Large Language Models for deep analysis and structured organization, ultimately generating high-quality Markdown intelligence weekly reports.

## ✨ Features

- **Multi-source RSS Fetching**: Supports WeChat Official Accounts, X (Twitter), YouTube, Blogs/News, etc.
- **Smart Classification**: Automatically groups and organizes content by source type.
- **Deep Content Parsing**: Automatically extracts blog links and YouTube videos from tweets or articles for recursive fetching.
- **Intelligent Video Transcription**: Integrates Whisper model to convert embedded videos in X or YouTube videos into text, and uses DeepSeek/LLM for context-aware subtitle optimization.
- **LLM Intelligent Organization**: Calls LLM APIs to structurally summarize fetched content.
- **Markdown Reports**: Automatically generates clear and structured Markdown weekly reports.
- **Flexible Configuration**: Supports custom LLM APIs, time ranges, RSS sources, etc.

## 📁 Project Structure

```
prod-scout/
├── config.ini              # Configuration file (LLM API, subscription sources, etc.)
├── rsshub-docker.env       # RSSHub Docker environment variables (for fetching X, requires TWITTER_AUTH_TOKEN, etc.)
├── native_scout/           # [Python Native Version] Intelligence Scout (Crawler + Organizer)
│   ├── pipeline.py         # Main pipeline entry point
│   ├── stages/             # Independent pipeline stages (Fetch, Enrich, Organize, Write)
│   └── utils/              # General utilities
│       ├── web_crawler.py      # Web page fetching + Screenshot/PDF
│       └── content_fetcher.py  # Deep content extraction and embedded resource handling
├── x_scraper/              # [New] Direct X/Twitter GraphQL API scraper (replaces RSSHub for X)
│   ├── client.py           # GraphQL API client with TLS fingerprint impersonation
│   ├── models.py           # Tweet data models with Pipeline-compatible output
│   ├── parser.py           # GraphQL response parser
│   ├── account_pool.py     # Multi-credential rotation & cooldown manager
│   └── scraper.py          # High-level orchestrator & CLI entry point
├── daft_scout/             # [Daft Version] High-performance distributed Scout
│   └── pipeline.py         # Daft data flow entry point
├── video_scribe/           # [General] Video transcription and subtitle optimization module
│   ├── core.py             # Core logic for transcription
│   ├── optimize.py         # LLM subtitle optimization and alignment
│   └── run_video_scribe.py # Standalone execution script
├── data/                   # Output directory
│   └── {batch_timestamp}/  # Each run creates an isolated batch directory
│       ├── raw/            # Raw data backups + video transcripts
│       ├── By-Domain/      # Posts organized by domain
│       └── By-Entity/      # Posts organized by entity
└── README.md
```

## 🚀 Quick Start

### 0. Configure Python Environment (Using uv)

It is recommended to use [uv](https://github.com/astral-sh/uv) to manage the Python environment, as it is faster and simpler than traditional pip/venv.

#### Install uv

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Create Project Virtual Environment

```bash
# Enter project directory
cd prod-scout

# Create virtual environment (automatically downloads and installs Python)
uv venv

# Activate virtual environment
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate
```

> 💡 **Tip**: uv will automatically detect and download a suitable Python version, no need to manually install Python. To specify a version, use `uv venv --python 3.12`.

### 1. Install Dependencies

```bash
# Install dependencies using uv (recommended, faster)
uv pip install feedparser openai python-dateutil beautifulsoup4 selenium webdriver-manager

# Or using traditional pip
pip install feedparser openai python-dateutil beautifulsoup4 selenium webdriver-manager
```

### 2. Configure LLM API

Create a `config.ini` file:

```ini
[llm]
api_key = your_api_key_here
base_url = https://api.openai.com/v1
model = gpt-4o
```

Supports OpenAI, DeepSeek, Moonshot, Doubao, and other OpenAI API compatible services.

### 3. Configure RSS Sources

Configure accounts to fetch in `config.ini`:

```ini
[rsshub]
# RSSHub service address
base_url = http://127.0.0.1:1200

[weixin_accounts]
# WeChat Official Accounts list
# Format: Display Name = RSS Address
TencentTech = https://wechat2rss.xlab.app/feed/xxx.xml

[x_accounts]
# X (Twitter) Accounts list
# Format: Display Name = Account ID
karpathy = karpathy
OpenAI = OpenAI
Anthropic = AnthropicAI
```

### 4. Run

```bash
cd native_scout
python pipeline.py
```

The report will be saved to `data/rss_report_YYYYMMDD_HHMMSS.md`.

---

## 🎥 Video Transcription & Deep Analysis

Prod Scout includes a powerful `video_scribe` module for deep content mining:

### 1. Automated Video Scribe
When the crawler finds a YouTube link in a tweet or article, it automatically triggers the following workflow:
1.  **Auto Download**: Extracts audio stream (no need to download the full video).
2.  **Whisper Transcription**: Uses `faster-whisper` model (supports GPU acceleration) to convert audio to subtitles.
3.  **Context-Aware Optimization**: Uses the original text of the tweet/article as **context** to guide the LLM (e.g., DeepSeek) in optimizing the subtitles.
    *   *Example: If "Pythagorean theorem" is mentioned in the tweet, the LLM will use this information to correct any misidentified mathematical terms in the subtitles.*
    *   Also removes filler words (um, uh, I mean) to generate fluent, article-like text.

### 2. Deep Link Extraction
In addition to videos, the crawler also automatically identifies and recursively fetches embedded blog links:
- Automatically filters out irrelevant social media links.
- Uses Selenium to dynamically render target web pages.
- Extracts main content and merges it into the intelligence report.

### 3. Standalone Use of Video Scribe
You can also use this module independently to process local files or URLs:

```bash
# Enter video_scribe directory
cd video_scribe

# Run the tool
python run_video_scribe.py
```

> **Dependency Note**: `video_scribe` will automatically download required dependencies (such as the `faster-whisper` program and models) on its first run, no manual configuration needed. Windows users please ensure GPU drivers are installed for optimal performance.

---

## 🐦 Fetching X (Twitter) using RSSHub

X needs to be fetched via a self-hosted RSSHub service. Here are the configuration steps:

### Step 1: Get Your X Account Cookie

RSSHub needs to simulate your identity to access X. You need to extract a few key parameters from your browser.

1. Open x.com in Chrome/Edge browser and log in to your account.
2. Press `F12` to open Developer Tools, switch to the **Network** tab.
3. Refresh the page and click on any request in the list (usually `HomeTimeline` or `guide.json`).
4. In the **Headers** -> **Request Headers** section on the right, find the `cookie` field.
5. Copy the following two values (make sure not to include the semicolon):
   - `auth_token`
   - `ct0` (sometimes called `x-csrf-token`)

### Step 2: Configure Environment Variables

Create an `rsshub-docker.env` file:

```env
TWITTER_AUTH_TOKEN=your_auth_token
TWITTER_CT0=your_ct0
XCSRF_TOKEN=your_ct0
```

### Step 3: Run RSSHub Container

```bash
docker run -d --name rsshub -p 1200:1200 --env-file rsshub-docker.env diygod/rsshub:chromium-bundled
```

### Step 4: Use RSS Source

After configuration, you can use RSS sources in the following format:

```
http://127.0.0.1:1200/twitter/user/{username}
```

Example: `http://127.0.0.1:1200/twitter/user/karpathy`

---

## 📝 Output Structure

Each pipeline run creates a batch directory under `data/`:

```
data/20260212_210000/
├── raw/                              # Raw backups & video transcripts
│   ├── X_OpenAI.json                 # Raw posts from X_OpenAI
│   ├── WX_机器之心.json               # Raw posts from WeChat
│   ├── YT_Databricks.json            # Raw posts from YouTube
│   └── YT_Databricks_dQw4w9WgXcQ/    # Video transcript files
│       ├── dQw4w9WgXcQ.srt
│       └── dQw4w9WgXcQ.txt
├── By-Domain/                        # Posts grouped by domain
│   ├── 大模型技术和产品/
│   │   ├── high/                     # Quality score >= 4
│   │   │   ├── X_OpenAI_2026-02-04_e4be7e.md
│   │   │   └── WX_机器之心_2026-02-05_a3b8d1.md
│   │   ├── pending/                  # Quality score 2-3
│   │   └── excluded/                 # Quality score <= 1
│   ├── AI平台和框架/
│   └── .../
├── By-Entity/                        # Posts grouped by entity (from config.ini)
│   ├── OpenAI/
│   ├── Google/
│   ├── Databricks/
│   └── Others/                       # Posts not matching any configured entity
└── batch_manifest.json               # Batch summary & statistics
```

### Post File Format

Each post is saved as a Markdown file named `{source_name}_{date}_{hash}.md`:

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

## 📚 More RSS Sources

- RSSHub Documentation: https://docs.rsshub.app/
- WeChat2RSS: https://wechat2rss.xlab.app/

## 📄 License

MIT
