"""Shared source loading helpers for scout pipelines."""


def load_sources(config):
    """Load configured source URLs using native_scout's behavior as the baseline."""

    def load_weixin():
        accounts = {}
        if config.has_section("weixin_accounts"):
            for name in config.options("weixin_accounts"):
                rss_url = config.get("weixin_accounts", name).strip()
                if rss_url:
                    accounts[name] = rss_url
        return accounts

    def load_x():
        accounts = {}
        rsshub_base = config.get("rsshub", "base_url", fallback="http://127.0.0.1:1200")
        if config.has_section("x_accounts"):
            for name in config.options("x_accounts"):
                account_id = config.get("x_accounts", name).strip()
                if account_id:
                    accounts[name] = f"{rsshub_base}/twitter/user/{account_id}"
        return accounts

    def load_youtube():
        accounts = {}
        if config.has_section("youtube_channels"):
            for name in config.options("youtube_channels"):
                channel_id = config.get("youtube_channels", name).strip()
                if channel_id:
                    accounts[name] = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        return accounts

    return {
        "weixin": load_weixin(),
        "X": load_x(),
        "YouTube": load_youtube(),
    }
