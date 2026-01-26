"""
common.py - 公共配置和工具函数
"""
import os
import json
import time
import configparser
from datetime import datetime
from openai import OpenAI

# 时间范围配置,爬取最近多少天的内容
DAYS_LOOKBACK = 5

# 批次清单文件名
MANIFEST_FILENAME = "latest_batch.json"


def log(message):
    """带时间戳的日志输出"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")

# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'), encoding='utf-8')

# 设置 LLM API (从 config.ini 配置文件读取)
client = OpenAI(
    api_key=config.get('llm', 'api_key'), 
    base_url=config.get('llm', 'base_url')
)


def organize_single_post(post, source_name, max_retries=3, retry_delay=3):
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
你是一个专业的数据整理助手。请对以下来自【{source_name}】的文章进行标准化整理，输出为 JSON 格式。

请严格按照以下 JSON 格式输出：

EXAMPLE JSON OUTPUT:
{{
    "date": "2026-01-17",
    "event": "OpenAI发布GPT-5",
    "key_info": "1. 支持多模态<br>2. 上下文100万tokens",
    "link": "https://example.com",
    "detail": "OpenAI宣布发布GPT-5，这是迄今为止最强大的语言模型...",
    "category": "技术发布",
    "domain": "大模型技术和产品"
}}

各字段说明：
- **date**: 日期，格式为 YYYY-MM-DD，使用原始日期: {post['date']}
- **event**: 简练概括发生了什么（标题/核心动作），在原始标题足够描述事件的情况下尽可能重用原始标题来描述事件
- **key_info**: 提取 1-5 点核心细节，用 <br> 分隔，作为一段字符串
- **link**: 原文链接，使用: {post['link']}
- **detail**: 若原文是X的推文，则保留原始推文内容；若原文不长且可读性良好也直接输出原文；其他情况则对原始内容进行格式优化（比如去掉HTML标签），结构化整理输出为一段对原文的详细描述，要求尽可能把原文的脉络梳理清楚，不要过于概括和简略
- **category**: 事件分类标签，从以下选择一个：技术发布、产品动态、观点分享、商业资讯、技术活动、客户案例、广告招聘、其他
- **domain**: 所属领域标签，必须从以下选择一个：大模型技术和产品、数据平台和框架、AI平台和框架、智能体平台和框架、代码智能体（IDE）、数据智能体、行业或领域智能体、具身智能、其他

如果是纯广告或无实质内容，返回: {{"skip": true}}

原始数据：
标题: {post['title']}
时间: {post['date']}
原文链接: {post['link']}
来源类型: {post['source_type']}
内容: {content}
"""

    # 带重试机制的 API 调用
    result_text = None
    finish_reason = None
    
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=config.get('llm', 'model'),
                messages=[
                    {"role": "system", "content": "You are a helpful assistant for data organization. Output only valid JSON, no extra text."},
                    {"role": "user", "content": prompt}
                ],
                response_format={'type': 'json_object'}
            )
            
            # 获取响应内容和完成原因
            result_text = response.choices[0].message.content
            finish_reason = response.choices[0].finish_reason
            
            # 处理 None 或空字符串
            if not result_text or not result_text.strip():
                if attempt < max_retries:
                    log(f"    LLM 返回空响应 (finish_reason: {finish_reason})，{retry_delay}秒后重试 ({attempt+1}/{max_retries})...")
                    time.sleep(retry_delay)
                    continue
                log(f"    LLM 返回空响应 (finish_reason: {finish_reason})，已重试 {max_retries} 次，跳过")
                return None
            
            # 成功获取响应，跳出重试循环
            result_text = result_text.strip()
            break
            
        except Exception as e:
            if attempt < max_retries:
                log(f"    API 调用失败: {e}，{retry_delay}秒后重试 ({attempt+1}/{max_retries})...")
                time.sleep(retry_delay)
                continue
            # 最后一次重试也失败，抛出异常
            raise
    
    # 解析 JSON 响应
    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as e:
        log(f"    JSON 解析失败: {e}")
        log(f"    原始响应内容: {result_text[:200]}..." if len(result_text) > 200 else f"    原始响应内容: {result_text}")
        return None
    
    # 检查是否为跳过标记
    if result.get('skip'):
        return None
    
    # 添加来源名称
    result['source_name'] = source_name
    
    return result


def organize_data(posts, source_name):
    """
    调用 LLM 对信息进行标准化整理 (逐篇处理，避免上下文超限)
    
    返回:
        list[dict]: 包含所有整理后的文章数据列表，每个 dict 包含:
            date, event, key_info, link, detail, category, domain, source_name
    """
    if not posts:
        return []
    
    # 逐篇处理
    organized_posts = []
    for idx, post in enumerate(posts):
        log(f"    正在整理 [{source_name}] 第 {idx+1}/{len(posts)} 篇: {post['title'][:30]}...")
        try:
            result = organize_single_post(post, source_name)
            if not result:
                log(f"    跳过（LLM返回空或无实质内容）")
                continue
            organized_posts.append(result)
        except Exception as e:
            log(f"    整理失败: {e}")
            continue
    
    return organized_posts


