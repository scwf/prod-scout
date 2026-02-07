"""
llm_organizer.py - OrganizerStage for Native Python Pipeline.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue

from openai import OpenAI

from common import setup_logger, _tid

logger = setup_logger("llm_organizer")

def organize_single_post(post, source_name, llm_client, llm_config, max_retries=3, retry_delay=3):
    """
    调用 LLM 对单篇文章进行标准化整理，返回 JSON 结构化数据
    
    参数:
        post: dict - 文章数据
        source_name: str - 来源名称
        max_retries: int - 最大重试次数 (默认 3)
        retry_delay: int - 重试间隔秒数 (默认 3)
    
    返回:
        dict: 包含 date, event, key_info, link, detail, category, domain, source_name 字段
        None: 如果是纯广告或无实质内容
    """
    content = post['content']
    
    prompt = f"""
你是一位资深的 Data & AI 领域情报分析专家，拥有 10 年行业经验。
你的专长包括：大模型技术、AI/数据平台框架、智能体应用、行业AI落地。
你的任务是对原始信息进行结构化整理，整理后的数据将用于Data & AI产品分析、行业洞察和决策支持。

请对以下来自【{source_name}】的文章进行标准化整理，输出为 JSON 格式。

请严格按照以下 JSON 格式输出：

EXAMPLE JSON OUTPUT:
{{
    "event": "OpenAI发布GPT-5",
    "key_info": "1. 支持多模态<br>2. 上下文100万tokens",
    "detail": "OpenAI宣布发布GPT-5，这是迄今为止最强大的语言模型...",
    "category": "技术发布",
    "domain": "大模型技术和产品",
    "quality_score": 5,
    "quality_reason": "重大产品发布，包含关键技术参数"
}}

各字段说明：
- **event**: 简练概括发生了什么（标题/核心动作），在原始标题足够描述事件的情况下尽可能重用原始标题来描述事件
- **key_info**: 提取 1-5 点核心细节，用 <br> 分隔，作为一段字符串
- **detail**: 若原文是X的推文，则保留原始推文内容；若原文不长且可读性良好也直接输出原文；其他情况则对原始内容进行格式优化（比如去掉HTML标签），结构化整理输出为一段对原文的详细描述，要求尽可能把原文的脉络梳理清楚，不要过于概括和简略
- **category**: 事件分类标签，从以下选择一个：技术发布、产品动态、观点分享、商业资讯、技术活动、客户案例、广告招聘、其他
- **domain**: 所属领域标签，必须从以下选择一个：大模型技术和产品、数据平台和框架、AI平台和框架、智能体平台和框架、代码智能体（IDE）、数据智能体、行业或领域智能体、具身智能、其他
- **quality_score**: 内容质量评分(1-5分)，评分标准：
  - 5分(高价值): 有重要数据、深度洞察、独家信息、重大事件发布
  - 4分(值得关注): 有实质内容、有参考价值、值得跟进
  - 3分(一般): 信息一般、可作为背景参考
  - 2分(价值有限): 内容单薄、缺乏深度、信息密度低
  - 1分(无价值): 无实质内容、纯营销广告、完全不相关
- **quality_reason**: 简短说明评分理由

原始数据：
标题: {post['title']}
时间: {post['date']}
原文链接: {post['link']}
来源类型: {post['source_type']}
内容: {content}
补充内容: {post.get('extra_content', '')}
"""

    # 带重试机制的 API 调用
    result_text = None
    finish_reason = None
    
    for attempt in range(max_retries + 1):
        try:
            start_ts = time.time()
            response = llm_client.chat.completions.create(
                model=llm_config.get('llm', 'model'),
                messages=[
                    {"role": "system", "content": "You are a helpful assistant for data organization. Output only valid JSON, no extra text."},
                    {"role": "user", "content": prompt}
                ],
                response_format={'type': 'json_object'}
            )
            elapsed = time.time() - start_ts
            logger.info(f"LLM Response Time: {elapsed:.2f}s for {post['title'][:30]}...")
            
            # 获取响应内容和完成原因
            result_text = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # 处理 None 或空字符串
            if not result_text or not result_text.strip():
                if attempt < max_retries:
                    logger.warning(f"⚠️ [LLM-Empty][{post['title'][:30]}] sleep {retry_delay}s to retry... (Reason: {finish_reason})")
                    time.sleep(retry_delay)
                    continue
                logger.error(f"❌ [LLM-Fail][{post['title'][:30]}] Empty response after retries.")
                return None
            
            # 成功获取响应，跳出重试循环
            result_text = result_text.strip()
            break
            
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"⚠️ [LLM-Error][{post['title'][:30]}] {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                continue
            # 最后一次重试也失败，抛出异常
            logger.error(f"❌ [LLM-Fail][{post['title'][:30]}] Final attempt failed: {e}")
            raise
    
    # 解析 JSON 响应
    try:
        result = json.loads(result_text)    
    except json.JSONDecodeError as e:
        logger.error(f"❌ [JSON-Fail] {post['link']} Parse error: {e}")
        logger.error(f"❌ [JSON-Fail] {result_text}")
        return None

    # 补全基础字段 (减少LLM输出)
    result['date'] = post.get('date', '')
    result['link'] = post.get('link', '')
    result['source_name'] = source_name
    
    # 添加 extra_content 和 extra_urls
    result['extra_content'] = post.get('extra_content', '')
    result['extra_urls'] = post.get('extra_urls', [])

    # Final Success Log
    logger.info(f"🤖 [Organized] {result.get('domain', 'Unknown')} | Score: {result.get('quality_score')} | {post['title'][:50]}...")

    return result

class OrganizerStage:
    def __init__(self, enrich_queue: Queue, organize_queue: Queue, config):
        self.enrich_queue = enrich_queue
        self.organize_queue = organize_queue
        self.config = config
        self.client = OpenAI(
            api_key=self.config.get('llm', 'api_key'),
            base_url=self.config.get('llm', 'base_url'),
        )
        
        self.max_workers = config.getint('crawler', 'organize_workers', fallback=5)
        self.pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="Organizer")
        self.futures = []

    def start(self):
        """Start consumer workers."""
        logger.info(f"Starting OrganizerStage with {self.max_workers} workers...")
        for _ in range(self.max_workers):
            self.futures.append(
                self.pool.submit(self._worker_loop)
            )

    def stop(self):
        """Graceful shutdown."""
        logger.info("Stopping OrganizerStage... Sending poison pills.")
        for _ in range(self.max_workers):
            self.enrich_queue.put(None)
        
        self.pool.shutdown(wait=True)
        logger.info("OrganizerStage stopped.")

    def _worker_loop(self):
        while True:
            post = self.enrich_queue.get()
            
            if post is None:
                self.enrich_queue.task_done()
                break
            
            try:
                # organize_single_post comes from local module now
                source_name = post.get('source_name', 'Unknown')
                
                # If post is broken or somehow None (integrity check)
                if not post:
                    continue
                    
                result = organize_single_post(
                    post,
                    source_name,
                    llm_client=self.client,
                    llm_config=self.config,
                )
                
                if result:
                    self.organize_queue.put(result)
                else:
                    # Logic: if None returned, it means skip (ad or empty)
                    pass
                    
            except Exception as e:
                logger.error(f"Organizer task failed: {e}")
            finally:
                self.enrich_queue.task_done()
