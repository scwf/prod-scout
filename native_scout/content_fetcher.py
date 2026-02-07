"""
content_fetcher.py - 嵌入内容爬取模块

功能：
- 从文本中提取博客和YouTube链接
- 爬取博客页面正文内容
- 获取YouTube视频字幕和元数据

设计原则：
- 单一职责：每个类只负责一种类型的内容获取
- 易于扩展：新增内容类型只需添加新的Fetcher类
- 解耦清晰：rss_crawler.py 只需调用 ContentFetcher，不关心内部实现
"""
import re
from urllib.parse import urlparse, parse_qs
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from common import config, setup_logger

logger = setup_logger("content_fetcher")

@dataclass
class EmbeddedContent:
    """嵌入内容数据结构"""
    url: str
    content_type: str  # 'blog' | 'subtitle'
    title: str = ''
    content: str = ''
    metadata: Dict = field(default_factory=dict)


def _shorten_url(url: str, length: int = 60) -> str:
    """Helper: Truncate long URLs for logging"""
    if not url: return ""
    return url[:length] + "..." if len(url) > length else url



class LinkExtractor:
    """从文本中提取和分类URL"""
    
    # 需要跳过的域名（社交媒体自身的链接，不作为博客处理）
    SKIP_DOMAINS = ['twitter.com', 'x.com', 't.co', 'pic.twitter.com']
    
    # YouTube相关域名
    YOUTUBE_DOMAINS = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
    
    # 通用视频域名/扩展名
    VIDEO_DOMAINS = ['video.twimg.com']
    VIDEO_EXTENSIONS = ['.mp4', '.mov', '.webm', '.mkv']
    
    # 媒体资源域名（图片、视频等）
    MEDIA_DOMAINS = ['twimg.com', 'pbs.twimg.com']
    
    @staticmethod
    def extract_urls(text: str) -> List[str]:
        """
        提取文本中的所有URL
        
        参数:
            text: 要解析的文本内容
        
        返回:
            提取到的URL列表
        """
        if not text:
            return []
        
        # URL匹配正则表达式
        pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        urls = re.findall(pattern, text)
        
        # 去重并保持顺序
        seen = set()
        unique_urls = []
        for url in urls:
            # 清理URL末尾可能的标点符号
            url = url.rstrip('.,;:!?')
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)
        
        return unique_urls
    
    @classmethod
    def categorize(cls, text: str) -> Tuple[List[str], List[str], List[str]]:
        """
        分类提取博客链接、视频链接（含YouTube）和媒体链接
        
        参数:
            text: 要解析的文本内容
        
        返回:
            (blog_links, video_links, media_urls) 三元组
        """
        urls = cls.extract_urls(text)
        blog_links = []
        video_links = []
        media_urls = []
        
        for url in urls:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path = parsed.path.lower()
            
            # 1. 视频链接 (YouTube 或 通用视频)
            is_youtube = any(yt in domain for yt in cls.YOUTUBE_DOMAINS)
            is_generic_video = (
                any(v in domain for v in cls.VIDEO_DOMAINS) or 
                any(path.endswith(ext) for ext in cls.VIDEO_EXTENSIONS)
            )
            
            if is_youtube or is_generic_video:
                video_links.append(url)
            
            # 2. 其他媒体资源链接（图片等）
            elif any(media in domain for media in cls.MEDIA_DOMAINS):
                media_urls.append(url)
            
            # 3. 博客/网页链接 (排除跳过的域名)
            elif domain and not any(skip in domain for skip in cls.SKIP_DOMAINS):
                blog_links.append(url)
        
        return blog_links, video_links, media_urls



