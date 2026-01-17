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
├── config.ini              # LLM API 配置文件
├── rsshub-docker.env       # RSSHub Docker 环境变量
├── crawler/
│   ├── common.py           # 公共配置和 LLM 整理函数
│   ├── rss_crawler.py      # RSS 信息抓取
│   └── web_crawler.py      # Web 页面抓取 + 截图/PDF
├── data/                   # 输出目录（报告、截图等）
└── README.md
```

## 🚀 快速开始

### 1. 安装依赖

```bash
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

编辑 `crawler/rss_crawler.py` 中的 `rss_sources`：

```python
rss_sources = {
    "weixin": {
        "腾讯技术工程": "https://wechat2rss.xlab.app/feed/xxx.xml",
    },
    "X": {
        "karpathy": "http://127.0.0.1:1200/twitter/user/karpathy",
    },
    "YouTube": {
        # "GoogleAI": "https://rsshub.app/youtube/channel/xxx",
    },
    "blog": {
        # "OpenAI_Blog": "https://rsshub.app/openai/blog",
    },
}
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
# 🌍 RSS 情报周报 (Automated)

## 📂 X

### karpathy

| 日期 | 事件 | 关键信息 | 分类 |
|------|------|----------|------|
| 2026-01-17 | 分享 LLM 训练心得 | 1. 推荐使用... | 观点分享 |

---
```

## 📚 更多 RSS 源

- RSSHub 文档：https://docs.rsshub.app/
- WeChat2RSS：https://wechat2rss.xlab.app/

## 📄 License

MIT
