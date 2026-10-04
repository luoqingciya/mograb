# SPDX-License-Identifier: GPL-3.0-only
"""Worker 池（规划书 §18、§38）。

池子本身很薄：从队列取任务，交给 :class:`~mograb.task.runner.TaskRunner` 执行。
任务的状态机、错误归类、取消检查都在 TaskRunner 里 —— CLI 就地跑任务时
走的是同一份，不会出现「CLI 和后台任务对失败的处理不一样」。

并发度不由 worker 数量单独决定：真正的下载并发受 ``SourceLimiter``（按书源）
与 ``GlobalLimiter``（全局）双重约束。所以 worker 数量应该 ≥ 期望的最大并发，
实际并发由限流器收敛。

每个 worker 独立捕获异常，单个任务失败不影响其他任务。
"""

from __future__ import annotations

import asyncio

from ..logging.setup import bind_context, clear_context, get_logger
from .queue import TaskQueue
from .runner import StatusCallback, TaskHandler, TaskRunner

_logger = get_logger(__name__)


class WorkerPool:
    """固定大小的 worker 协程池。"""

    def __init__(
        self,
        queue: TaskQueue,
        handlers: dict[str, TaskHandler],
        *,
        size: int = 4,
        on_status_change: StatusCallback | None = None,
    ) -> None:
        self._queue = queue
        self._size = size
        self._runner = TaskRunner(handlers, on_status_change=on_status_change)
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = False

    async def start(self) -> None:
        """启动全部 worker。"""
        self._stopping = False
        self._workers = [
            asyncio.create_task(self._run(i), name=f"mograb-worker-{i}") for i in range(self._size)
        ]

    async def stop(self, *, graceful: bool = True) -> None:
        """停止 worker。

        Args:
            graceful: True 时等待在途任务完成；False 时立即取消。
        """
        self._stopping = True
        for worker in self._workers:
            worker.cancel()
        if graceful:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def cancel_task(self, task_id: str) -> None:
        """请求取消某个任务。"""
        self._runner.cancel(task_id)

    def is_cancelled(self, task_id: str) -> bool:
        return self._runner.is_cancelled(task_id)

    @property
    def size(self) -> int:
        """worker 数量。"""
        return self._size

    # ------------------------------------------------------------------
    async def _run(self, worker_id: int) -> None:
        """单个 worker 的主循环。"""
        while not self._stopping:
            task = await self._queue.get()
            bind_context(task_id=task.id, source_id=task.source_id or "-")
            try:
                await self._runner.run(task)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception as exc:
                _logger.error(
                    "worker.task_failed", worker=worker_id, task_id=task.id, error=str(exc)
                )
            finally:
                self._queue.task_done()
                clear_context()


__all__ = ["TaskHandler", "WorkerPool"]
