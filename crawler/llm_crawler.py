"""
llm_crawler.py - 多源数据抓取与信息整理工具

功能概述：
1. RSS 订阅抓取：支持从 RSSHub 等源抓取最新更新（如 Twitter, YouTube, 博客）。
2. Web 内容抓取：使用 Selenium 抓取普通网页内容。
3. 智能截图与归档：支持生成网页长截图 (PNG) 和高保真 PDF 存档，自动处理懒加载和长页面。
4. LLM 整理总结：调用大模型 API 对抓取内容进行结构化整理。

输入：
- 配置区域的 RSS 源列表 (rss_sources)
- 配置区域的 Web URL 列表 (web_sources)

输出：
- 控制台打印的结构化情报简报 (Markdown 格式)
- data/ 目录下的网页快照 (PNG 长图)
- data/ 目录下的网页存档 (PDF)

依赖：selenium, feedparser, openai, beautifulsoup4
"""
import feedparser
import base64
from datetime import datetime, timedelta, timezone
from dateutil import parser as date_parser
from openai import OpenAI
import os
import configparser
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time

# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'), encoding='utf-8')

# ================= 配置区域 =================
# 1. 设置 LLM API (从 config.ini 配置文件读取)
client = OpenAI(
    api_key=config.get('llm', 'api_key'), 
    base_url=config.get('llm', 'base_url')  # 如果是用中转或者其他模型，修改 config.ini 文件
)

# 2. 设置 RSSHub 的订阅源 (关键步骤)
# 提示：X (Twitter) 和 YouTube 的路由可以在 https://docs.rsshub.app/ 找到
rss_sources = {
    # "36Kr_News": "https://rsshub.app/36kr/newsflashes", # 36氪快讯
    # "OpenAI_Blog": "https://rsshub.app/openai/blog",    # OpenAI 官方博客
    # 注意：微博/X 可能需要自建 RSSHub 服务或配置 Cookie 才能稳定抓取
    # "ElonMusk_X": "http://127.0.0.1:1200/twitter/user/elonmusk", 
    "腾讯技术工程": "https://wechat2rss.xlab.app/feed/9685937b45fe9c7a526dbc32e4f24ba879a65b9a.xml",
}

# 3. 设置普通 Web URL 抓取源 (新增)
# 适用于没有 RSS 的单页面，如具体的一篇博文或静态页面
web_sources = {
    # "Qwen_blog": "https://qwen.ai/research",
    # "DeepMind_About": "https://deepmind.google/about/",
}

# 3. 设置时间范围 (最近 7 天)
DAYS_LOOKBACK = 7
# ===========================================

def fetch_recent_posts(rss_url, days):
    """
    抓取 RSS 并筛选指定天数内的内容
    """
    print(f"正在抓取: {rss_url} ...")
    try:
        feed = feedparser.parse(rss_url)
        recent_posts = []
        
        # 获取当前时间 (带时区感知，默认为 UTC 以便比较)
        now = datetime.now(timezone.utc)
        
        for entry in feed.entries:
            # 解析发布时间
            if hasattr(entry, 'published'):
                post_date = date_parser.parse(entry.published)
            elif hasattr(entry, 'updated'):
                post_date = date_parser.parse(entry.updated)
            else:
                continue # 没有时间戳跳过

            # 确保 post_date 有时区信息，如果没有则设为 UTC
            if post_date.tzinfo is None:
                post_date = post_date.replace(tzinfo=timezone.utc)
            
            # 计算时间差
            if (now - post_date).days <= days:
                # 清洗数据，提取标题、链接和摘要
                content = entry.get('summary', '') or entry.get('description', '')
                # 简单去除 HTML 标签 (可选，LLM 其实能读懂 HTML，但纯文本更省 Token)
                # 这里简单处理，保留原始文本给 LLM 也可以
                
                recent_posts.append({
                    "title": entry.title,
                    "date": post_date.strftime("%Y-%m-%d"),
                    "link": entry.link,
                    "content_snippet": content[:500] # 截取前500字符防止 Token 溢出
                })
                
        return recent_posts
    except Exception as e:
        print(f"抓取失败: {e}")
        return []

