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
from common import organize_data, log

# ================= 配置区域 =================
# 设置普通 Web URL 抓取源
# 适用于没有 RSS 的单页面，如具体的一篇博文或静态页面
web_sources = {
    # "Qwen_blog": "https://qwen.ai/research",
    # "DeepMind_About": "https://deepmind.google/about/",
}
# ===========================================


def fetch_web_content(url):
    """
    抓取普通网页内容 (使用 Selenium 以支持动态渲染)
    """
    log(f"    正在抓取网页(Selenium): {url} ...")
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
        # log(f"[DEBUG] Title: {title}")
        # log(f"[DEBUG] Content Length: {len(content_text)}")
        # preview = content_text[:200].replace('\n', ' ')
        # log(f"[DEBUG] Content Preview (first 200 chars): {preview}...")

        # 普通网页通常没有统一的 "发布时间" 元数据，这里使用当前抓取时间作为参考
        pub_date = datetime.now().strftime("%Y-%m-%d")
        
        return {
            "title": title,
            "date": pub_date,
            "link": url,
            "content": content_text
        }
    except Exception as e:
        log(f"    网页抓取失败: {e}")
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
    log(f"    正在准备页面: {url} ...")
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
        log("    -> 正在分析页面结构并加载内容...")
        
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
                log(f"    -> 内容加载完毕，检测到高度: {new_height}px")
                break
            
            last_height = new_height
            if new_height > 30000:
                log("    -> 页面过长，提前停止")
                break
                
        # 滚回顶部
        driver.execute_script("window.scrollTo(0, 0)")
        return driver, last_height

    except Exception as e:
        log(f"页面准备失败: {e}")
        if driver:
            driver.quit()
        return None, 0


def capture_web_screenshot_png(url, output_path):
    """
    抓取网页长截图 (PNG)
    """
    log(f"    正在生成 PNG: {url} ...") 
    driver, last_height = _prepare_page_for_capture(url)
    if not driver:
        return False
        
    try:
        # 截图: 设置窗口为最大检测到的高度 + 缓冲
        final_height = last_height + 200
        if final_height > 30000: final_height = 30000
        if final_height < 1080: final_height = 1080 # 保底
        
        log(f"Final Viewport Height: {final_height}px")
        driver.set_window_size(1920, final_height)
        time.sleep(2) # 布局重绘等待
        driver.save_screenshot(output_path)
        log(f"文件已保存至: {output_path}")
        return True
    except Exception as e:
        log(f"PNG 生成失败: {e}")
        return False
    finally:
        driver.quit()


def capture_web_pdf(url, output_path):
    """
    抓取网页并导出为单页长 PDF
    """
    log(f"    正在生成 PDF: {url} ...")
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
        
        log(f" -> 生成 PDF 尺寸: {metrics['width']}x{real_height} px (由滚动探测决定)")

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
        log(f"    文件已保存至: {output_path}")
        return True
    except Exception as e:
        log(f"    PDF 生成失败: {e}")
        return False
    finally:
        driver.quit()


# ================= 主程序入口 =================
if __name__ == "__main__":
    final_report = "# 🌐 Web 情报周报 (Automated)\n\n"
    
    for name, url in web_sources.items():
        # 生成网页截图或 PDF
        snapshot_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        capture_web_screenshot_png(url, snapshot_path)

        pdf_path = f"data/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        capture_web_pdf(url, pdf_path)

    for name, url in web_sources.items():
        post = fetch_web_content(url)
        if post: # 只有抓取成功才处理
            log(f"    -> 成功获取网页内容，正在整理...")
            organized_content = organize_data([post], name)
            final_report += f"## 来源：{name} (Web)\n{organized_content}\n\n---\n\n"
    
    # 打印最终报告
    log("\n" + "="*30 + " 最终报告 " + "="*30)
    log(final_report)
