"""
common.py - 公共配置和工具函数
"""
import os
import json
import configparser
from datetime import datetime
from openai import OpenAI

# 时间范围配置,爬取最近多少天的内容
DAYS_LOOKBACK = 2


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


def organize_single_post(post, source_name):
    """
    调用 LLM 对单篇文章进行标准化整理，返回 JSON 结构化数据
    
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

    response = client.chat.completions.create(
        model=config.get('llm', 'model'),
        messages=[
            {"role": "system", "content": "You are a helpful assistant for data organization. Output only valid JSON, no extra text."},
            {"role": "user", "content": prompt}
        ],
        response_format={'type': 'json_object'}
    )
    
    result_text = response.choices[0].message.content.strip()
    
    # 解析 JSON 响应
    try:
        result = json.loads(result_text)
    except json.JSONDecodeError as e:
        log(f"    JSON 解析失败: {e}")
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
        # key_info 现在是字符串
        key_info_str = post.get('key_info', '')
        
        # 构建表格行
        row = "| {date} | {event} | {key_info} | [原文链接]({link}) | {detail} | {category} | {domain} |".format(
            date=post.get('date', ''),
            event=post.get('event', ''),
            key_info=key_info_str,
            link=post.get('link', ''),
            detail=post.get('detail', ''),
            category=post.get('category', ''),
            domain=post.get('domain', '')
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
