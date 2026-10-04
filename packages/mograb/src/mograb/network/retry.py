# SPDX-License-Identifier: GPL-3.0-only
"""重试策略（规划书 §19）。

核心原则：**重试不是无限重试，且不同错误类型的可重试性不同。**

======================  ==========  ====================================
错误类型                 自动重试     说明
======================  ==========  ====================================
网络错误 / 超时           是          指数退避 + 抖动
5xx                     是          指数退避 + 抖动
429                     是          优先遵循 ``Retry-After``
解析错误 (ParseError)     否          站点结构变化，重试无意义
内容校验失败              否          需人工/规则修正
Schema 错误              否          立即失败
======================  ==========  ====================================

退避序列：``1s, 2s, 4s, 8s, ...``，上限由 ``max_delay`` 控制，叠加随机抖动
以避免多任务同时重试造成的惊群。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..errors import MoGrabError, RateLimitedError

# 默认可重试的错误码（与 errors.py 中的 retryable 标记互为补充）
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 60.0
DEFAULT_JITTER = 0.25


@dataclass(slots=True)
class RetryPolicy:
    """重试策略配置。"""

    max_retries: int = DEFAULT_MAX_RETRIES
    base_delay: float = DEFAULT_BASE_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    jitter: float = DEFAULT_JITTER
    """抖动比例，取值 [0, 1]；实际延迟 = delay * (1 ± jitter)。"""

    def delay_for(self, attempt: int, *, retry_after: float | None = None) -> float:
        """计算第 ``attempt`` 次重试（从 0 起）应等待的秒数。

        Args:
            attempt: 已失败次数（0 表示首次失败后）。
            retry_after: 服务端 ``Retry-After`` 指定的秒数，优先级最高。
        """
        if retry_after is not None:
            return min(retry_after, self.max_delay)

        delay = min(self.base_delay * (2**attempt), self.max_delay)
        if self.jitter > 0:
            spread = delay * self.jitter
            delay += random.uniform(-spread, spread)
        return max(0.0, delay)

    def should_retry(self, error: BaseException, attempt: int) -> bool:
        """判断是否应继续重试。

        Args:
            error: 捕获到的异常。
            attempt: 已重试次数（0 表示首次失败）。
        """
        if attempt >= self.max_retries:
            return False
        if isinstance(error, MoGrabError):
            return error.retryable
        # 非 MoGrabError（如 httpx 连接异常）交由调用方包装，默认不重试
        return False

    def retry_after_of(self, error: BaseException) -> float | None:
        """提取服务端建议的重试等待时间。"""
        if isinstance(error, RateLimitedError):
            return error.retry_after
        return None


__all__ = [
    "DEFAULT_BASE_DELAY",
    "DEFAULT_JITTER",
    "DEFAULT_MAX_DELAY",
    "DEFAULT_MAX_RETRIES",
    "RetryPolicy",
]
