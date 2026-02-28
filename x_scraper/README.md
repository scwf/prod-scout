# X Scraper - Direct X/Twitter Tweet Fetcher

`x_scraper` is a standalone module that fetches tweets directly from X (Twitter) using its internal GraphQL API, **bypassing the need for RSSHub**. It provides richer data (engagement metrics, media, threads) and more reliable fetching through cookie-based authentication and TLS fingerprint impersonation.

## ✨ Features

- **Direct GraphQL API Access**: Talks to X's internal API endpoints directly — no RSSHub or third-party proxies needed.
- **TLS Fingerprint Impersonation**: Uses `curl_cffi` to mimic Chrome's TLS fingerprint (JA3), greatly reducing the risk of detection.
- **Multi-Account Rotation**: Supports rotating multiple `auth_token:ct0` credential pairs with automatic cooldown when rate-limited.
- **Rich Data Extraction**: Captures full tweet text (including long-form notes), engagement metrics (likes, retweets, views, bookmarks), media (photos, videos, GIFs), quoted tweets, and threads.
- **Thread Preservation**: Correctly identifies and preserves self-reply threads instead of filtering them out as regular replies.
- **Pipeline-Compatible Output**: Converts tweets to `post_dict` format, fully compatible with the existing `native_scout` pipeline stages (Enricher → Organizer → Writer).
- **Standalone CLI**: Can be run independently to fetch and save tweets as JSON files.

## 📁 Module Structure

```
x_scraper/
├── __init__.py         # Module entry point, public API exports
├── client.py           # GraphQL API HTTP client (core request logic)
├── models.py           # Tweet & TweetMedia data models
├── parser.py           # GraphQL JSON response parser
├── account_pool.py     # Multi-credential rotation & cooldown manager
├── scraper.py          # High-level orchestrator & CLI entry point
├── DESIGN.md           # Architecture & design documentation (Chinese)
└── README.md           # This file
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
uv pip install curl_cffi
```

