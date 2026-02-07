"""
utils/content_fetcher.py - merged content fetcher for daft_crawler.

Includes:
- fetch_web_content (Selenium-based web page fetch)
- embedded content extraction
- video subtitle fetching via video_scribe
"""
import os
import re
import time
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from common import setup_logger


logger = setup_logger("daft_content_fetcher")


@dataclass
class EmbeddedContent:
    url: str
    content_type: str  # "blog" | "subtitle"
    title: str = ""
    content: str = ""
    metadata: Dict = field(default_factory=dict)


def _shorten_url(url: str, length: int = 60) -> str:
    if not url:
        return ""
    return url[:length] + "..." if len(url) > length else url


def _md5_hash(value: str) -> str:
    import hashlib

    return hashlib.md5(value.encode()).hexdigest()


def _clean_text_content(text):
    if not text:
        return ""

    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.split("\n")
    cleaned_lines = []

    noise_patterns = [
        r"^share this post$",
        r"^contents in this story$",
        r"^read time:?\s*\d+",
        r"^\d+\s*min read$",
        r"^keep up with us$",
        r"^sign up for.*newsletter",
        r"^all rights reserved",
        r"^\d+\s*$",
        r"^click to share",
        r"^subscribe to",
        r"^share on",
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if len(stripped) < 60:
            is_noise = False
            for pattern in noise_patterns:
                if re.search(pattern, stripped, re.IGNORECASE):
                    is_noise = True
                    break
            if is_noise:
                continue

        lower_line = stripped.lower()
        if "cookies" in lower_line and "browser" in lower_line and "experience" in lower_line:
            continue
        if lower_line.startswith("by submitting") and "privacy policy" in lower_line:
            continue

        cleaned_lines.append(stripped)

    return "\n".join(cleaned_lines)


def fetch_web_content(url):
    logger.info(f"Fetching web page (Selenium): {url} ...")
    driver = None
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {
                  get: () => undefined
                })
                """,
            },
        )

        driver.get(url)

        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except Exception:
            logger.info("Page load wait timed out; continue.")

        logger.info("-> Triggering scroll load...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(3):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html_content = driver.page_source
        soup = BeautifulSoup(html_content, "html.parser")

        for tag in soup(
            ["script", "style", "nav", "header", "footer", "noscript", "meta", "iframe", "svg", "select", "button"]
        ):
            tag.decompose()

        bad_selectors = [
            ".sidebar",
            "#sidebar",
            ".ads",
            ".advertisement",
            ".social-share",
            ".comment-list",
            ".related-posts",
            ".menu",
            "#menu",
            ".nav",
            ".navigation",
        ]
        for selector in bad_selectors:
            for tag in soup.select(selector):
                tag.decompose()

        title = soup.title.string.strip() if soup.title else url

        content_text = ""
        article_selectors = [
            "article",
            "main",
            "[role=\"main\"]",
            ".post-content",
            ".entry-content",
            ".article-content",
            "#content",
            ".container",
        ]

        target_element = None
        for selector in article_selectors:
            found = soup.select(selector)
            if found:
                target_element = max(found, key=lambda t: len(t.get_text()))
                logger.info(f"-> Selector hit: {selector}")
                break

        if target_element:
            content_text = target_element.get_text(separator="\n", strip=True)
        else:
            logger.info("-> Using paragraph density fallback")
            paragraphs = soup.find_all("p")
            valid_paragraphs = [p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 5]
            content_text = "\n".join(valid_paragraphs)

        if len(content_text) < 50 and soup.body:
            content_text = soup.body.get_text(separator="\n", strip=True)

        logger.info(f"-> Raw content length: {len(content_text)}")

        content_text = _clean_text_content(content_text)
        logger.info(f"-> Cleaned content length: {len(content_text)}")

        return {
            "title": title,
            "link": url,
            "content": content_text,
        }

    except Exception as e:
        logger.info(f"Web fetch failed: {e}")
        return None
    finally:
        if driver:
            driver.quit()


class LinkExtractor:
    """Extract and categorize URLs from text."""

    SKIP_DOMAINS = ["twitter.com", "x.com", "t.co", "pic.twitter.com"]
    YOUTUBE_DOMAINS = ["youtube.com", "youtu.be", "www.youtube.com", "m.youtube.com"]
    VIDEO_DOMAINS = ["video.twimg.com"]
    VIDEO_EXTENSIONS = [".mp4", ".mov", ".webm", ".mkv"]
    MEDIA_DOMAINS = ["twimg.com", "pbs.twimg.com"]

    @staticmethod
    def extract_urls(text: str) -> List[str]:
        if not text:
            return []
        pattern = r"https?://[^\s<>\"{}|\\^`\[\]]+"
        urls = re.findall(pattern, text)
        seen = set()
        unique_urls = []
        for url in urls:
            url = url.rstrip(".,;:!?")
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        return unique_urls

    @classmethod
    def categorize(cls, text: str) -> Tuple[List[str], List[str], List[str]]:
        urls = cls.extract_urls(text)
        blog_links = []
        video_links = []
        media_urls = []

        for url in urls:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path.lower()

            is_youtube = any(yt in domain for yt in cls.YOUTUBE_DOMAINS)
            is_generic_video = (
                any(v in domain for v in cls.VIDEO_DOMAINS)
                or any(path.endswith(ext) for ext in cls.VIDEO_EXTENSIONS)
            )

            if is_youtube or is_generic_video:
                video_links.append(url)
            elif any(media in domain for media in cls.MEDIA_DOMAINS):
                media_urls.append(url)
            elif domain and not any(skip in domain for skip in cls.SKIP_DOMAINS):
                blog_links.append(url)

        return blog_links, video_links, media_urls


class GenericVideoFetcher:
    """Generic video fetcher (YouTube, Twitter video, etc.)."""

    SILENT_VIDEO_PATTERNS = ["/tweet_video/"]

    def __init__(self, config):
        self.config = config

    def _is_likely_silent_video(self, url: str) -> bool:
        return any(pattern in url for pattern in self.SILENT_VIDEO_PATTERNS)

    def _parse_video_info(self, url: str) -> Tuple[Optional[str], str]:
        if not url:
            return None, ""

        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        youtube_id = self._extract_youtube_id(parsed, domain)
        if youtube_id:
            return youtube_id, f"https://www.youtube.com/watch?v={youtube_id}"

        return self._generate_generic_video_id(url, parsed), url

    def _extract_youtube_id(self, parsed, domain) -> Optional[str]:
        if not any(d in domain for d in ["youtube.com", "youtu.be"]):
            return None

        try:
            if "youtu.be" in domain:
                return parsed.path.lstrip("/").split("?")[0]

            if "youtube.com" in domain:
                if "/watch" in parsed.path:
                    query = parse_qs(parsed.query)
                    return query.get("v", [None])[0]
                if "/embed/" in parsed.path:
                    parts = parsed.path.split("/embed/")
                    if len(parts) > 1:
                        return parts[1].split("/")[0].split("?")[0]
        except Exception:
            pass
        return None

    def _generate_generic_video_id(self, url: str, parsed, title: str = "") -> str:
        try:
            safe_name = ""
            if title:
                clean_title = "".join(c if c.isalnum() else "_" for c in title)[:50]
                if clean_title:
                    safe_name = clean_title

            if not safe_name:
                filename = os.path.basename(parsed.path)
                if filename and "." in filename and len(filename) <= 80:
                    safe_name = "".join(c if c.isalnum() else "_" for c in os.path.splitext(filename)[0])

            if not safe_name:
                return _md5_hash(url)[:12]

            url_hash = _md5_hash(url)[:6]
            return f"{safe_name}_{url_hash}"

        except Exception:
            return _md5_hash(url)[:12]

    def fetch_transcript(self, video_id: str, video_url: str, context: str = "", optimize: bool = False) -> str:
        import sys

        # Move up 2 levels: daft_scout/utils/ -> daft_scout -> project_root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        if project_root not in sys.path:
            sys.path.append(project_root)

        try:
            output_dir = os.path.join(project_root, "data", "raw", video_id)
            os.makedirs(output_dir, exist_ok=True)

            logger.info(f"Transcribing video [ID: {video_id}] -> {output_dir}")

            from video_scribe.core import process_video, optimize_subtitle

            asr_data = process_video(
                video_url_or_path=video_url,
                output_dir=output_dir,
                device="cuda",
                language=None,
            )

            final_data = asr_data
            if optimize:
                try:
                    logger.info(f"Optimizing subtitles [ID: {video_id}]...")
                    api_key = self.config.get("llm", "api_key")
                    base_url = self.config.get("llm", "base_url")
                    model = self.config.get("llm", "opt_model", fallback="gpt-3.5-turbo")

                    custom_prompt = f"Context: {context}" if context else None
                    if custom_prompt:
                        logger.info(f"Subtitle context: {custom_prompt}")

                    optimized_data = optimize_subtitle(
                        subtitle_data=asr_data,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                        custom_prompt=custom_prompt,
                    )

                    save_base = os.path.join(output_dir, f"{video_id}_optimized")
                    optimized_data.save(save_base + ".srt")
                    optimized_data.save(save_base + ".txt")

                    final_data = optimized_data

                except Exception as opt_e:
                    logger.warning(f"Subtitle optimization failed, fallback to raw [ID: {video_id}]: {opt_e}")

            return final_data.to_txt()

        except Exception as e:
            error_msg = str(e)
            if "unable to obtain file audio codec" in error_msg:
                logger.info(f"Skip silent video [ID: {video_id}]")
                return ""

            logger.error(f"Video transcription failed [ID: {video_id}]: {e}")
            import traceback
            traceback.print_exc()
            return ""

    def fetch(self, url: str, context: str = "", title: str = "", optimize: bool = False) -> Optional[EmbeddedContent]:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        youtube_id = self._extract_youtube_id(parsed, domain)
        if youtube_id:
            video_id = youtube_id
            video_url = f"https://www.youtube.com/watch?v={youtube_id}"
        else:
            video_id = self._generate_generic_video_id(url, parsed, title)
            video_url = url

        if not video_id:
            logger.info(f"Cannot parse video info: {_shorten_url(url)}")
            return None

        if self._is_likely_silent_video(url):
            logger.info(f"Skip silent video (pattern match): {_shorten_url(url)}")
            return None

        transcript = self.fetch_transcript(video_id, video_url, context=context, optimize=optimize)

        return EmbeddedContent(
            url=url,
            content_type="subtitle",
            title=title,
            content=transcript,
            metadata={"video_id": video_id, "video_url": video_url},
        )


class BlogFetcher:
    """Fetch blog content using Selenium via fetch_web_content."""

    MAX_CONTENT_LENGTH = 50000

    def fetch(self, url: str) -> Optional[EmbeddedContent]:
        try:
            result = fetch_web_content(url)

            if result:
                content = result.get("content", "")
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[: self.MAX_CONTENT_LENGTH] + "..."

                return EmbeddedContent(
                    url=url,
                    content_type="blog",
                    title=result.get("title", ""),
                    content=content,
                    metadata={"original_length": len(result.get("content", ""))},
                )

            logger.info(f"Blog fetch returned empty: {_shorten_url(url)}")
            return None

        except Exception as e:
            logger.info(f"Blog fetch failed [{_shorten_url(url)}]: {e}")
            return None


class ContentFetcher:
    """Facade for embedded content fetching."""

    def __init__(self, config):
        self.config = config
        self.video_fetcher = GenericVideoFetcher(config)
        self.blog_fetcher = BlogFetcher()

    def fetch_embedded_content(self, text: str, title: str = "", optimize_video: bool = False) -> Tuple[List[EmbeddedContent], List[str]]:
        if not text:
            return [], []

        blog_links, video_links, media_urls = LinkExtractor.categorize(text)
        results = []

        for url in video_links:
            try:
                logger.info(f"Fetching video: {_shorten_url(url)}")
                content = self.video_fetcher.fetch(url, title=title, context=text, optimize=optimize_video)
                if content:
                    results.append(content)
            except Exception as e:
                logger.info(f"Video fetch failed [{_shorten_url(url)}]: {e}")

        for url in blog_links:
            try:
                logger.info(f"Fetching blog: {_shorten_url(url)}")
                content = self.blog_fetcher.fetch(url)
                if content:
                    results.append(content)
            except Exception as e:
                logger.info(f"Blog fetch failed [{_shorten_url(url)}]: {e}")

        all_urls = blog_links + video_links + media_urls
        return results, all_urls
