"""
web_crawler.py - Web 页面抓取工具

功能：
- 使用 Selenium 抓取普通网页内容
- 生成网页长截图 (PNG) 和高保真 PDF 存档
- 调用 LLM 对抓取内容进行结构化整理

依赖：selenium, beautifulsoup4, openai, webdriver-manager
"""
import base64
from datetime import datetime
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from common import setup_logger

logger = setup_logger("web_crawler")

# ================= 配置区域 =================
# 设置普通 Web URL 抓取源
# 适用于没有 RSS 的单页面，如具体的一篇博文或静态页面
web_sources = {
    # "databricks_ebook": "https://www.databricks.com/resources/ebook/state-of-ai-agents?utm_source=twitter&utm_medium=organic-social&utm_scid=701Vp00000V6YWcIAN",
    # "qwen3asr": "https://qwen.ai/blog?id=qwen3asr",
    # "databricks_hidden_technical_debt_genai_systems": "https://www.databricks.com/blog/hidden-technical-debt-genai-systems",
    "Qwen_blog": "https://qwen.ai/research",
    # "DeepMind_About": "https://deepmind.google/about/",
}
# ===========================================

def _clean_text_content(text):
    """
    [Optional] 后处理清洗文本内容
    移除多余空行、特定的噪音关键词行、Cookie声明等
    """
    if not text:
        return ""
    
    # 1. 移除多余空行 (保留段落结构，但去除大片空白)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    lines = text.split('\n')
    cleaned_lines = []
    
    # 定义一些绝对不想看到的噪音关键词 (大小写不敏感)
    # 注意：只针对短行生效，避免误删正文
    noise_patterns = [
        r'^share this post$',
        r'^contents in this story$',
        r'^read time:?\s*\d+',
        r'^\d+\s*min read$',
        r'^keep up with us$',
        r'^sign up for.*newsletter',
        r'^all rights reserved',
        r'^©\s*\d+',
        r'^click to share',
        r'^subscribe to',
        r'^share on',
    ]
    
    for line in lines:
        stripped = line.strip()
        
        # 跳过空行（后面统一 join）
        if not stripped:
            continue
            
        # 2. 检查短行噪音 (< 60 chars)
        if len(stripped) < 60:
            is_noise = False
            for pattern in noise_patterns:
                if re.search(pattern, stripped, re.IGNORECASE):
                    is_noise = True
                    break
            if is_noise:
                continue
        
        # 3. 针对特定的 Cookie/Privacy 声明段落 (长文本特征)
        lower_line = stripped.lower()
        if "cookies" in lower_line and "browser" in lower_line and "experience" in lower_line:
            continue
        if lower_line.startswith("by submitting") and "privacy policy" in lower_line:
            continue
            
        cleaned_lines.append(stripped)
        
    return '\n'.join(cleaned_lines)

