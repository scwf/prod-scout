# x_scraper Code Review Fix Task List

> Based on review of commit `ffc6911`. Created 2026-02-13.
> Status: ✅ ALL COMPLETE

## Summary

6 issues identified from code review, all confirmed and fixed. 7 new unit tests added.

---

## Task 1: 🔴 Fix pagination early termination when all-retweet pages exist
- **File**: `x_scraper/client.py`
- **Problem**: `page_has_valid` was affected by both date filtering AND retweet filtering. A page of all retweets would trigger early termination.
- **Fix**: Separated `page_has_new_enough` (date-only, controls pagination) from business filters (retweets/replies, only controls result inclusion).
- [x] Code fix
- [x] Test: covered by existing integration tests

## Task 2: 🔴 Make retry-after header parsing robust
- **File**: `x_scraper/client.py`
- **Problem**: `int()` on non-integer retry-after would raise ValueError.
- **Fix**: Wrapped in try/except, fallback to 900s default with warning log.
- [x] Code fix
- [x] Test: `test_retry_after_non_integer`

## Task 3: 🟡 Detect GraphQL business errors in HTTP 200 responses
- **File**: `x_scraper/client.py`
- **Problem**: HTTP 200 + `{"errors": [...]}` silently returned empty results.
- **Fix**: Check for `errors` field when `data` is absent; raise `XClientError`. When both `errors` and `data` exist, return data (partial success).
- [x] Code fix
- [x] Test: `test_graphql_error_detected`, `test_graphql_error_with_partial_data_ok`

## Task 4: 🟡 Deduplicate pinned tweets in timeline parsing
- **File**: `x_scraper/parser.py`
- **Problem**: TimelinePinEntry and TimelineAddEntries could duplicate the same tweet.
- **Fix**: Track `seen_ids` set in `parse_timeline`, skip duplicates.
- [x] Code fix
- [x] Test: `test_pinned_tweet_dedup`

## Task 5: 🟢 Fix overly broad .env key matching
- **File**: `x_scraper/account_pool.py`
- **Problem**: `startswith("TWITTER_AUTH_TOKEN")` matched suffixed keys.
- **Fix**: Use `str.partition('=')` + exact key comparison. Also added `XCSRF_TOKEN` as alias for ct0.
- [x] Code fix
- [x] Test: `test_env_exact_key_match`, `test_env_xcsrf_token_fallback`

## Task 6: 🟢 Reduce credential exposure in logs
- **File**: `x_scraper/account_pool.py`
- **Problem**: First 8 chars of auth_token exposed in `get_status()`.
- **Fix**: Reduced to 4 chars + `****` mask.
- [x] Code fix
- [x] Test: `test_status_token_masked`
