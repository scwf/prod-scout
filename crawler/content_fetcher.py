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
from common import log


@dataclass
class EmbeddedContent:
    """嵌入内容数据结构"""
    url: str
    content_type: str  # 'blog' | 'youtube'
    title: str = ''
    content: str = ''
    metadata: Dict = field(default_factory=dict)


class LinkExtractor:
    """从文本中提取和分类URL"""
    
    # 需要跳过的域名（社交媒体自身的链接，不作为博客处理）
    SKIP_DOMAINS = ['twitter.com', 'x.com', 't.co', 'pic.twitter.com']
    
    # YouTube相关域名
    YOUTUBE_DOMAINS = ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com']
    
    # 媒体资源域名（图片、视频等）
    MEDIA_DOMAINS = ['twimg.com', 'pbs.twimg.com', 'video.twimg.com']
    
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
        分类提取博客链接、YouTube链接和媒体链接
        
        参数:
            text: 要解析的文本内容
        
        返回:
            (blog_links, youtube_links, media_urls) 三元组
        """
        urls = cls.extract_urls(text)
        blog_links = []
        youtube_links = []
        media_urls = []
        
        for url in urls:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # 检查是否为YouTube链接
            if any(yt in domain for yt in cls.YOUTUBE_DOMAINS):
                youtube_links.append(url)
            # 检查是否为媒体资源链接（图片、视频）
            elif any(media in domain for media in cls.MEDIA_DOMAINS):
                media_urls.append(url)
            # 检查是否需要跳过（社交媒体自身链接）
            elif domain and not any(skip in domain for skip in cls.SKIP_DOMAINS):
                blog_links.append(url)
        
        return blog_links, youtube_links, media_urls


class YouTubeFetcher:
    """YouTube视频信息获取器"""
    
    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        """
        从URL提取视频ID
        
        支持的URL格式:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
        - https://m.youtube.com/watch?v=VIDEO_ID
        
        参数:
            url: YouTube视频URL
        
        返回:
            视频ID，如果无法提取则返回None
        """
        if not url:
            return None
        
        try:
            parsed = urlparse(url)
            
            # 处理 youtu.be 短链接
            if 'youtu.be' in parsed.netloc:
                # 路径格式: /VIDEO_ID 或 /VIDEO_ID?params
                video_id = parsed.path.lstrip('/').split('?')[0]
                return video_id if video_id else None
            
            # 处理 youtube.com 标准链接
            if 'youtube.com' in parsed.netloc:
                # 检查 /watch?v=VIDEO_ID 格式
                if '/watch' in parsed.path:
                    query_params = parse_qs(parsed.query)
                    video_ids = query_params.get('v', [])
                    return video_ids[0] if video_ids else None
                
                # 检查 /embed/VIDEO_ID 格式
                if '/embed/' in parsed.path:
                    parts = parsed.path.split('/embed/')
                    if len(parts) > 1:
                        return parts[1].split('/')[0].split('?')[0]
            
            return None
        except Exception:
            return None
    
    def fetch_transcript(self, video_id: str) -> str:
        """
        获取视频字幕
        
        TODO: 后续使用更优方案实现
        可选方案：
        - youtube-transcript-api
        - yt-dlp 提取字幕
        - Google Cloud Speech-to-Text
        - Whisper 本地转录
        
        参数:
            video_id: YouTube视频ID
        
        返回:
            视频字幕文本，当前返回空字符串（待实现）
        """
        # TODO: 待实现
        return ''
    
    def fetch(self, url: str) -> Optional[EmbeddedContent]:
        """
        获取YouTube视频的完整信息
        
        参数:
            url: YouTube视频URL
        
        返回:
            EmbeddedContent对象，如果无法提取则返回None
        """
        video_id = self.extract_video_id(url)
        if not video_id:
            log(f"    无法从URL提取视频ID: {url}")
            return None
        
        transcript = self.fetch_transcript(video_id)
        
        return EmbeddedContent(
            url=url,
            content_type='youtube',
            title='',  # 可后续扩展获取标题
            content=transcript,
            metadata={'video_id': video_id}
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
            
            log(f"    博客爬取返回空结果: {url}")
            return None
            
        except Exception as e:
            log(f"    博客爬取失败 [{url}]: {e}")
            return None


class ContentFetcher:
    """
    内容爬取统一入口（门面模式）
    
    提供简洁的API，隐藏内部的链接提取和分类爬取逻辑
    """
    
    def __init__(self):
        self.youtube_fetcher = YouTubeFetcher()
        self.blog_fetcher = BlogFetcher()
    
    def fetch_embedded_content(self, text: str) -> Tuple[List[EmbeddedContent], List[str]]:
        """
        从文本中提取并爬取所有嵌入内容
        
        参数:
            text: 包含URL的文本内容（如推文正文）
        
        返回:
            (embedded_contents, all_urls) 元组
            - embedded_contents: 爬取到的嵌入内容列表（博客、YouTube）
            - all_urls: 所有外部资源链接（博客URL、YouTube URL、媒体URL）
        """
        if not text:
            return [], []
        
        # 提取并分类URL
        blog_links, youtube_links, media_urls = LinkExtractor.categorize(text)
        results = []
        
        # 处理YouTube链接
        for url in youtube_links:
            try:
                log(f"    正在获取YouTube内容: {url}")
                content = self.youtube_fetcher.fetch(url)
                if content:
                    results.append(content)
            except Exception as e:
                log(f"    YouTube内容获取失败 [{url}]: {e}")
        
        # 处理博客链接
        for url in blog_links:
            try:
                log(f"    正在获取博客内容: {url}")
                content = self.blog_fetcher.fetch(url)
                if content:
                    results.append(content)
            except Exception as e:
                log(f"    博客内容获取失败 [{url}]: {e}")
        
        # 合并所有外部资源链接（博客、YouTube、媒体）
        all_urls = blog_links + youtube_links + media_urls
        
        return results, all_urls
    
    def fetch_youtube_transcript(self, url: str) -> Optional[EmbeddedContent]:
        """
        直接获取YouTube视频字幕（用于YouTube RSS源）
        
        参数:
            url: YouTube视频URL
        
        返回:
            EmbeddedContent对象，如果获取失败则返回None
        """
        return self.youtube_fetcher.fetch(url)