def escape_markdown_table(text):
    """
    转义 Markdown 表格中的特殊字符
    
    参数:
        text: str - 需要转义的文本
    
    返回:
        str: 转义后的文本
    """
    if not text:
        return ''
    # 转换为字符串（防止非字符串类型）
    text = str(text)
    # 替换换行符为 <br>
    text = text.replace('\r\n', '<br>').replace('\n', '<br>').replace('\r', '')
    # 转义管道符
    text = text.replace('|', '\\|')
    return text


def posts_to_markdown_table(posts, title=None):
    """
    将文章列表转换为 Markdown 表格格式
    
    参数:
        posts: list[dict] - 整理后的文章数据列表
        title: str - 可选的标题
    
    返回:
        str: Markdown 格式的表格
    """
    if not posts:
        return ""
    
    # 表头
    table_header = "| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 事件分类 | 所属领域 |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    
    rows = []
    for post in posts:
        # 构建表格行（对自由文本字段进行转义处理，防止表格显示异常）
        row = "| {date} | {event} | {key_info} | [原文链接]({link}) | {detail} | {category} | {domain} |".format(
            date=post.get('date', ''),  # 固定格式 YYYY-MM-DD
            event=escape_markdown_table(post.get('event', '')),
            key_info=escape_markdown_table(post.get('key_info', '')),
            link=post.get('link', ''),  # URL 不转义
            detail=escape_markdown_table(post.get('detail', '')),
            category=post.get('category', ''),  # 预定义枚举值
            domain=post.get('domain', '')  # 预定义枚举值
        )
        rows.append(row)
    
    result = table_header + "\n" + "\n".join(rows)
    
    if title:
        result = f"### {title}\n{result}"
    
    return result


def group_posts_by_domain(all_posts):
    """
    按所属领域对文章进行分组
    
    参数:
        all_posts: list[dict] - 所有整理后的文章数据列表
    
    返回:
        dict: {domain: list[dict]} - 按领域分组的文章
    """
    grouped = {}
    for post in all_posts:
        domain = post.get('domain', '其他')
        if domain not in grouped:
            grouped[domain] = []
        grouped[domain].append(post)
    return grouped


# ================= 批次清单管理 =================

def save_batch_manifest(output_dir, batch_id, domain_reports, summary_report=None, stats=None):
    """
    保存批次清单文件
    
    参数:
        output_dir: str - 输出目录路径
        batch_id: str - 批次ID (通常是时间戳，如 20260124_123456)
        domain_reports: dict - 领域报告映射 {领域名称: 文件名}
        summary_report: str - 汇总报告文件名 (可选)
        stats: dict - 统计信息 (可选)
    
    返回:
        str: 清单文件的完整路径
    """
    manifest = {
        "batch_id": batch_id,
        "created_at": datetime.now().isoformat(),
        "source": "rss_crawler",
        "domain_reports": domain_reports,
    }
    
    if summary_report:
        manifest["summary_report"] = summary_report
    
    if stats:
        manifest["stats"] = stats
    
    manifest_path = os.path.join(output_dir, MANIFEST_FILENAME)
    
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    log(f"批次清单已保存: {MANIFEST_FILENAME}")
    return manifest_path


def load_batch_manifest(data_dir):
    """
    加载最新的批次清单
    
    参数:
        data_dir: str - 数据目录路径
    
    返回:
        dict: 清单内容，包含 batch_id, domain_reports 等
        None: 如果清单文件不存在或解析失败
    """
    manifest_path = os.path.join(data_dir, MANIFEST_FILENAME)
    
    if not os.path.exists(manifest_path):
        return None
    
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        return manifest
    except (json.JSONDecodeError, IOError) as e:
        log(f"读取批次清单失败: {e}")
        return None


def get_domain_report_paths(data_dir, manifest):
    """
    从清单中获取领域报告的完整路径
    
    参数:
        data_dir: str - 数据目录路径
        manifest: dict - 批次清单
    
    返回:
        dict: {领域名称: 完整文件路径}
    """
    domain_reports = manifest.get("domain_reports", {})
    result = {}
    
    for domain, filename in domain_reports.items():
        full_path = os.path.join(data_dir, filename)
        if os.path.exists(full_path):
            result[domain] = full_path
        else:
            log(f"警告: 领域报告文件不存在: {filename}")
    
    return result
