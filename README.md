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
├── rsshub-docker.env       # RSSHub Docker 环境变量，用于抓取X，需配置TWITTER_AUTH_TOKEN等
├── native_scout/           # [Python 原生版] 情报侦察兵（爬虫+整理）
│   ├── pipeline.py         # 主控流水线入口
│   ├── stages/             # 独立的流水线阶段（Fetch, Enrich, Organize, Write）
│   └── utils/              # 通用工具
│       ├── web_crawler.py      # Web 页面抓取 + 截图/PDF
│       └── content_fetcher.py  # 深度内容提取与嵌入资源处理
├── daft_scout/             # [Daft 版] 高性能分布式侦察兵
│   └── pipeline.py         # Daft 数据流入口
├── video_scribe/           # [通用] 视频转录与字幕优化模块
│   ├── core.py             # 转录核心逻辑
│   ├── optimize.py         # LLM 字幕优化与对齐
│   └── run_video_scribe.py # 独立运行脚本
├── data/                   # 输出目录（报告、截图、转录文件等）
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

## 📝 输出示例

```markdown
# 🌍 Data&AI 情报周报 (Automated RSS Crawler)

## 📂 weixin

### 腾讯技术工程

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 补充内容 | 外部链接 | 事件分类 | 所属领域 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-01-15 | 鹅厂员工分享AI Coding防坑技巧 | 1. 内容汇集了10位腾讯工程师的实践经验。<br>2. 核心建议包括：使用高质量模型、优先Commit备份等。 | [原文链接](https://mp.weixin.qq.com/s?...) | 文章围绕AI编程实践中的"翻车"经历与防坑技巧展开... | - | - | 观点分享 | 代码智能体（IDE） |
| 2026-01-13 | 腾讯开源AngelSlim工具包 | 1. 腾讯混元团队升级并开源了大模型压缩算法工具包AngelSlim。<br>2. 可使大模型推理速度最高提升1.4-1.9倍。 | [原文链接](https://mp.weixin.qq.com/s?...) | 文章宣布腾讯AngelSlim工具包完成重磅升级... | - | - | 技术发布 | 大模型技术和产品 |

---

## 📂 X

### AI Researcher (Andrej)

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 补充内容 | 外部链接 | 事件分类 | 所属领域 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-02-01 | 解析 LLM 训练新范式 | 1. 视频核心观点：SFT 数据质量比数量更重要。<br>2. 深度抓取：博客文章详细论述了 "Token 效率"。<br>3. 提到未来趋势是小模型 + 高质量数据。 | [原文链接](https://x.com/karpathy/...) | Andrej 深入分析了当前大模型训练中 SFT 阶段的数据策略... | **[视频解析]** Andrej 在视频中详细解释了... (基于 Video Scribe 转录)<br>**[博客摘要]** 随附文章深入探讨了... | [karpathy.ai](https://karpathy.ai) | 深度观点 | 大模型技术和产品 |

### MLflow

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 补充内容 | 外部链接 | 事件分类 | 所属领域 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-01-16 | 发布播客，探讨MLflow向GenAI平台转型 | 1. 视频内容：MLflow 团队讨论了向 AI Agent 平台的演进。<br>2. 关键挑战：评估(Evaluation)和治理(Governance)是目前企业落地的痛点。 | [原文链接](https://x.com/MLflow/...) | MLflow 团队发布了一期新的播客节目，专注于探讨... | **[视频智能转录]** 播客中详细讨论了...<br>MLflow isn't just for traditional data scientists anymore... | - | 技术发布 | AI平台和框架 |

---
```

## 📚 更多 RSS 源

- RSSHub 文档：https://docs.rsshub.app/
- WeChat2RSS：https://wechat2rss.xlab.app/

## 📄 License

MIT
