"""
common.py - 公共配置和工具函数
"""
import os
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
    调用 LLM 对单篇文章进行标准化整理
    """
    content = post['content']
    
    prompt = f"""
    你是一个专业的数据整理助手。请对以下来自【{source_name}】的文章进行标准化整理。
    
    要求：
    1. 输出格式（输出为 Markdown 表格的一行（不需要表头）, 请严格遵守，以 | 开头和结尾）：| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 | 所属领域 |
    2. 输出示例：| 2026-01-17 | OpenAI发布GPT-5 | 1. 支持多模态<br>2. 上下文100万tokens | [原文链接](https://example.com) | OpenAI宣布发布GPT-5，这是迄今为止最强大的语言模型... | 技术发布 |
    3. 列顺序：日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 | 所属领域 |
    4. 各列说明：
       - **日期**: {post['date']}
       - **事件**: 简练概括发生了什么（标题/核心动作），在原始标题足够描述事件的情况下尽可能重用原始标题来描述事件。
       - **关键信息**: 提取 1-5 点核心细节，用 <br> 分隔
       - **原文链接**: [原文链接]({post['link']})
       - **详细内容**: 若原文是X的推文，则保留原始推文内容；若原文不长且可读性良好也直接输出原文；其他情况则对原始内容进行格式优化（比如去掉HTML标签），结构化整理输出为一段对原文的详细描述,要求尽可能把原文的脉络梳理清楚，不要过于概括和简略。
       - **事件分类**: 给该事件打一个标签（如：技术发布、产品动态、观点分享、商业资讯、技术活动（meetup/会议/沙龙）、客户案例、广告招聘、其他）
       - **所属领域**: 给该事件打一个所属领域标签（从：大模型技术和产品、数据平台和框架、AI平台和框架、智能体平台和框架、代码智能体（IDE）、数据智能体、行业或领域智能体、具身智能、其他 中选择一个）
    5. 如果是纯广告或无实质内容，返回空字符串。
    6. 只输出表格行，不要输出其他内容。

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
            {"role": "system", "content": "You are a helpful assistant for data organization. Output only the requested format, no extra text."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content.strip()


def organize_data(posts, source_name):
    """
    调用 LLM 对信息进行标准化整理 (逐篇处理，避免上下文超限)
    """
    if not posts:
        return f"【{source_name}】最近 {DAYS_LOOKBACK} 天没有更新。"

    # 表头
    table_header = "| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 事件分类 | 所属领域 |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    
    # 逐篇处理
    rows = []
    for idx, post in enumerate(posts):
        log(f"    正在整理 [{source_name}] 第 {idx+1}/{len(posts)} 篇: {post['title'][:30]}...")
        try:
            row = organize_single_post(post, source_name)
            if not row:
                log(f"    跳过（LLM返回空）")
                continue
            # 容错处理：如果 LLM 漏掉了开头的 |，自动补上
            if not row.startswith('|'):
                row = '| ' + row
            # 确保结尾也有 |
            if not row.endswith('|'):
                row = row + ' |'
            rows.append(row)
        except Exception as e:
            log(f"    整理失败: {e}")
            continue
    
    if not rows:
        return f"【{source_name}】最近 {DAYS_LOOKBACK} 天的内容均无实质信息。"
    
    # 组合表格
    return table_header + "\n" + "\n".join(rows)
