"""
llm_organizer.py - OrganizerStage for Native Python Pipeline.
"""
import json
import time
import os
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from openai import OpenAI
from common import setup_logger, _tid

logger = setup_logger("llm_organizer")

def organize_single_post(post, prompt_template, llm_client, llm_config, entity_list='', max_retries=3, retry_delay=3):
    """
    调用 LLM 对单篇文章进行标准化整理，返回 JSON 结构化数据
    
    参数:
        post: dict - 文章数据
        prompt_template: str - 提示词模板
        max_retries: int - 最大重试次数 (默认 3)
        retry_delay: int - 重试间隔秒数 (默认 3)
    
    返回:
        dict: 包含 date, event, key_info, link, detail, category, domain, source_name 等字段
    """
    if not prompt_template:
        logger.error(f"❌ [Prompt-Missing] No prompt template provided for {post.get('link', 'unknown')}")
        return None

    content = post['content']
    
    # 2. Prepare Context
    context = {
        'title': post.get('title', ''),
        'date': post.get('date', ''),
        'link': post.get('link', ''),
        'source_type': post.get('source_type', ''),
        'source_name': post.get('source_name', ''),  # Added for potential prompt usage
        'content': post.get('content', ''),
        'extra_content': post.get('extra_content', ''),
        'extra_urls': post.get('extra_urls', []),
        'entity_list': entity_list
    }
    
    # 3. Format Prompt
    try:
        prompt = prompt_template.format(**context)
    except KeyError as e:
        logger.error(f"Prompt format error: missing key {e}. Check your prompt template.")
        return None

    # Fallback if file load failed or format failed
    if not prompt:
        logger.error(f"❌ [Prompt-Fail] Could not load or format prompt for {post['link']}")
        return None

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

    # 补全基础字段
    result['date'] = post.get('date', '')
    result['link'] = post.get('link', '')
    result['source_name'] = post.get('source_name', '')
    result['source_type'] = post.get('source_type', '')
    
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
        
        # Load prompt template once during initialization
        self.prompt_template = self._load_prompt_template()
        self.entity_list = self._load_entity_list()
        
        self.max_workers = config.getint('crawler', 'organize_workers', fallback=5)
        self.pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="Organizer")
        self.futures = []

    def _load_prompt_template(self):
        """Load prompt template from file."""
        try:
            config_path = self.config.get('llm', 'prompt_template', fallback='prompts/organizer_prompt.md')
            
            # Resolve path
            target_path = config_path
            if not os.path.isabs(config_path):
                 # Resolve relative to project root (assuming native_scout/stages is CWD or handled by pipeline pathing logic?)
                 # Better to rely on __file__ relative path anchor
                 project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                 target_path = os.path.join(project_root, config_path)
            
            if os.path.exists(target_path):
                with open(target_path, 'r', encoding='utf-8') as f:
                    logger.info(f"Loaded prompt template from {target_path}")
                    return f.read()
            else:
                logger.error(f"❌ Prompt file not found at {target_path}")
                return ""
        except Exception as e:
            logger.error(f"❌ Failed to load prompt template: {e}")
            return ""

    def _load_entity_list(self):
        """Load entity names from config [entity_mapping] section as comma-separated string."""
        if self.config.has_section('entity_mapping'):
            entities = list(self.config.options('entity_mapping'))
            logger.info(f"Loaded {len(entities)} entities for prompt: {', '.join(entities)}")
            return ', '.join(entities)
        return ''

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
                # If post is broken or somehow None (integrity check)
                if not post:
                    continue
                    
                result = organize_single_post(
                    post,
                    prompt_template=self.prompt_template,
                    llm_client=self.client,
                    llm_config=self.config,
                    entity_list=self.entity_list,
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