def fetch_web_content(url):
    """
    抓取普通网页内容 (使用 Selenium 以支持动态渲染)
    """
    print(f"正在抓取网页(Selenium): {url} ...")
    driver = None
    try:
        # 配置无头浏览器
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # 无界面模式
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        # 伪装 User-Agent
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.get(url)
        # 等待页面加载 (简单等待，可改进为 WebDriverWait)
        time.sleep(5) 
        
        # 获取渲染后的 HTML
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 提取标题
        title = soup.title.string.strip() if soup.title else url
        
        # 提取正文 
        # 策略：优先找 article 标签，其次找主要的 div 类名，最后兜底 p 标签
        content_text = ""
        
        # 尝试通常的文章容器
        article = soup.find('article')
        if article:
            content_text = article.get_text(strip=True)
        else:
            # 兜底：获取所有 p 标签
            paragraphs = soup.find_all('p')
            content_text = "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
            
            # 最后的兜底：body
            if not content_text and soup.body:
                content_text = soup.body.get_text(strip=True)

        # DEBUG: 打印抓取到的内容日志
        print(f"[DEBUG] Title: {title}")
        print(f"[DEBUG] Content Length: {len(content_text)}")
        preview = content_text[:200].replace('\n', ' ')
        print(f"[DEBUG] Content Preview (first 200 chars):\n{preview}...\n")

        # 普通网页通常没有统一的 "发布时间" 元数据，这里使用当前抓取时间作为参考
        pub_date = datetime.now().strftime("%Y-%m-%d")
        
        return [{
            "title": title,
            "date": pub_date,
            "link": url,
            "content_snippet": content_text[:5000] # Selenium 抓取的内容可能较多，给 5000 字符
        }]
    except Exception as e:
        print(f"网页抓取失败: {e}")
        return []
    finally:
        if driver:
            driver.quit()

def _prepare_page_for_capture(url):
    """
    内部辅助函数：初始化浏览器，打开网页，并滚动加载所有内容。
    返回 (driver, last_height)
    注意：调用方负责 driver.quit()
    """
    print(f"正在准备页面: {url} ...")
    driver = None
    try:
        # 复用 Selenium 配置
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080") # 设置初始窗口大小
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        driver.get(url)
        
        # 智能寻找滚动容器并触发懒加载
        print(" -> 正在分析页面结构并加载内容...")
        
        # 1. 模拟滚动 (针对找到的元素)
        # 我们分段滚动，确保触发 Lazy Load
        last_height = 0
        
        # 最多尝试滚动 20 次，每次滚 1000px，直到滚不动
        for i in range(20):
            driver.execute_script("""
                let el = (function() { 
                    let maxS = 0; let target = document.documentElement;
                    [document.documentElement, document.body, ...document.querySelectorAll('div')].forEach(e => {
                        if(e.scrollHeight > maxS && e.offsetParent !== null) { maxS = e.scrollHeight; target = e; }
                    });
                    return target;
                })();
                el.scrollTop = el.scrollHeight; 
                window.scrollTo(0, document.body.scrollHeight);
            """)
            
            time.sleep(1.5) # 等待加载
            
            # 检查高度是否还在增长
            new_height = driver.execute_script("""
                let maxS = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
                let divs = document.querySelectorAll('div');
                for(let d of divs) { if(d.scrollHeight > maxS) maxS = d.scrollHeight; }
                return maxS;
            """)
            
            if new_height == last_height and i > 2: # 至少滚两次确认
                print(f" -> 内容加载完毕，检测到高度: {new_height}px")
                break
            
            last_height = new_height
            if new_height > 30000:
                print(" -> 页面过长，提前停止")
                break
                
        # 滚回顶部
        driver.execute_script("window.scrollTo(0, 0)")
        return driver, last_height

    except Exception as e:
        print(f"页面准备失败: {e}")
        if driver:
            driver.quit()
        return None, 0

def capture_web_screenshot_png(url, output_path):
    """
    抓取网页长截图 (PNG)
    """
    print(f"正在生成 PNG: {url} ...")
    driver, last_height = _prepare_page_for_capture(url)
    if not driver:
        return False
        
    try:
        # 截图: 设置窗口为最大检测到的高度 + 缓冲
        final_height = last_height + 200
        if final_height > 30000: final_height = 30000
        if final_height < 1080: final_height = 1080 # 保底
        
        print(f"Final Viewport Height: {final_height}px")
        driver.set_window_size(1920, final_height)
        time.sleep(2) # 布局重绘等待
        driver.save_screenshot(output_path)
        print(f"文件已保存至: {output_path}")
        return True
    except Exception as e:
        print(f"PNG 生成失败: {e}")
        return False
    finally:
        driver.quit()

