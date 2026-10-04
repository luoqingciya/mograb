# SPDX-License-Identifier: GPL-3.0-only
"""任务队列（规划书 §18）。

一个**异步优先级队列**，支持：

- 按 ``priority`` 排序（数值大者优先，FIFO 打破平局）
- 取消已入队但未开始的任务
- 优雅关闭（等待在途任务）

队列只负责「排队」，不负责执行 —— 执行在 :mod:`mograb.task.worker`。
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field

from ..domain.task import Task


@dataclass(order=True, slots=True)
class _QueueItem:
    """队列元素；排序键为 (-priority, seq)。"""

    sort_key: tuple[int, int]
    task: Task = field(compare=False)
    cancelled: bool = field(default=False, compare=False)


class TaskQueue:
    """异步优先级任务队列。"""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[_QueueItem] = asyncio.PriorityQueue()
        self._seq = itertools.count()
        self._cancelled: set[str] = set()

    async def put(self, task: Task) -> None:
        """入队。优先级越高越先出队。"""
        item = _QueueItem(sort_key=(-task.priority, next(self._seq)), task=task)
        await self._queue.put(item)

    async def get(self) -> Task:
        """出队；自动跳过已取消的任务。"""
        while True:
            item = await self._queue.get()
            if item.task.id in self._cancelled:
                self._cancelled.discard(item.task.id)
                self._queue.task_done()
                continue
            return item.task

    def task_done(self) -> None:
        """标记当前任务处理完毕。"""
        self._queue.task_done()

    def cancel(self, task_id: str) -> bool:
        """标记任务为已取消；返回是否成功标记。

        若任务已在执行中，取消信号由 :class:`TaskManager` 通过取消令牌传递。
        """
        self._cancelled.add(task_id)
        return True

    def __len__(self) -> int:
        return self._queue.qsize()

    @property
    def pending(self) -> int:
        """尚未处理的任务数（含未调用 task_done 的）。"""
        return self._queue.qsize()

    async def join(self) -> None:
        """等待所有任务处理完毕。"""
        await self._queue.join()


__all__ = ["TaskQueue"]