def fetch_web_content(url):
    """
    [Optimized] 抓取普通网页内容
    
    改进点：
    1. 智能等待 (WebDriverWait)
    2. 模拟滚动 (Lazy Load支持)
    3. 内容清洗 (移除干扰标签)
    4. 反爬虫规避优化
    """
    logger.info(f"正在抓取网页(Selenium Optimized): {url} ...")
    driver = None
    try:
        # 配置无头浏览器
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # 伪装 User-Agent
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # 规避检测
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # 进一步规避：移除 navigator.webdriver 标记
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined
            })
            """
        })
        
        driver.get(url)
        
        # 1. 智能等待：等待 body 可见，最长 15秒
        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            logger.info("等待页面加载超时，尝试继续处理...")

        # 2. 模拟滚动加载 (复用部分 _prepare_page_for_capture 的精简逻辑)
        # 快速滚动以触发懒加载文字
        logger.info("-> 触发滚动加载...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3): # 尝试滚动3次，不像截图那样需要特别精细，只要加载出大部分正文即可
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
        
        # 获取渲染后的 HTML
        html_content = driver.page_source
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 3. 内容清洗
        # 移除干扰元素
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'meta', 'iframe', 'svg', 'select', 'button']):
            tag.decompose()
            
        # 移除常见的广告/侧边栏 class/id
        bad_selectors = [
            '.sidebar', '#sidebar', '.ads', '.advertisement', '.social-share', 
            '.comment-list', '.related-posts', '.menu', '#menu', '.nav', '.navigation'
        ]
        for selector in bad_selectors:
            for tag in soup.select(selector):
                tag.decompose()

        # 提取标题
        title = soup.title.string.strip() if soup.title else url
        
        # 4. 优化的提取策略
        content_text = ""
        
        # 策略A: 查找常见的文章容器 ID/Class
        article_selectors = [
            'article', 
            'main',
            '[role="main"]',
            '.post-content', 
            '.entry-content', 
            '.article-content',
            '#content',
            '.container' 
        ]
        
        target_element = None
        for selector in article_selectors:
            found = soup.select(selector)
            if found:
                # 如果找到多个，取字数最多的一个
                target_element = max(found, key=lambda t: len(t.get_text()))
                logger.info(f"-> 命中选择器提取: {selector}")
                break
                
        if target_element:
            content_text = target_element.get_text(separator='\n', strip=True)
        else:
            # 策略B: 兜底 - 提取所有P标签，但进行密度过滤
            logger.info("-> 使用段落密度回退策略")
            paragraphs = soup.find_all('p')
            # 过滤掉过短的导航性文字 (例如少于 5 个字)
            valid_paragraphs = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 5]
            content_text = "\n".join(valid_paragraphs)
            
            # 策略C: 如果还是没东西，Last Resort
        if len(content_text) < 50 and soup.body:
                content_text = soup.body.get_text(separator='\n', strip=True)

        logger.info(f"-> 原始内容长度: {len(content_text)} 字符")
        
        # [Optional] 后处理清洗
        content_text = _clean_text_content(content_text)
        logger.info(f"-> 清洗后内容长度: {len(content_text)} 字符")

        pub_date = datetime.now().strftime("%Y-%m-%d")
        
        return {
            "title": title,
            "date": pub_date,
            "link": url,
            "content": content_text
        }
    except Exception as e:
        logger.info(f"网页抓取失败: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def _prepare_page_for_capture(url):
    """
    内部辅助函数：初始化浏览器，打开网页，并滚动加载所有内容。
    返回 (driver, last_height)
    注意：调用方负责 driver.quit()
    """
    logger.info(f"正在准备页面: {url} ...")
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
        logger.info("-> 正在分析页面结构并加载内容...")
        
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
                logger.info(f"-> 内容加载完毕，检测到高度: {new_height}px")
                break
            
            last_height = new_height
            if new_height > 30000:
                logger.info("-> 页面过长，提前停止")
                break
                
        # 滚回顶部
        driver.execute_script("window.scrollTo(0, 0)")
        return driver, last_height

    except Exception as e:
        logger.info(f"页面准备失败: {e}")
        if driver:
            driver.quit()
        return None, 0


def capture_web_screenshot_png(url, output_path):
    """
    抓取网页长截图 (PNG)
    """
    logger.info(f"正在生成 PNG: {url} ...") 
    driver, last_height = _prepare_page_for_capture(url)
    if not driver:
        return False
        
    try:
        # 截图: 设置窗口为最大检测到的高度 + 缓冲
        final_height = last_height + 200
        if final_height > 30000: final_height = 30000
        if final_height < 1080: final_height = 1080 # 保底
        
        logger.info(f"Final Viewport Height: {final_height}px")
        driver.set_window_size(1920, final_height)
        time.sleep(2) # 布局重绘等待
        driver.save_screenshot(output_path)
        logger.info(f"文件已保存至: {output_path}")
        return True
    except Exception as e:
        logger.info(f"PNG 生成失败: {e}")
        return False
    finally:
        driver.quit()


def capture_web_pdf(url, output_path):
    """
    抓取网页并导出为单页长 PDF
    """
    logger.info(f"正在生成 PDF: {url} ...")
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
        
        logger.info(f" -> 生成 PDF 尺寸: {metrics['width']}x{real_height} px (由滚动探测决定)")

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
        logger.info(f"文件已保存至: {output_path}")
        return True
    except Exception as e:
        logger.info(f"PDF 生成失败: {e}")
        return False
    finally:
        driver.quit()


# ================= 主程序入口 =================
if __name__ == "__main__":
    final_report = "# 🌐 Web 情报周报 (Automated)\n\n"
    
    # for name, url in web_sources.items():
    #     # 生成网页截图或 PDF
    #     snapshot_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    #     capture_web_screenshot_png(url, snapshot_path)

    #     pdf_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    #     capture_web_pdf(url, pdf_path)

    for name, url in web_sources.items():
        post = fetch_web_content(url)
        if post: # 只有抓取成功才处理
            logger.info(f"-> 成功获取网页内容")
            final_report += f"## 来源：{name} (Web)\n{post}\n\n---\n\n"
    
    # 打印最终报告
    logger.info("\n" + "="*30 + " 最终报告 " + "="*30)
    logger.info(final_report)
