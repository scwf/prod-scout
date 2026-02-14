
import unittest
import sys
import os
from unittest.mock import MagicMock, patch

# Add the project root to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'native_scout')))

from stages.content_enricher import EnricherStage
from queue import Queue

class TestEnricherFiltering(unittest.TestCase):
    def setUp(self):
        # Mock config
        self.config = MagicMock()
        self.config.getint.return_value = 1
        self.config.getboolean.return_value = False
        
        # Create queues
        self.fetch_queue = Queue()
        self.enrich_queue = Queue()
        
        # Create EnricherStage instance
        self.enricher = EnricherStage(self.fetch_queue, self.enrich_queue, self.config, "test_batch")
        
        # We need to ensure we don't actually try to use Selenium in this test environment
        # So we mock the underlying fetch call in BlogFetcher, but keep the logic structure intact.
        # This simulates a network call returning empty content, avoiding Selenium startup.
        # The key is that LinkExtractor (which runs before this) will still extract the URL.
        self.patcher = patch('utils.web_crawler.fetch_web_content', return_value=None)
        self.mock_fetch = self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_filter_spotify_and_apple_podcast_urls(self):
        # Define test URLs provided by the user
        spotify_url = "https://open.spotify.com/episode/0qR8WghMlv19sF08bQDClM?si=HS9Pr2XLTMusVXGyAbWhfw"
        apple_url = "https://podcasts.apple.com/us/podcast/episode-13-the-thinking-behind-ads-in-chatgpt/id1820330260?i=1000748954840"
        valid_url = "https://example.com/blog/article"
        
        # Construct content with these URLs
        content = f"""
        Here are some podcasts:
        {spotify_url}
        {apple_url}
        And a valid blog post:
        {valid_url}
        """
        
        # Create a post item
        post = {
            'source_type': 'X',
            'title': 'Test Post with Podcasts',
            'content': content,
            'source_name': 'test_user'
        }
        
        # Simulate processing the item
        # We are testing _process_item directly to avoid threading complexities in a unit test
        self.enricher._process_item(post)
        
        # Check results
        extra_urls = post.get('extra_urls', [])
        
        print(f"DEBUG: Extracted Extra URLs: {extra_urls}")
        
        # Assertions
        # The goal is that Spotify and Apple Podcast URLs should be filtered out
        self.assertNotIn(spotify_url, extra_urls, "Spotify URL should be filtered out")
        self.assertNotIn(apple_url, extra_urls, "Apple Podcast URL should be filtered out")
        
        # Valid URL should remain (unless fetch failed and extracted logic changes? 
        # ContentFetcher puts ALL extracted URLs in `all_urls` regardless of fetch success.
        # So valid_url should be present.)
        self.assertIn(valid_url, extra_urls, "Valid URL should be preserved")

if __name__ == '__main__':
    unittest.main()
