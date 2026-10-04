# SPDX-License-Identifier: GPL-3.0-only
"""按书源隔离的限流器（规划书 §15、§38）。

关键约束：**不能让多个来源共用一个全局限制器。**

因此本模块提供两级模型：

1. :class:`GlobalLimiter` —— 全局并发上限（保护本机资源）
2. :class:`SourceLimiter` —— 每个书源独立的并发上限 + 最小请求间隔

``SourceLimiterRegistry`` 按 ``source_id`` 维护 :class:`SourceLimiter` 实例，
保证「Source A 2 并发、Source B 5 并发」互不影响。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class SourceLimiter:
    """单个书源的限流器。

    - ``concurrency``：同时进行的请求数上限（信号量）
    - ``min_interval``：两次请求之间的最小间隔（秒），用于「礼貌抓取」

    使用方式::

        async with limiter.slot():
            ...  # 发起请求
    """

    concurrency: int = 2
    min_interval: float = 0.5

    _semaphore: asyncio.Semaphore = field(init=False, repr=False)
    _last_request_at: float = field(default=0.0, init=False, repr=False)
    _interval_lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._semaphore = asyncio.Semaphore(self.concurrency)
        self._interval_lock = asyncio.Lock()

    def slot(self) -> _LimiterSlot:
        """获取一个执行槽位（异步上下文管理器）。"""
        return _LimiterSlot(self)

    async def acquire(self) -> None:
        """等待并占用一个并发槽位，同时满足最小间隔。"""
        await self._semaphore.acquire()
        try:
            async with self._interval_lock:
                if self.min_interval > 0:
                    elapsed = time.monotonic() - self._last_request_at
                    wait = self.min_interval - elapsed
                    if wait > 0:
                        await asyncio.sleep(wait)
                self._last_request_at = time.monotonic()
        except BaseException:
            self._semaphore.release()
            raise

    def release(self) -> None:
        """释放并发槽位。"""
        self._semaphore.release()


class _LimiterSlot:
    """:meth:`SourceLimiter.slot` 返回的异步上下文管理器。"""

    __slots__ = ("_limiter",)

    def __init__(self, limiter: SourceLimiter) -> None:
        self._limiter = limiter

    async def __aenter__(self) -> SourceLimiter:
        await self._limiter.acquire()
        return self._limiter

    async def __aexit__(self, *exc_info: object) -> None:
        self._limiter.release()


class GlobalLimiter:
    """全局并发上限（跨所有书源）。"""

    def __init__(self, concurrency: int = 8) -> None:
        self.concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)

    def slot(self) -> _GlobalSlot:
        return _GlobalSlot(self._semaphore)


class _GlobalSlot:
    __slots__ = ("_sem",)

    def __init__(self, sem: asyncio.Semaphore) -> None:
        self._sem = sem

    async def __aenter__(self) -> None:
        await self._sem.acquire()

    async def __aexit__(self, *exc_info: object) -> None:
        self._sem.release()


class SourceLimiterRegistry:
    """按 ``source_id`` 维护独立限流器。

    ``default_concurrency`` / ``default_min_interval`` 是兜底值：调用方没给
    具体策略时用它们。书源自己声明了 ``network.concurrency`` 的话，首次取
    限流器时传进来即可，之后沿用。
    """

    def __init__(
        self,
        global_limiter: GlobalLimiter | None = None,
        *,
        default_concurrency: int = 2,
        default_min_interval: float = 0.5,
    ) -> None:
        self._limiters: dict[str, SourceLimiter] = {}
        self._global = global_limiter or GlobalLimiter()
        self._lock = asyncio.Lock()
        self._default_concurrency = default_concurrency
        self._default_min_interval = default_min_interval

    async def get(
        self,
        source_id: str,
        *,
        concurrency: int | None = None,
        min_interval: float | None = None,
    ) -> SourceLimiter:
        """取（或创建）指定书源的限流器。

        已存在就直接返回，**不会**用新参数覆盖 —— 同一个来源的限速策略
        在一轮运行里应该稳定，中途变来变去不好推理。
        """
        async with self._lock:
            limiter = self._limiters.get(source_id)
            if limiter is None:
                limiter = SourceLimiter(
                    concurrency=concurrency or self._default_concurrency,
                    min_interval=(
                        self._default_min_interval if min_interval is None else min_interval
                    ),
                )
                self._limiters[source_id] = limiter
            return limiter

    @property
    def global_limiter(self) -> GlobalLimiter:
        return self._global


__all__ = [
    "GlobalLimiter",
    "SourceLimiter",
    "SourceLimiterRegistry",
]
