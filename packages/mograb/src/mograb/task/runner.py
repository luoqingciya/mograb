# SPDX-License-Identifier: GPL-3.0-only
"""单个任务的执行与状态维护。

这段逻辑原本长在 :class:`~mograb.task.worker.WorkerPool` 里，但 CLI 也需要它 ——
``mog download`` 是就地跑完就退出的，没必要为了跑一个任务把 worker 池拉起来。

所以抽成 :class:`TaskRunner`：谁执行任务都走它，状态机、错误归类、取消检查
只有一份实现。WorkerPool 变成「从队列取任务、交给 TaskRunner」的薄壳。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..domain.enums import TaskStatus
from ..domain.task import Task
from ..errors import MoGrabError, TaskCancelledError
from ..logging.setup import get_logger

_logger = get_logger(__name__)

TaskHandler = Callable[[Task], Awaitable[None]]
"""任务处理函数。约定：只干活，不碰 ``task.status`` —— 状态由 TaskRunner 管。"""

StatusCallback = Callable[[Task], Awaitable[None]]


class TaskRunner:
    """执行任务并维护它的状态。"""

    def __init__(
        self,
        handlers: dict[str, TaskHandler],
        *,
        on_status_change: StatusCallback | None = None,
    ) -> None:
        self._handlers = handlers
        self._on_status_change = on_status_change
        self._cancelled: set[str] = set()

    # ------------------------------------------------------------------
    def cancel(self, task_id: str) -> None:
        """请求取消。正在跑的任务会在下一次检查点退出。"""
        self._cancelled.add(task_id)

    def is_cancelled(self, task_id: str) -> bool:
        return task_id in self._cancelled

    # ------------------------------------------------------------------
    async def run(self, task: Task) -> Task:
        """执行任务，返回状态已更新的同一个对象。

        不会抛异常 —— 失败信息落在 ``task.error_code`` / ``error_message`` 上。
        调用方需要区分成败时看 ``task.status``。
        """
        # 先进入 RUNNING。状态机不允许 PENDING 直接跳到终态，
        # 所以「没有 handler」这类失败也必须发生在 RUNNING 之后。
        task.transition_to(TaskStatus.RUNNING)
        await self._notify(task)

        handler = self._handlers.get(task.type.value)
        if handler is None:
            _logger.error("task.no_handler", task_id=task.id, task_type=task.type.value)
            task.error_code = "NO_HANDLER"
            task.error_message = f"没有注册处理 {task.type.value} 的 handler"
            task.transition_to(TaskStatus.FAILED)
            await self._notify(task)
            return task

        try:
            if self.is_cancelled(task.id):
                raise TaskCancelledError(f"任务 {task.id} 已取消")
            await handler(task)
            task.transition_to(TaskStatus.SUCCESS)
        except TaskCancelledError as exc:
            task.error_code = exc.code
            task.error_message = exc.message
            task.transition_to(TaskStatus.CANCELLED)
        except Exception as exc:
            if isinstance(exc, MoGrabError):
                task.error_code = exc.code
                task.error_message = exc.message
            else:
                task.error_code = "UNEXPECTED"
                task.error_message = str(exc)
            task.transition_to(TaskStatus.FAILED)
            _logger.error("task.failed", task_id=task.id, error=str(exc))
        finally:
            self._cancelled.discard(task.id)
            await self._notify(task)

        return task

    async def _notify(self, task: Task) -> None:
        if self._on_status_change is not None:
            await self._on_status_change(task)


__all__ = ["StatusCallback", "TaskHandler", "TaskRunner"]
