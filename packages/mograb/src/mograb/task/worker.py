# SPDX-License-Identifier: GPL-3.0-only
"""Worker 池（规划书 §18、§38）。

设计要点：

- ``WorkerPool`` 启动固定数量的 worker 协程，从 :class:`TaskQueue` 取任务。
- **并发度不由 worker 数量单独决定**：真正的下载并发受
  ``SourceLimiter``（按书源）与 ``GlobalLimiter``（全局）双重约束。
  因此 worker 数量应 ≥ 最大期望并发，实际并发由限流器收敛。
- 每个 worker 独立捕获异常，单个任务失败不影响其他任务。
- 支持优雅停机：``stop(graceful=True)`` 会等待在途任务完成。

任务到处理函数的映射通过 ``handlers`` 注入，避免 Worker 直接依赖具体实现。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..domain.enums import TaskStatus
from ..domain.task import Task
from ..errors import TaskCancelledError
from ..logging.setup import bind_context, clear_context, get_logger
from .queue import TaskQueue

_logger = get_logger(__name__)

TaskHandler = Callable[[Task], Awaitable[None]]
"""任务处理函数签名。"""


class WorkerPool:
    """固定大小的 worker 协程池。"""

    def __init__(
        self,
        queue: TaskQueue,
        handlers: dict[str, TaskHandler],
        *,
        size: int = 4,
        on_status_change: Callable[[Task], Awaitable[None]] | None = None,
    ) -> None:
        self._queue = queue
        self._handlers = handlers
        self._size = size
        self._on_status_change = on_status_change
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = False
        self._cancelled: set[str] = set()

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
        """请求取消某个任务（由正在执行的 handler 检查）。"""
        self._cancelled.add(task_id)

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

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
                await self._handle(task)
            except asyncio.CancelledError:
                self._queue.task_done()
                raise
            except Exception as exc:
                _logger.error(
                    "worker.task_failed",
                    worker=worker_id,
                    task_id=task.id,
                    error=str(exc),
                )
            finally:
                self._queue.task_done()
                clear_context()

    async def _handle(self, task: Task) -> None:
        """执行单个任务。"""
        handler = self._handlers.get(task.type.value)
        if handler is None:
            _logger.error("worker.no_handler", task_type=task.type.value)
            task.transition_to(TaskStatus.FAILED)
            task.error_code = "NO_HANDLER"
            await self._notify(task)
            return

        task.transition_to(TaskStatus.RUNNING)
        await self._notify(task)

        try:
            if self.is_cancelled(task.id):
                raise TaskCancelledError(f"任务 {task.id} 已取消")
            await handler(task)
            task.transition_to(TaskStatus.SUCCESS)
        except TaskCancelledError as exc:
            task.error_code = exc.code
            task.transition_to(TaskStatus.CANCELLED)
        except Exception as exc:
            from ..errors import MoGrabError

            if isinstance(exc, MoGrabError):
                task.error_code = exc.code
                task.error_message = exc.message
            else:
                task.error_code = "UNEXPECTED"
                task.error_message = str(exc)
            task.transition_to(TaskStatus.FAILED)
            _logger.error("worker.task_error", task_id=task.id, error=str(exc))
        finally:
            self._cancelled.discard(task.id)
            await self._notify(task)

    async def _notify(self, task: Task) -> None:
        if self._on_status_change is not None:
            await self._on_status_change(task)


__all__ = ["TaskHandler", "WorkerPool"]
