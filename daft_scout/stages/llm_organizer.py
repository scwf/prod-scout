"""
llm_organizer.py - LLM organizing stage for Daft pipeline.
"""
import json
import time
import os
import threading
import daft
from daft import col, DataType
from openai import OpenAI

from common.config import load_project_ini
from common.logging import setup_logger


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


def _get_organize_concurrency():
    config = load_project_ini(__file__, "config-test.ini", package_depth=1)
    return config.getint("crawler", "organize_workers", fallback=5)


@daft.cls(max_concurrency=_get_organize_concurrency(), use_process=False)
class OrganizeUDF:
    def __init__(self, config):
        self.client = OpenAI(
            api_key=config.get("llm", "api_key"),
            base_url=config.get("llm", "base_url"),
        )
        self.model = config.get("llm", "model")
        self.prompt_template = self._load_prompt_template(config)

    def _load_prompt_template(self, config):
        try:
            config_path = config.get("llm", "prompt_template", fallback="prompts/organizer_prompt.md")
            
            # Resolve path (relative to project root)
            # daft_scout/stages/llm_organizer.py -> ... -> root
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            target_path = config_path
            
            if not os.path.isabs(config_path):
                target_path = os.path.join(project_root, config_path)
            
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    logger.info(f"Loaded prompt template from {target_path}")
                    return f.read()
            else:
                logger.error(f"Prompt file not found at {target_path}")
                return ""
        except Exception as e:
            logger.error(f"Failed to load prompt template: {e}")
            return ""

    @daft.method(return_dtype=ORGANIZED_STRUCT, unnest=True)
    def __call__(
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
            result = self._organize_single_post(post, source_name)
        except Exception:
            result = None

        if not result:
            return None

        return result

    def _organize_single_post(self, post, source_name, max_retries=3, retry_delay=3):
        if not self.prompt_template:
            logger.error(f"No prompt template loaded for {post['link']}")
            return None
            
        # Prepare context (explicitly list fields)
        context = {
            "title": post.get("title", ""),
            "date": post.get("date", ""),
            "link": post.get("link", ""),
            "source_type": post.get("source_type", ""),
            "source_name": post.get("source_name", ""),
            "content": post.get("content", ""),
            "extra_content": post.get("extra_content", ""),
            "extra_urls": post.get("extra_urls", []),
        }

        try:
            prompt = self.prompt_template.format(**context)
        except KeyError as e:
            logger.error(f"Prompt format error: missing key {e}")
            return None
            
        result_text = None
        finish_reason = None

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
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
                        time.sleep(retry_delay)
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
                    time.sleep(retry_delay)
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
