# pip3 install transformers
# python3 deepseek_tokenizer.py
# 
# DeepSeek V3 Tokenizer - 用于计算文本的token数量
import os
from transformers import PreTrainedTokenizerFast

# 获取当前脚本所在目录
tokenizer_dir = os.path.dirname(os.path.abspath(__file__))

# 使用 PreTrainedTokenizerFast 直接加载（无需 config.json）
tokenizer = PreTrainedTokenizerFast.from_pretrained(tokenizer_dir)


def count_tokens(text: str) -> int:
    """计算文本的token数量"""
    return len(tokenizer.encode(text))


if __name__ == "__main__":
    # 测试
    test_text = "Hello! 你好！这是一个测试文本。"
    tokens = tokenizer.encode(test_text)
    print(f"文本: {test_text}")
    print(f"Token IDs: {tokens}")
    print(f"Token 数量: {len(tokens)}")
