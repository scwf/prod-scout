import feedparser
import sys

# 真实的 RSSHub URL (假设本地运行在 1200 端口)
# 如果您使用了其他端口或由于网络原因无法访问，请替换此 URL
# TEST_URL = "http://127.0.0.1:1200/twitter/user/Kimi_Moonshot" 
# TEST_URL = "https://wechat2rss.xlab.app/feed/51e92aad2728acdd1fda7314be32b16639353001.xml"
TEST_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC3q8O3Bh2Le8Rj1-Q-_UUbA"

def test_feedparser_real_url():
    print(f"Fetching from: {TEST_URL} ...")
    
    # 尝试加载 feed
    # 注意：feedparser 可以直接接受 URL，但它内部处理网络错误比较隐晦
    # 为了更好的调试信息，通常建议先用 requests 获取内容
    try:
        import requests
        resp = requests.get(TEST_URL, timeout=10)
        resp.raise_for_status()
        raw_content = resp.content
        print(f"Successfully downloaded {len(raw_content)} bytes.")
    except Exception as e:
        print(f"Network error: {e}")
        print("Please enforce your local RSSHub server is running at port 1200.")
        return

    feed = feedparser.parse(raw_content)
    
    if not feed.entries:
        print("Warning: No entries found in the feed. (Maybe the account has no tweets?)")
        return

    print(f"\nAnalyzing top {min(10, len(feed.entries))} entries out of {len(feed.entries)} total...")
    
    for i, entry in enumerate(feed.entries[:10]):
        print("\n" + "-"*60)
        print(f" ENTRY #{i+1}: {entry.get('title', 'No Title')[:50]}...")
        print("-"*60)

        # 1. 检查 content 字段
        if hasattr(entry, "content"):
            content_obj = entry.content
            print(f"  [content] Found (List Length: {len(content_obj)})")
            
            # 遍历打印每个元素的详情
            for j, item in enumerate(content_obj):
                print(f"    - Item {j}: type='{item.get('type')}', keys={list(item.keys())}")
        else:
            print(f"  [content] NOT Found")

        # 2. 检查 description 字段
        desc = entry.get("description", "")
        print(f"  [description] Found (Length: {len(desc)})")
        print(f"     Preview: {desc[:100].replace('\n', ' ')}...")

if __name__ == "__main__":
    test_feedparser_real_url()
