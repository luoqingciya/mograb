# SPDX-License-Identifier: GPL-3.0-only
"""TaskManager —— 任务生命周期管理（规划书 §17、§18、§39）。

职责：

- 创建任务（分配 ID、写入 PENDING）
- 入队 / 暂停 / 继续 / 取消 / 重试
- 启动与停止 WorkerPool
- **孤儿任务恢复**：进程异常退出后，库中残留的 RUNNING / RETRYING 任务
  在启动时被标记为 FAILED（``error_code=INTERRUPTED``），
  由用户显式重试，避免「假装还在跑」。

规划书未定义恢复策略，此处补齐（对应评估报告 P1-06）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from ..domain.enums import TaskStatus, TaskType
from ..domain.task import Task
from ..errors import InvalidTaskTransitionError, TaskNotFoundError
from ..logging.setup import get_logger
from .queue import TaskQueue
from .worker import TaskHandler, WorkerPool

_logger = get_logger(__name__)


@runtime_checkable
class TaskRepository(Protocol):
    """任务仓储契约（由 Storage 层实现）。"""

    async def get(self, task_id: str) -> Task | None: ...

    async def save(self, task: Task) -> None: ...

    async def list_all(self, *, status: TaskStatus | None = ...) -> list[Task]: ...

    async def list_by_status(self, status: TaskStatus) -> list[Task]: ...


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"task_{uuid.uuid4().hex[:16]}"


class TaskManager:
    """任务管理器。"""

    def __init__(
        self,
        repository: TaskRepository,
        handlers: dict[str, TaskHandler],
        *,
        worker_count: int = 4,
    ) -> None:
        self._repo = repository
        self._handlers = handlers
        self._queue = TaskQueue()
        self._pool = WorkerPool(
            self._queue, handlers, size=worker_count, on_status_change=self._persist
        )
        self._running = False

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """启动管理器并恢复孤儿任务。"""
        if self._running:
            return
        await self._recover_orphans()
        await self._pool.start()
        self._running = True
        _logger.info("task.manager_started", workers=self._pool.size)

    async def stop(self, *, graceful: bool = True) -> None:
        """停止管理器。"""
        if not self._running:
            return
        await self._pool.stop(graceful=graceful)
        self._running = False
        _logger.info("task.manager_stopped")

    # ------------------------------------------------------------------
    # 创建与控制
    # ------------------------------------------------------------------
    async def create(
        self,
        task_type: TaskType,
        *,
        book_id: str | None = None,
        source_id: str | None = None,
        priority: int = 0,
        total: int = 0,
        max_retries: int = 3,
        params: dict[str, Any] | None = None,
        enqueue: bool = True,
    ) -> Task:
        """创建任务（可选立即入队）。"""
        task = Task(
            id=_new_id(),
            type=task_type,
            book_id=book_id,
            source_id=source_id,
            priority=priority,
            total=total,
            max_retries=max_retries,
            params=dict(params or {}),
            created_at=_now(),
        )
        await self._repo.save(task)
        if enqueue:
            await self._queue.put(task)
        return task

    async def get(self, task_id: str) -> Task:
        """查询任务；不存在抛 :class:`TaskNotFoundError`。"""
        task = await self._repo.get(task_id)
        if task is None:
            raise TaskNotFoundError(f"任务不存在: {task_id}", details={"task_id": task_id})
        return task

    async def list(self, *, status: TaskStatus | None = None) -> list[Task]:
        """列出任务。"""
        if status is None:
            return await self._repo.list_all()
        return await self._repo.list_by_status(status)

    async def pause(self, task_id: str) -> Task:
        """暂停任务。"""
        task = await self.get(task_id)
        task.transition_to(TaskStatus.PAUSED)
        self._pool.cancel_task(task_id)
        await self._persist(task)
        return task

    async def resume(self, task_id: str) -> Task:
        """继续任务（重置为 PENDING 后重新入队）。"""
        task = await self.get(task_id)
        if task.status is not TaskStatus.PAUSED:
            raise InvalidTaskTransitionError(
                f"只有 PAUSED 任务可继续，当前为 {task.status.value}",
                details={"task_id": task_id, "status": task.status.value},
            )
        task.transition_to(TaskStatus.PENDING)
        await self._persist(task)
        await self._queue.put(task)
        return task

    async def cancel(self, task_id: str) -> Task:
        """取消任务。"""
        task = await self.get(task_id)
        self._pool.cancel_task(task_id)
        self._queue.cancel(task_id)
        if not task.is_terminal:
            task.transition_to(TaskStatus.CANCELLED)
            task.finished_at = _now()
        await self._persist(task)
        return task

    async def retry(self, task_id: str) -> Task:
        """重试失败的任务（重置为 PENDING 后重新入队）。"""
        task = await self.get(task_id)
        if task.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
            raise InvalidTaskTransitionError(
                f"只有 FAILED/CANCELLED 任务可重试，当前为 {task.status.value}",
                details={"task_id": task_id, "status": task.status.value},
            )
        # 终态不可直接转出，创建新任务承载重试
        return await self.create(
            task.type,
            book_id=task.book_id,
            source_id=task.source_id,
            priority=task.priority,
            total=task.total,
            max_retries=task.max_retries,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _persist(self, task: Task) -> None:
        """持久化任务状态。"""
        await self._repo.save(task)

    async def _recover_orphans(self) -> None:
        """恢复进程崩溃遗留的在途任务。"""
        for status in (TaskStatus.RUNNING, TaskStatus.RETRYING):
            for task in await self._repo.list_by_status(status):
                task.status = TaskStatus.FAILED  # 直接置位，绕过状态机（恢复场景）
                task.error_code = "INTERRUPTED"
                task.error_message = "进程在任务执行期间退出，任务已中断"
                task.finished_at = _now()
                await self._repo.save(task)
                _logger.warning("task.orphan_recovered", task_id=task.id, was=status.value)

    async def join(self) -> None:
        """等待队列中所有任务处理完毕。"""
        await self._queue.join()


__all__ = ["TaskManager", "TaskRepository"]
