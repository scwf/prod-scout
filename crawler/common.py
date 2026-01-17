"""
common.py - 公共配置和工具函数
"""
import os
import configparser
from openai import OpenAI

# 加载配置文件 (config.ini，位于项目根目录)
config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), '..', 'config.ini'), encoding='utf-8')

# 设置 LLM API (从 config.ini 配置文件读取)
client = OpenAI(
    api_key=config.get('llm', 'api_key'), 
    base_url=config.get('llm', 'base_url')
)

# 时间范围配置
DAYS_LOOKBACK = 7


def organize_data(posts, source_name):
    """
    调用 LLM 对信息进行标准化整理 (时间、事件维度)
    """
    if not posts:
        return f"【{source_name}】最近 {DAYS_LOOKBACK} 天没有更新。"

    # 构建 Prompt
    data_text = ""
    for idx, post in enumerate(posts):
        content = post['content']
        data_text += f"ID: {idx+1}\n标题: {post['title']}\n时间: {post['date']}\n原文链接: {post['link']}\n来源类型: {post['source_type']}\n内容: {content}\n\n"

    prompt = f"""
    你是一个专业的数据整理助手。请对以下来自【{source_name}】的原始数据进行标准化整理。
    
    目标：
    不要生成笼统的总结报告。请按照"时间"和"事件"维度，将每条有价值的信息结构化展示和输出。
    
    要求：
    1. 按时间倒序排列（最新的在最前）。
    2. 每一项需包含：
       - **日期**: YYYY-MM-DD
       - **事件**: 简练概括发生了什么（标题/核心动作）
       - **关键信息**: 提取 1-3 点核心细节（如发布了什么模型、具体参数、活动地点等）
       - **原文链接**: 原文链接
       - **详细内容**: 若原文是X的推文，则保留原始推文内容；若原文不长且可读性良好也直接输出原文；其他情况则对原始内容进行格式优化（比如去掉HTML标签）,结构化整理输出为一段对原文的详细描述。
       - **分类**: 给该事件打一个标签（如：技术发布、商业动态、观点分享、其他）
    3. 忽略无实质内容的条目（如纯广告或无意义的短文）。
    4. 输出格式请使用 Markdown 列表或表格，保持清晰。

    待整理数据：
    {data_text}
    """

    response = client.chat.completions.create(
        model=config.get('llm', 'model'),
        messages=[
            {"role": "system", "content": "You are a helpful assistant for data organization."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return response.choices[0].message.content
