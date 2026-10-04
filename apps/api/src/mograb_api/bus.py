# SPDX-License-Identifier: GPL-3.0-only
"""进程内事件广播（规划书 §30）。

任务状态变更时推给所有 SSE 订阅者。单进程、单用户，用不上 Redis 那一套。

一条原则：**慢订阅者丢事件，不阻塞发布方**。一个卡住的浏览器标签页
不该拖慢正在跑的下载。队列满了就丢掉这条，订阅者下一次收到的是更新后的状态。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

MAX_QUEUE_SIZE = 256


class EventBus:
    """极简的进程内广播。"""

    def __init__(self, max_queue: int = MAX_QUEUE_SIZE) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._max_queue = max_queue

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """订阅事件。退出上下文时自动退订。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def publish(self, event: dict[str, Any]) -> None:
        """广播一条事件。"""
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 跟不上就丢，不阻塞发布方
                continue

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


__all__ = ["EventBus"]