> `curl_cffi` is the only additional dependency. If not installed, the module falls back to standard `requests` (but without TLS fingerprint impersonation, which may trigger X's bot detection).

### 2. Configure Credentials

The module needs a valid X session cookie (`auth_token` + `ct0`). There are two ways to provide them:

#### Option A: Use existing `rsshub-docker.env` (default)

If you already have a `rsshub-docker.env` file in the project root (from the RSSHub setup), the module will automatically read it:

```env
TWITTER_AUTH_TOKEN="your_auth_token_here"
TWITTER_CT0="your_ct0_here"
```

#### Option B: Configure in `config.ini` (supports multiple accounts)

Add to `config.ini`:

```ini
[x_scraper]
enabled = true
# Multiple credential pairs separated by | (avoid ; as it's a comment in INI)
auth_credentials = auth_token_1:ct0_1|auth_token_2:ct0_2
```

> 💡 **How to get `auth_token` and `ct0`**: Log into [x.com](https://x.com) in your browser, open DevTools → Application → Cookies → `https://x.com`, and copy the values of `auth_token` and `ct0`.

### 3. Use as Python Module

```python
from x_scraper import XScraper, AccountPool

# Method 1: From config.ini
import configparser
config = configparser.ConfigParser()
config.optionxform = str
config.read("config.ini", encoding="utf-8")
scraper = XScraper.from_config(config)

# Method 2: Manual setup
pool = AccountPool.from_env_file("rsshub-docker.env")
scraper = XScraper(account_pool=pool)

# Fetch tweets
tweets = scraper.fetch_user_tweets("karpathy", limit=20, days_lookback=7)
for tweet in tweets:
    print(f"[{tweet.date_str}] @{tweet.username}: {tweet.text[:80]}")
    print(f"  ❤️ {tweet.like_count}  🔄 {tweet.retweet_count}  👁️ {tweet.view_count}")

# Get Pipeline-compatible output
posts = scraper.fetch_user_tweets_as_posts("OpenAI", source_name="X_OpenAI", limit=10)
# posts is a list of dicts ready for native_scout pipeline
```

### 4. Use as Standalone CLI

```bash
python -m x_scraper.scraper
```

This reads `config.ini` for `[x_accounts]` and `[x_scraper]` settings, fetches all configured users, and saves results as JSON files to `data/x_scraper_{timestamp}/`.

## ⚙️ Configuration Reference

All options go under the `[x_scraper]` section in `config.ini`:

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable x_scraper to replace RSSHub for X fetching |
| `auth_credentials` | *(empty)* | Credential pairs (`token:ct0|token2:ct0_2`). Falls back to `rsshub-docker.env` if empty |
| `max_tweets_per_user` | `20` | Maximum tweets to fetch per user |
| `request_delay_min` | `15` | Minimum delay between API requests (seconds) |
| `request_delay_max` | `25` | Maximum delay between API requests (seconds) |
| `user_switch_delay_min` | `30` | Minimum delay when switching between users (seconds) |
| `user_switch_delay_max` | `60` | Maximum delay when switching between users (seconds) |
| `request_timeout` | `30` | HTTP request timeout (seconds) |
| `max_retries` | `3` | Maximum retry attempts per request |
| `include_retweets` | `false` | Include retweets in results |
| `include_replies` | `false` | Include replies to other users (self-reply threads are always kept) |
| `circuit_breaker_threshold` | `5` | Consecutive failures before pausing requests |
| `circuit_breaker_cooldown` | `60` | Circuit breaker pause duration (seconds) |
| `query_ids` | *(empty)* | Custom GraphQL Query IDs (JSON) |
| `features` | *(empty)* | Custom GraphQL Features (JSON) |

## 🔗 Pipeline Integration

When `x_scraper.enabled = true` in `config.ini`, the `FetcherStage` in `native_scout` will use `x_scraper` instead of RSSHub for X accounts. The integration is seamless:

```
[x_scraper]                    [native_scout Pipeline]
                               
 XScraper.fetch_user_tweets    
        │                      
        ▼                      
 Tweet.to_post_dict()  ──────► fetch_queue ──► EnricherStage
                                                    │
                               (extracts embedded   ▼
                                links & videos)  OrganizerStage
                                                    │
                                                    ▼
                                               WriterStage
```

The `post_dict` output format is identical to what `source_fetcher.py` produces via RSSHub, so all downstream stages (Enricher, Organizer, Writer) work without any changes.

## 🧪 Testing

```bash
# Run unit tests only (no network required, fast)
python -m pytest tests/test_x_scraper.py -v

# Run all tests including end-to-end integration tests
# (requires valid credentials in rsshub-docker.env + network)
python -m pytest tests/test_x_scraper.py -v --run-integration

# Run a specific test
python -m pytest tests/test_x_scraper.py -v --run-integration -k "test_e2e_get_user_id"

# Show print() output during tests
python -m pytest tests/test_x_scraper.py -v --run-integration -s
```

Test coverage:
- **49 unit tests**: Models, parser, account pool, client logic (all mocked, no network)
- **5 integration tests**: End-to-end API calls against real X endpoints

## ⚠️ Risks & Considerations

1. **Unofficial API**: X's internal GraphQL API is undocumented and may change without notice. If requests start failing with HTTP 400 ("features cannot be null"), update the `DEFAULT_FEATURES` dict in `client.py` with the missing feature flags.

2. **Account Safety**: Excessive request rates can trigger rate limits (HTTP 429) or permanent account suspension. Always use conservative delays and multiple accounts for rotation.

3. **Query ID Updates**: The `QUERY_IDS` in `client.py` may need updating when X deploys frontend changes. Extract fresh IDs from browser DevTools (Network tab → filter `graphql`).

4. **Legal Compliance**: Ensure your usage complies with X's Terms of Service and applicable data protection laws.