class GenericVideoFetcher:
    """通用视频信息获取器 (支持YouTube, Twitter视频等)"""
    
    # 已知的无声视频URL模式 (如Twitter GIF转MP4)
    SILENT_VIDEO_PATTERNS = [
        '/tweet_video/',  # Twitter GIF -> MP4
    ]
    
    def _is_likely_silent_video(self, url: str) -> bool:
        """检查URL是否可能是无声视频（如GIF转MP4）"""
        return any(pattern in url for pattern in self.SILENT_VIDEO_PATTERNS)
    
    def _parse_video_info(self, url: str) -> Tuple[Optional[str], str]:
        """
        解析视频信息
        
        返回:
            (video_id, video_url)
            - video_id: 用于文件存储的唯一标识
            - video_url: 用于下载的实际URL
        """
        if not url:
            return None, ""
            
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # 1. 尝试解析 YouTube
        youtube_id = self._extract_youtube_id(parsed, domain)
        if youtube_id:
            return youtube_id, f"https://www.youtube.com/watch?v={youtube_id}"

        # 2. 通用策略 (其他视频源)
        return self._generate_generic_video_id(url, parsed), url

    def _extract_youtube_id(self, parsed, domain) -> Optional[str]:
        """辅助函数: 提取YouTube ID"""
        current_url = parsed.geturl()
        if not any(d in domain for d in ['youtube.com', 'youtu.be']):
            logger.info(f"Skipping non-youtube page: {current_url}")
            return None
            
        # 过滤非视频页面（直播大厅、频道页、用户页）
        if any(x in parsed.path for x in ['/streams', '/live', '/channel/', '/c/', '/user/']):
            logger.info(f"Skipping non-video page: {current_url}")
            return None
            
        try:
            # youtu.be/ID
            if 'youtu.be' in domain:
                return parsed.path.lstrip('/').split('?')[0]
                
            # youtube.com/watch?v=ID or /embed/ID
            if 'youtube.com' in domain:
                if '/watch' in parsed.path:
                    query = parse_qs(parsed.query)
                    return query.get('v', [None])[0]
                if '/embed/' in parsed.path:
                    parts = parsed.path.split('/embed/')
                    if len(parts) > 1:
                        return parts[1].split('/')[0].split('?')[0]
        except Exception:
            pass
        return None

    def _generate_generic_video_id(self, url: str, parsed, title: str = "") -> str:
        """辅助函数: 生成通用视频ID (基于标题、文件名或Hash)"""
        import hashlib
        
        def get_hash(s):
            return hashlib.md5(s.encode()).hexdigest()

        try:
            # 优先使用标题作为文件名基础
            safe_name = ""
            if title:
                # 截取前50个字符并清理特殊字符
                clean_title = "".join(c if c.isalnum() else '_' for c in title)[:50]
                if clean_title:
                    safe_name = clean_title

            # 如果没有标题，尝试从URL路径获取文件名
            if not safe_name:
                filename = os.path.basename(parsed.path)
                if filename and '.' in filename and len(filename) <= 80:
                    safe_name = "".join(c if c.isalnum() else '_' for c in os.path.splitext(filename)[0])
            
            # 如果还是没有有效的文件名基础，直接返回Hash
            if not safe_name:
                return get_hash(url)[:12]
            
            # 组合: 安全文件名 + URL Hash前缀 (防止重名)
            url_hash = get_hash(url)[:6]
            return f"{safe_name}_{url_hash}"
            
        except Exception:
            # 绝对兜底
            return get_hash(url)[:12]

    
    def fetch_transcript(self, video_id: str, video_url: str, context: str = "", optimize: bool = False, batch_timestamp: str = None) -> str:
        """
        获取视频字幕，并保存 srt/txt 到 raw 目录
        
        使用 video_scribe 模块自动处理（下载+转录）
        
        参数:
            video_id: 视频ID (也是目录名)
            video_url: 视频可下载链接
            batch_timestamp: 批次时间戳，用于归档 (None则用默认raw)
        
        返回:
            视频字幕文本
        """
        import os
        import sys
        
        # 确保能导入 video_scribe
        # video_scribe 在项目根目录， content_fetcher.py 在 crawler/ 目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        if project_root not in sys.path:
            sys.path.append(project_root)
            
        try:
            # 构造输出目录: data/raw_{timestamp}/{video_id}/
            raw_dir_name = f"raw_{batch_timestamp}" if batch_timestamp else "raw"
            output_dir = os.path.join(project_root, 'data', raw_dir_name, video_id)
            os.makedirs(output_dir, exist_ok=True)
            
            logger.info(f"开始转录视频 [ID: {video_id}] -> {output_dir}")
            
            # 调用 video_scribe 处理
            # process_video 会自动保存 .srt, .txt, .json 到 output_dir
            from video_scribe.core import process_video, optimize_subtitle
            
            asr_data = process_video(
                video_url_or_path=video_url,
                output_dir=output_dir,
                device="cuda", # 默认使用CUDA，如果失败 video_scribe 可能会报错，需确保环境
                language=None  # 自动检测
            )
            
            # --- LLM 字幕优化 ---
            # youtube 自动生成的字幕质量很差，会导致优化后的字幕文件和优化前字幕变化较大，导致优化失败（差异判别过大），故先把优化关掉
            final_data = asr_data  # 默认为原始数据
            if optimize:
                try:
                    logger.info(f"开始优化字幕 [ID: {video_id}]...")
                    api_key = config.get('llm', 'api_key')
                    base_url = config.get('llm', 'base_url')
                    model = config.get('llm', 'opt_model', fallback='gpt-3.5-turbo')
                    
                    if context:
                        custom_prompt = f"Context: {context}"
                    logger.info(f"优化字幕上下文信息：{custom_prompt}")

                    optimized_data = optimize_subtitle(
                        subtitle_data=asr_data,
                        model=model,
                        api_key=api_key,
                        base_url=base_url,
                        custom_prompt=custom_prompt
                    )
                    
                    save_base = os.path.join(output_dir, f"{video_id}_optimized")
                    optimized_data.save(save_base + ".srt")
                    optimized_data.save(save_base + ".txt")
                    
                    final_data = optimized_data
                    
                except Exception as opt_e:
                    logger.warning(f"字幕优化失败，回退到原始字幕 [ID: {video_id}]: {opt_e}")
                    # 即使优化失败，也继续返回原始字幕
            
            # 返回最终文本（优化后或原始）
            return final_data.to_txt()
            
        except Exception as e:
            error_msg = str(e)
            
            # 特殊处理：无音频编解码器（静音视频/GIF）
            if 'unable to obtain file audio codec' in error_msg:
                logger.info(f"跳过静音视频（无音轨）[ID: {video_id}]")
                return ''
            
            logger.error(f"视频转录流程严重失败 [ID: {video_id}]: {e}")
            import traceback
            traceback.print_exc()
            return ''
    
    def fetch(self, url: str, context: str = "", title: str = "", optimize: bool = False, batch_timestamp: str = None) -> Optional[EmbeddedContent]:
        """
        获取视频的完整信息
        
        参数:
            url: 视频URL
            context: 上下文信息
            title: 视频标题 (用于生成更有意义的文件名)
            batch_timestamp: 批次时间戳
        返回:
            EmbeddedContent对象，如果无法提取则返回None
        """
        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # 1. 尝试解析 YouTube ID
        youtube_id = self._extract_youtube_id(parsed, domain)
        if youtube_id:
            video_id = youtube_id
            video_url = f"https://www.youtube.com/watch?v={youtube_id}"
        else:
            # 2. 通用视频，优先使用 Title 生成 ID
            video_id = self._generate_generic_video_id(url, parsed, title)
            video_url = url

        if not video_id:
            logger.info(f"无法解析视频信息: {_shorten_url(url)}")
            return None
        
        # 预检查：跳过已知的无声视频
        if self._is_likely_silent_video(url):
            logger.info(f"跳过静音视频（URL模式匹配）: {_shorten_url(url)}")
            return None
        
        transcript = self.fetch_transcript(video_id, video_url, context=context, optimize=optimize, batch_timestamp=batch_timestamp)
        
        return EmbeddedContent(
            url=url,
            content_type='subtitle',
            title=title,
            content=transcript,
            metadata={'video_id': video_id, 'video_url': video_url}
        )