def capture_web_pdf(url, output_path):
    """
    抓取网页并导出为单页长 PDF
    """
    print(f"正在生成 PDF: {url} ...")
    driver, last_height = _prepare_page_for_capture(url)
    if not driver:
        return False

    try:
        # PDF 修复逻辑：
        # 直接使用刚才滚动探测到的真实高度 (last_height)
        real_height = max(last_height, 1080)
        
        driver.execute_script(f"""
            // 1. 尝试找到那个滚动容器
            let scrollEl = (function() {{ 
                let maxS = 0; let target = document.body;
                [document.documentElement, document.body, ...document.querySelectorAll('div')].forEach(e => {{
                    if(e.scrollHeight > maxS && e.offsetParent !== null) {{ maxS = e.scrollHeight; target = e; }}
                }});
                return target;
            }})();
            
            // 2. 暴力撑开
            let h = '{real_height}px';
            
            if(scrollEl) {{
                scrollEl.style.height = h;
                scrollEl.style.maxHeight = 'none';
                scrollEl.style.overflow = 'visible';
            }}
            document.body.style.height = h;
            document.documentElement.style.height = h;
            document.body.style.overflow = 'visible';
            document.documentElement.style.overflow = 'visible';
        """)
        time.sleep(1) # 等待渲染更新

        # 计算尺寸
        metrics = driver.execute_script("return { width: Math.max(document.body.scrollWidth, document.documentElement.scrollWidth, 1200) }")
        page_width_in_inches = metrics['width'] / 96.0
        page_height_in_inches = (real_height + 100) / 96.0 
        
        print(f" -> 生成 PDF 尺寸: {metrics['width']}x{real_height} px (由滚动探测决定)")

        params = {
            'landscape': False,
            'displayHeaderFooter': False,
            'printBackground': True,
            'preferCSSPageSize': False,
            'paperWidth': page_width_in_inches,
            'paperHeight': page_height_in_inches,
            'marginTop': 0,
            'marginBottom': 0,
            'marginLeft': 0,
            'marginRight': 0,
        }
        
        result = driver.execute_cdp_cmd("Page.printToPDF", params)
        with open(output_path, 'wb') as f:
            f.write(base64.b64decode(result['data']))
        print(f"文件已保存至: {output_path}")
        return True
    except Exception as e:
        print(f"PDF 生成失败: {e}")
        return False
    finally:
        driver.quit()


def organize_data(posts, source_name):
    """
    调用 LLM 对信息进行标准化整理 (时间、事件维度)
    """
    if not posts:
        return f"【{source_name}】最近 {DAYS_LOOKBACK} 天没有更新。"

    # 构建 Prompt
    data_text = ""
    for idx, post in enumerate(posts):
        # 截取一部分内容，避免 Token 过长，但要足够提取信息
        snippet = post['content_snippet'][:1000]
        data_text += f"ID: {idx+1}\n标题: {post['title']}\n时间: {post['date']}\n内容: {snippet}\n\n"

    prompt = f"""
    你是一个专业的数据整理助手。请对以下来自【{source_name}】的原始数据进行标准化整理。
    
    目标：
    不要生成笼统的总结报告。请按照“时间”和“事件”维度，将每条有价值的信息结构化展示和输出。
    
    要求：
    1. 按时间倒序排列（最新的在最前）。
    2. 每一项需包含：
       - **日期**: YYYY-MM-DD
       - **事件**: 简练概括发生了什么（标题/核心动作）
       - **关键信息**: 提取 1-3 点核心细节（如发布了什么模型、具体参数、活动地点等）
       - **分类**: 给该事件打一个标签（如：技术发布、商业动态、观点分享、其他）
    3. 忽略无实质内容的条目（如纯广告或无意义的短文）。
    4. 输出格式请使用 Markdown 列表或表格，保持清晰。

    待整理数据：
    {data_text}
    """

    response = client.chat.completions.create(
        model=config.get('llm', 'model'),  # 模型名称从 config.ini 读取
        messages=[
            {"role": "system", "content": "You are a helpful assistant for data organization."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content

# ================= 主程序入口 =================
if __name__ == "__main__":
    final_report = "# 🌍 全球情报周报 (Automated)\n\n"
    
    for name, url in rss_sources.items():
        posts = fetch_recent_posts(url, DAYS_LOOKBACK)
        print(f" -> 发现 {len(posts)} 条相关内容，正在整理...")
        
        organized_content = organize_data(posts, name)
        
        final_report += f"## 来源：{name}\n{organized_content}\n\n---\n\n"

    for name, url in web_sources.items():
        # 生成网页截图或 PDF
        snapshot_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        capture_web_screenshot_png(url, snapshot_path)

        pdf_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        capture_web_pdf(url, pdf_path)

    for name, url in web_sources.items():
        posts = fetch_web_content(url)
        if posts: # 只有抓取成功才处理
            print(f" -> 成功获取网页内容，正在整理...")
            organized_content = organize_data(posts, name)
            final_report += f"## 来源：{name} (Web)\n{organized_content}\n\n---\n\n"
    
    # 打印最终报告，或者可以改为发送邮件/保存为 Markdown 文件
    print("\n" + "="*30 + " 最终报告 " + "="*30 + "\n")
    print(final_report)