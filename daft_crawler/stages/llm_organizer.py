"""
llm_organizer.py - LLM organizing stage for Daft pipeline.
"""
import json
import asyncio
import daft
from daft import col, DataType
from openai import AsyncOpenAI

from common import setup_logger, get_organize_concurrency


logger = setup_logger("daft_llm_organizer")

ORGANIZED_STRUCT = DataType.struct(
    {
        "event": DataType.string(),
        "key_info": DataType.string(),
        "detail": DataType.string(),
        "category": DataType.string(),
        "domain": DataType.string(),
        "quality_score": DataType.int64(),
        "quality_reason": DataType.string(),
    }
)


def _tid():
    return f"[T{threading.current_thread().name.split('_')[-1]}]"


def _build_prompt(post, source_name):
    content = post["content"]
    return f"""
你是一位资深的 Data & AI 领域情报分析专家，拥有 10 年行业经验。你的任务是对原始信息进行结构化整理，输出为 JSON。
请对以下来自「{source_name}」的文章进行标准化整理，仅输出有效 JSON。

EXAMPLE JSON OUTPUT:
{{
  "event": "OpenAI发布GPT-5",
  "key_info": "1. 支持多模态<br>2. 上下文100万tokens",
  "detail": "OpenAI宣布发布GPT-5，这是迄今最强大的语言模型...",
  "category": "技术发布",
  "domain": "大模型技术和产品",
  "quality_score": 5,
  "quality_reason": "重大产品发布，包含关键技术参数"
}}

字段说明：
- event: 简洁概括发生了什么，尽量复用原标题
- key_info: 1-5 条关键信息，用 <br> 分隔
- detail: 若原文很短可直接输出原文；否则结构化整理，避免过度概括
- category: 事件分类，选其一：技术发布、产品动态、观点分享、商业融资、技术活动、客户案例、广告招聘、其他
- domain: 所属领域，选其一：大模型技术和产品、数据平台和架构、AI平台和架构、智能体平台和架构、代码智能体(IDE)、数据智能体、行业或领域智能体、具身智能、其他
- quality_score: 内容质量评分(1-5)
- quality_reason: 评分理由
如果是纯广告或无实质内容，返回 {{"skip": true}}

原始数据：
标题: {post['title']}
时间: {post['date']}
原文链接: {post['link']}
来源类型: {post['source_type']}
内容: {content}
补充内容: {post.get('extra_content', '')}
"""

@daft.cls(max_concurrency=get_organize_concurrency(), use_process=False)
class OrganizeUDF:
    def __init__(self, config):
        self.client = AsyncOpenAI(
            api_key=config.get("llm", "api_key"),
            base_url=config.get("llm", "base_url"),
        )
        self.model = config.get("llm", "model")
        # Global concurrency limit for LLM calls per worker to avoid 429
        max_concurrency = config.getint("llm", "max_concurrency", fallback=10)
        self.semaphore = asyncio.Semaphore(max_concurrency)

    @daft.method(return_dtype=ORGANIZED_STRUCT, unnest=True)
    async def __call__(
        self,
        title: str,
        date: str,
        link: str,
        source_type: str,
        source_name: str,
        content: str,
        extra_content: str,
        extra_urls: list,
    ):

        post = {
            "title": title,
            "date": date,
            "link": link,
            "source_type": source_type,
            "source_name": source_name,
            "content": content,
            "extra_content": extra_content,
            "extra_urls": extra_urls,
        }

        try:
            # Use semaphore to limit concurrent LLM requests
            async with self.semaphore:
                result = await self._organize_single_post(post, source_name)
        except Exception:
            result = None

        if not result:
            return None

        return result

    async def _organize_single_post(self, post, source_name, max_retries=3, retry_delay=3):
        prompt = _build_prompt(post, source_name)
        result_text = None
        finish_reason = None

        for attempt in range(max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant for data organization. Output only valid JSON, no extra text.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                )

                result_text = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                if not result_text or not result_text.strip():
                    if attempt < max_retries:
                        logger.info(
                            f"{_tid()} LLM empty response (finish_reason: {finish_reason}); retry in {retry_delay}s ({attempt+1}/{max_retries})"
                        )
                        await asyncio.sleep(retry_delay)
                        continue
                    logger.info(
                        f"{_tid()} LLM empty response (finish_reason: {finish_reason}); skip after {max_retries} retries"
                    )
                    return None

                result_text = result_text.strip()
                break

            except Exception as e:
                if attempt < max_retries:
                    logger.info(
                        f"{_tid()} API call failed: {e}; retry in {retry_delay}s ({attempt+1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as e:
            logger.info(f"{_tid()} JSON parse failed: {e}")
            preview = result_text[:200] + "..." if len(result_text) > 200 else result_text
            logger.info(f"{_tid()} Raw response: {preview}")
            return None

        if result.get("skip"):
            logger.info(f"{_tid()} LLM returned skip: {result}")
            return None

        # Redundant fields are no longer injected here
        return result


class LLMOrganizer:
    def __init__(self, config):
        self.organize_udf = OrganizeUDF(config)

    def organize(self, df):
        return df.select(
            col("*"),
            self.organize_udf(
                col("title"),
                col("date"),
                col("link"),
                col("source_type"),
                col("source_name"),
                col("content"),
                col("extra_content"),
                col("extra_urls"),
            ),
        )