class BlogFetcher:
    """博客页面内容获取器（复用Selenium逻辑）"""
    
    # 内容最大长度限制
    MAX_CONTENT_LENGTH = 50000
    
    def fetch(self, url: str) -> Optional[EmbeddedContent]:
        """
        爬取博客页面内容
        
        使用 Selenium 进行动态渲染，复用 web_crawler.py 的逻辑
        
        参数:
            url: 博客页面URL
        
        返回:
            EmbeddedContent对象，如果爬取失败则返回None
        """
        try:
            # 延迟导入，避免不使用时加载 Selenium
            from web_crawler import fetch_web_content
            
            result = fetch_web_content(url)
            
            if result:
                content = result.get('content', '')
                
                # 截断过长内容
                if len(content) > self.MAX_CONTENT_LENGTH:
                    content = content[:self.MAX_CONTENT_LENGTH] + '...'
                
                return EmbeddedContent(
                    url=url,
                    content_type='blog',
                    title=result.get('title', ''),
                    content=content,
                    metadata={
                        'original_length': len(result.get('content', ''))
                    }
                )
            
            logger.info(f"博客爬取返回空结果: {_shorten_url(url)}")
            return None
            
        except Exception as e:
            logger.info(f"博客爬取失败 [{_shorten_url(url)}]: {e}")
            return None


class ContentFetcher:
    """
    内容爬取统一入口（门面模式）
    
    提供简洁的API，隐藏内部的链接提取和分类爬取逻辑
    """
    
    def __init__(self, batch_timestamp: str = None):
        self.video_fetcher = GenericVideoFetcher()
        self.blog_fetcher = BlogFetcher()
        self.batch_timestamp = batch_timestamp
    
    def fetch_embedded_content(self, text: str, title: str = "", optimize_video: bool = False) -> Tuple[List[EmbeddedContent], List[str]]:
        """
        从文本中提取并爬取所有嵌入内容
        
        参数:
            text: 包含URL的文本内容（如推文正文）
            title: 来源的标题（如推文内容的前30个字，用于辅助视频命名）
        
        返回:
            (embedded_contents, all_urls) 元组
            - embedded_contents: 爬取到的嵌入内容列表（博客、YouTube）
            - all_urls: 所有外部资源链接（博客URL、YouTube URL、媒体URL）
        """
        if not text:
            return [], []
        
        # 提取并分类URL
        blog_links, video_links, media_urls = LinkExtractor.categorize(text)
        results = []
        
        # 处理视频链接 (YouTube + Generic)
        for url in video_links:
            try:
                logger.info(f"正在获取视频内容: {_shorten_url(url)}")
                content = self.video_fetcher.fetch(url, title=title, context=text, optimize=optimize_video, batch_timestamp=self.batch_timestamp)
                if content:
                    results.append(content)
            except Exception as e:
                logger.info(f"视频内容获取失败 [{_shorten_url(url)}]: {e}")
        
        # 处理博客链接
        for url in blog_links:
            try:
                logger.info(f"正在获取博客内容: {_shorten_url(url)}")
                content = self.blog_fetcher.fetch(url)
                if content:
                    results.append(content)
            except Exception as e:
                logger.info(f"博客内容获取失败 [{_shorten_url(url)}]: {e}")
        
        # 合并所有外部资源链接（博客、YouTube、媒体）
        all_urls = blog_links + video_links + media_urls
        
        return results, all_urls
    

