# Crawl Nova - 多源数据抓取与智能整理工具

一个基于 RSS 和 LLM 的信息聚合工具，支持从 X (Twitter)、微信公众号、YouTube、博客等多种来源抓取内容，并使用大语言模型进行结构化整理，生成 Markdown 格式的情报周报。

## ✨ 功能特性

- **多源 RSS 抓取**：支持微信公众号、X (Twitter)、YouTube、博客/新闻等多种来源
- **智能分类**：按来源类型自动分组整理
- **LLM 智能整理**：调用大模型 API 对抓取内容进行结构化总结
- **Markdown 报告**：自动生成格式清晰的 Markdown 周报
- **灵活配置**：支持自定义 LLM API、时间范围、RSS 源等

## 📁 项目结构

```
crawl-nova/
├── config.ini              # 配置文件（LLM API、RSSHub、订阅源等）
├── rsshub-docker.env       # RSSHub Docker 环境变量
├── crawler/
│   ├── common.py           # 公共配置和 LLM 整理函数
│   ├── rss_crawler.py      # RSS 信息抓取
│   └── web_crawler.py      # Web 页面抓取 + 截图/PDF
├── data/                   # 输出目录（报告、截图等）
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
cd crawl-nova

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
cd crawler
python rss_crawler.py
```

报告将保存至 `data/rss_report_YYYYMMDD_HHMMSS.md`

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

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-01-15 | 鹅厂员工分享AI Coding防坑技巧 | 1. 内容汇集了10位腾讯工程师的实践经验。<br>2. 核心建议包括：使用高质量模型、优先Commit备份等。 | [原文链接](https://mp.weixin.qq.com/s?...) | 文章围绕AI编程实践中的"翻车"经历与防坑技巧展开... | 观点分享 |
| 2026-01-13 | 腾讯开源AngelSlim工具包 | 1. 腾讯混元团队升级并开源了大模型压缩算法工具包AngelSlim。<br>2. 可使大模型推理速度最高提升1.4-1.9倍。 | [原文链接](https://mp.weixin.qq.com/s?...) | 文章宣布腾讯AngelSlim工具包完成重磅升级... | 技术发布 |

---

## 📂 X

### cowork creator

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-01-16 | 发布Cowork多项功能改进与修复 | 1. 新增安全功能：删除操作需用户明确授权。<br>2. 增强文件管理：可在对话中创建文件夹。 | [原文链接](https://x.com/felixrieseberg/...) | More Cowork improvements shipped today! We've taught Claude to always request explicit permission before deleting anything... | 技术发布 |
| 2026-01-16 | Claude Cowork扩展至Pro订阅用户 | 1. 产品覆盖范围扩大，Pro订阅用户现可使用。 | [原文链接](https://x.com/felixrieseberg/...) | Claude Cowork is now available to Pro subscribers, too! Give it a try and let us know how you'd like to see it improve. | 商业动态 |

### MLflow

| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-01-16 | 发布播客，探讨MLflow向GenAI平台转型 | 1. MLflow正在为AI代理和生产系统进行重构。<br>2. 讨论了评估、风险内存管理和治理等挑战。 | [原文链接](https://x.com/MLflow/...) | MLflow isn't just for traditional data scientists anymore. If you're an AI engineer or agent developer building GenAI applications... | 技术发布 |

---
```

## 📚 更多 RSS 源

- RSSHub 文档：https://docs.rsshub.app/
- WeChat2RSS：https://wechat2rss.xlab.app/

## 📄 License

MIT
