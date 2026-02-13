"""
account_pool.py - X/Twitter 账号池管理

管理多个 auth_token + ct0 凭证组合，支持轮换和冷却机制。
"""
import time
import logging
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger("x_scraper.account_pool")


@dataclass
class AccountState:
    """单个账号的状态"""
    auth_token: str
    ct0: str
    index: int = 0

    # 运行状态
    request_count: int = 0           # 累计请求次数
    cooldown_until: float = 0.0      # 冷却到期时间 (epoch timestamp)
    is_dead: bool = False            # 是否已永久失效 (401/403)
    last_error: str = ""             # 最近一次错误信息

    @property
    def is_available(self) -> bool:
        """是否可用（未失效 且 未在冷却期内）"""
        if self.is_dead:
            return False
        if self.cooldown_until > time.time():
            return False
        return True

    @property
    def cooldown_remaining(self) -> float:
        """剩余冷却时间 (秒)"""
        remaining = self.cooldown_until - time.time()
        return max(0, remaining)


class AccountPool:
    """
    账号池管理器

    支持:
    - 多凭证轮换 (Round-Robin)
    - 自动跳过冷却中/已失效的账号
    - 按需标记限速/失效
    """

    # 默认冷却时间: 15 分钟
    DEFAULT_COOLDOWN_SECONDS = 900

    def __init__(self, credentials: List[Tuple[str, str]]):
        """
        初始化账号池。

        Args:
            credentials: [(auth_token, ct0), ...] 凭证列表
        """
        if not credentials:
            raise ValueError("至少需要提供一个 auth_token:ct0 凭证对")

        self.accounts: List[AccountState] = []
        for i, (auth_token, ct0) in enumerate(credentials):
            self.accounts.append(AccountState(
                auth_token=auth_token.strip(),
                ct0=ct0.strip(),
                index=i,
            ))

        self._current_index = 0
        logger.info(f"账号池初始化完成: {len(self.accounts)} 个凭证")

    @classmethod
    def from_config_string(cls, config_str: str) -> 'AccountPool':
        """
        从配置字符串解析创建账号池。

        格式: "auth_token1:ct01;auth_token2:ct02"
        分号分隔多个凭证，冒号分隔 auth_token 和 ct0。

        Args:
            config_str: 配置字符串

        Returns:
            AccountPool 实例
        """
        credentials = []
        for pair in config_str.split(";"):
            pair = pair.strip()
            if not pair:
                continue
            parts = pair.split(":", 1)
            if len(parts) != 2:
                logger.warning(f"跳过格式错误的凭证: {pair[:20]}...")
                continue
            credentials.append((parts[0], parts[1]))

        return cls(credentials)

    @classmethod
    def from_env_file(cls, env_file_path: str) -> 'AccountPool':
        """
        从 rsshub-docker.env 格式的文件加载凭证。

        支持:
            TWITTER_AUTH_TOKEN="xxx"
            TWITTER_CT0="yyy"

        Args:
            env_file_path: .env 文件路径

        Returns:
            AccountPool 实例
        """
        auth_token = ""
        ct0 = ""

        try:
            with open(env_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key == "TWITTER_AUTH_TOKEN":
                        auth_token = value
                    elif key in ("TWITTER_CT0", "XCSRF_TOKEN"):
                        ct0 = value
        except FileNotFoundError:
            raise FileNotFoundError(f"找不到环境文件: {env_file_path}")

        if not auth_token or not ct0:
            raise ValueError(f"环境文件中缺少 TWITTER_AUTH_TOKEN 或 TWITTER_CT0: {env_file_path}")

        return cls([(auth_token, ct0)])

    def get_next(self) -> Optional[AccountState]:
        """
        获取下一个可用账号 (Round-Robin 轮换)。

        跳过冷却中和已失效的账号。
        如果所有账号都不可用，返回 None。

        Returns:
            可用的 AccountState，或 None
        """
        total = len(self.accounts)
        for _ in range(total):
            account = self.accounts[self._current_index]
            self._current_index = (self._current_index + 1) % total

            if account.is_available:
                account.request_count += 1
                return account

        # 所有账号都不可用
        return None

    def mark_rate_limited(self, account: AccountState, cooldown_seconds: int = None):
        """
        标记账号被限速，进入冷却期。

        Args:
            account: 被限速的账号
            cooldown_seconds: 冷却时间（秒），默认 15 分钟
        """
        if cooldown_seconds is None:
            cooldown_seconds = self.DEFAULT_COOLDOWN_SECONDS

        account.cooldown_until = time.time() + cooldown_seconds
        account.last_error = f"Rate limited, cooldown {cooldown_seconds}s"
        logger.warning(
            f"账号 #{account.index} 被限速，冷却 {cooldown_seconds}s "
            f"(已请求 {account.request_count} 次)"
        )

    def mark_dead(self, account: AccountState, reason: str = ""):
        """
        标记账号永久失效 (如 Token 过期、被封)。

        Args:
            account: 失效的账号
            reason: 失效原因
        """
        account.is_dead = True
        account.last_error = reason or "Account marked as dead"
        logger.error(f"账号 #{account.index} 已失效: {reason}")

    @property
    def available_count(self) -> int:
        """当前可用账号数量"""
        return sum(1 for a in self.accounts if a.is_available)

    @property
    def total_count(self) -> int:
        """总账号数量"""
        return len(self.accounts)

    def get_status(self) -> List[Dict[str, Any]]:
        """获取所有账号的状态摘要 (用于日志/调试)"""
        result = []
        for a in self.accounts:
            status = "available" if a.is_available else ("dead" if a.is_dead else "cooling")
            result.append({
                "index": a.index,
                "status": status,
                "request_count": a.request_count,
                "cooldown_remaining": round(a.cooldown_remaining, 1),
                "auth_token_hint": a.auth_token[:4] + "****",
            })
        return result

    def wait_for_available(self, timeout: float = 1800) -> Optional[AccountState]:
        """
        等待直到有可用账号，或超时。

        如果所有账号都在冷却中，会等待最快解锁的那个。
        如果所有账号都已永久失效，立即返回 None。

        Args:
            timeout: 最大等待时间 (秒)，默认 30 分钟

        Returns:
            可用的 AccountState，或 None (超时/全部失效)
        """
        deadline = time.time() + timeout

        while time.time() < deadline:
            # 尝试获取
            account = self.get_next()
            if account is not None:
                return account

            # 检查是否全部永久失效
            if all(a.is_dead for a in self.accounts):
                logger.error("所有账号已永久失效，无法继续")
                return None

            # 等待最快的冷却结束
            min_wait = min(
                (a.cooldown_remaining for a in self.accounts if not a.is_dead and a.cooldown_remaining > 0),
                default=1.0
            )
            wait_time = min(min_wait + 1, deadline - time.time(), 60)
            if wait_time <= 0:
                break

            logger.info(f"所有账号冷却中，等待 {wait_time:.0f}s...")
            time.sleep(wait_time)

        logger.error(f"等待可用账号超时 ({timeout}s)")
        return None
