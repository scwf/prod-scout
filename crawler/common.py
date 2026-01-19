"""
common.py - 公共配置和工具函数
"""
import os
import configparser
from openai import OpenAI

# 时间范围配置,爬取最近多少天的内容
DAYS_LOOKBACK = 2

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
    1. 输出为 Markdown 表格的一行（不需要表头）
    2. 列顺序：日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类
    3. 各列说明：
       - **日期**: {post['date']}
       - **事件**: 简练概括发生了什么（标题/核心动作）
       - **关键信息**: 提取 1-3 点核心细节，用 <br> 分隔
       - **原文链接**: [原文链接]({post['link']})
       - **详细内容**: 若原文是X的推文，则保留原始推文内容；若原文不长且可读性良好也直接输出原文；其他情况则对原始内容进行格式优化（比如去掉HTML标签），结构化整理输出为一段对原文的详细描述。
       - **分类**: 给该事件打一个标签（如：技术发布、商业动态、观点分享、活动、其他）
    4. 如果是纯广告或无实质内容，返回空字符串。
    5. 只输出表格行，不要输出其他内容。

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
    table_header = "| 日期 | 事件 | 关键信息 | 原文链接 | 详细内容 | 分类 |\n| :--- | :--- | :--- | :--- | :--- | :--- |"
    
    # 逐篇处理
    rows = []
    for idx, post in enumerate(posts):
        print(f"    正在整理{source_name} 第 {idx+1}/{len(posts)} 篇: {post['title'][:30]}...")
        try:
            row = organize_single_post(post, source_name)
            if row and row.startswith('|'):
                rows.append(row)
        except Exception as e:
            print(f"    整理失败: {e}")
            continue
    
    if not rows:
        return f"【{source_name}】最近 {DAYS_LOOKBACK} 天的内容均无实质信息。"
    
    # 组合表格
    return table_header + "\n" + "\n".join(rows)
