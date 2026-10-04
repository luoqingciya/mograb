# SPDX-License-Identifier: GPL-3.0-only
"""任务引擎测试：优先级队列、Worker 池、生命周期管理。

TaskManager 的持久化用一个内存仓储替身，不依赖 SQLite。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from mograb.domain.enums import TaskItemStatus, TaskStatus, TaskType
from mograb.domain.task import Task, TaskItem
from mograb.errors import InvalidTaskTransitionError, TaskCancelledError, TaskNotFoundError
from mograb.task.manager import TaskManager
from mograb.task.queue import TaskQueue
from mograb.task.worker import WorkerPool

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def make_task(task_id: str = "task_1", **overrides) -> Task:
    data = {
        "id": task_id,
        "type": TaskType.DOWNLOAD_BOOK,
        "status": TaskStatus.PENDING,
        "created_at": NOW,
    }
    data.update(overrides)
    return Task(**data)


class InMemoryTaskRepository:
    """TaskRepository 协议的内存实现，供测试使用。"""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.items: dict[str, TaskItem] = {}

    async def get(self, task_id: str) -> Task | None:
        task = self.tasks.get(task_id)
        return task.model_copy(deep=True) if task else None

    async def save(self, task: Task) -> None:
        # 深拷贝，模拟真实持久化不会与调用方共享对象
        self.tasks[task.id] = task.model_copy(deep=True)

    async def list_all(self, *, status: TaskStatus | None = None) -> list[Task]:
        values = list(self.tasks.values())
        if status is not None:
            values = [t for t in values if t.status is status]
        return [t.model_copy(deep=True) for t in values]

    async def list_by_status(self, status: TaskStatus) -> list[Task]:
        return await self.list_all(status=status)

    async def list_items(self, task_id: str) -> list[TaskItem]:
        return [i for i in self.items.values() if i.task_id == task_id]

    async def save_item(self, item: TaskItem) -> None:
        self.items[item.id] = item


# ---------------------------------------------------------------------------
# 队列
# ---------------------------------------------------------------------------
class TestTaskQueue:
    async def test_fifo_for_equal_priority(self) -> None:
        queue = TaskQueue()
        for i in range(3):
            await queue.put(make_task(f"t{i}"))
        order = [(await queue.get()).id for _ in range(3)]
        assert order == ["t0", "t1", "t2"]

    async def test_higher_priority_first(self) -> None:
        queue = TaskQueue()
        await queue.put(make_task("low", priority=0))
        await queue.put(make_task("high", priority=90))
        await queue.put(make_task("mid", priority=50))
        order = [(await queue.get()).id for _ in range(3)]
        assert order == ["high", "mid", "low"]

    async def test_cancel_skips_task(self) -> None:
        queue = TaskQueue()
        await queue.put(make_task("a"))
        await queue.put(make_task("b"))
        queue.cancel("a")
        assert (await queue.get()).id == "b"

    async def test_len_and_pending(self) -> None:
        queue = TaskQueue()
        assert len(queue) == 0
        await queue.put(make_task())
        assert len(queue) == 1

    async def test_join_waits_for_task_done(self) -> None:
        queue = TaskQueue()
        await queue.put(make_task())
        await queue.get()

        async def finish() -> None:
            await asyncio.sleep(0.01)
            queue.task_done()

        pending = asyncio.create_task(finish())
        await asyncio.wait_for(queue.join(), timeout=1.0)
        await pending


# ---------------------------------------------------------------------------
# Worker 池
# ---------------------------------------------------------------------------
class TestWorkerPool:
    async def test_runs_handler_and_marks_success(self) -> None:
        queue = TaskQueue()
        seen: list[str] = []

        async def handler(task: Task) -> None:
            seen.append(task.id)

        pool = WorkerPool(queue, {"download_book": handler}, size=1)
        await pool.start()
        try:
            await queue.put(make_task())
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert seen == ["task_1"]

    async def test_missing_handler_marks_failed(self) -> None:
        queue = TaskQueue()
        notified: list[Task] = []

        async def on_change(task: Task) -> None:
            notified.append(task.model_copy())

        pool = WorkerPool(queue, {}, size=1, on_status_change=on_change)
        await pool.start()
        try:
            await queue.put(make_task())
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert notified[-1].status is TaskStatus.FAILED
        assert notified[-1].error_code == "NO_HANDLER"

    async def test_handler_error_marks_failed(self) -> None:
        queue = TaskQueue()
        notified: list[Task] = []

        async def handler(task: Task) -> None:
            raise RuntimeError("炸了")

        async def on_change(task: Task) -> None:
            notified.append(task.model_copy())

        pool = WorkerPool(queue, {"download_book": handler}, size=1, on_status_change=on_change)
        await pool.start()
        try:
            await queue.put(make_task())
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert notified[-1].status is TaskStatus.FAILED
        assert notified[-1].error_code == "UNEXPECTED"

    async def test_mograb_error_code_is_preserved(self) -> None:
        queue = TaskQueue()
        notified: list[Task] = []

        async def handler(task: Task) -> None:
            raise TaskCancelledError("取消")

        async def on_change(task: Task) -> None:
            notified.append(task.model_copy())

        pool = WorkerPool(queue, {"download_book": handler}, size=1, on_status_change=on_change)
        await pool.start()
        try:
            await queue.put(make_task())
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert notified[-1].status is TaskStatus.CANCELLED
        assert notified[-1].error_code == "TASK_CANCELLED"

    async def test_one_failure_does_not_stop_pool(self) -> None:
        """单个任务失败不能拖垮 worker —— 后续任务仍要执行。"""
        queue = TaskQueue()
        done: list[str] = []

        async def handler(task: Task) -> None:
            if task.id == "bad":
                raise RuntimeError("boom")
            done.append(task.id)

        pool = WorkerPool(queue, {"download_book": handler}, size=1)
        await pool.start()
        try:
            await queue.put(make_task("bad"))
            await queue.put(make_task("good"))
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert done == ["good"]

    async def test_cancel_task_flag(self) -> None:
        queue = TaskQueue()
        notified: list[Task] = []

        async def handler(task: Task) -> None:
            await asyncio.sleep(0.05)

        async def on_change(task: Task) -> None:
            notified.append(task.model_copy())

        pool = WorkerPool(queue, {"download_book": handler}, size=1, on_status_change=on_change)
        await pool.start()
        try:
            pool.cancel_task("task_1")
            await queue.put(make_task())
            await asyncio.wait_for(queue.join(), timeout=2.0)
        finally:
            await pool.stop()

        assert notified[-1].status is TaskStatus.CANCELLED

    async def test_size_property(self) -> None:
        pool = WorkerPool(TaskQueue(), {}, size=3)
        assert pool.size == 3


# ---------------------------------------------------------------------------
# 生命周期管理
# ---------------------------------------------------------------------------
@pytest.fixture
def repo() -> InMemoryTaskRepository:
    return InMemoryTaskRepository()


@pytest.fixture
async def manager(repo: InMemoryTaskRepository):
    mgr = TaskManager(repo, {}, worker_count=1)
    yield mgr
    await mgr.stop()


class TestTaskManagerLifecycle:
    async def test_create_and_get(self, manager: TaskManager, repo: InMemoryTaskRepository) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, book_id="b1", enqueue=False)
        assert task.id.startswith("task_")
        loaded = await manager.get(task.id)
        assert loaded.book_id == "b1"

    async def test_get_missing_raises(self, manager: TaskManager) -> None:
        with pytest.raises(TaskNotFoundError):
            await manager.get("nope")

    async def test_list_all(self, manager: TaskManager) -> None:
        await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        await manager.create(TaskType.EXPORT_BOOK, enqueue=False)
        assert len(await manager.list()) == 2

    async def test_list_by_status(self, manager: TaskManager) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        await manager.cancel(task.id)
        assert len(await manager.list(status=TaskStatus.CANCELLED)) == 1
        assert len(await manager.list(status=TaskStatus.PENDING)) == 0

    async def test_pause_then_resume(self, manager: TaskManager) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        paused = await manager.pause(task.id)
        assert paused.status is TaskStatus.PAUSED
        resumed = await manager.resume(task.id)
        assert resumed.status is TaskStatus.PENDING

    async def test_resume_non_paused_raises(self, manager: TaskManager) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        with pytest.raises(InvalidTaskTransitionError):
            await manager.resume(task.id)

    async def test_cancel_sets_finished_at(self, manager: TaskManager) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        cancelled = await manager.cancel(task.id)
        assert cancelled.status is TaskStatus.CANCELLED
        assert cancelled.finished_at is not None

    async def test_retry_creates_new_task(self, manager: TaskManager) -> None:
        """终态不可逆，重试必须产生新任务。"""
        task = await manager.create(TaskType.DOWNLOAD_BOOK, book_id="b1", enqueue=False)
        await manager.cancel(task.id)
        retried = await manager.retry(task.id)
        assert retried.id != task.id
        assert retried.book_id == "b1"
        assert retried.status is TaskStatus.PENDING

    async def test_retry_non_terminal_raises(self, manager: TaskManager) -> None:
        task = await manager.create(TaskType.DOWNLOAD_BOOK, enqueue=False)
        with pytest.raises(InvalidTaskTransitionError):
            await manager.retry(task.id)


class TestOrphanRecovery:
    async def test_running_task_marked_failed_on_start(self, repo: InMemoryTaskRepository) -> None:
        """进程崩溃后残留的 RUNNING 任务要在启动时标成 FAILED。"""
        repo.tasks["t1"] = make_task("t1", status=TaskStatus.RUNNING)
        repo.tasks["t2"] = make_task("t2", status=TaskStatus.RETRYING)

        manager = TaskManager(repo, {}, worker_count=1)
        await manager.start()
        await manager.stop()

        for task_id in ("t1", "t2"):
            task = await repo.get(task_id)
            assert task is not None
            assert task.status is TaskStatus.FAILED
            assert task.error_code == "INTERRUPTED"
            assert task.finished_at is not None

    async def test_terminal_tasks_untouched(self, repo: InMemoryTaskRepository) -> None:
        repo.tasks["t1"] = make_task("t1", status=TaskStatus.SUCCESS)
        manager = TaskManager(repo, {}, worker_count=1)
        await manager.start()
        await manager.stop()

        task = await repo.get("t1")
        assert task is not None
        assert task.status is TaskStatus.SUCCESS
        assert task.error_code is None

    async def test_start_is_idempotent(self, repo: InMemoryTaskRepository) -> None:
        manager = TaskManager(repo, {}, worker_count=1)
        await manager.start()
        await manager.start()
        await manager.stop()

    async def test_stop_without_start_is_safe(self, repo: InMemoryTaskRepository) -> None:
        manager = TaskManager(repo, {}, worker_count=1)
        await manager.stop()


class TestTaskItem:
    async def test_item_roundtrip(self, repo: InMemoryTaskRepository) -> None:
        item = TaskItem(
            id="i1",
            task_id="t1",
            chapter_index=0,
            title="第一章",
            status=TaskItemStatus.SUCCESS,
            created_at=NOW,
            updated_at=NOW,
        )
        await repo.save_item(item)
        loaded = await repo.list_items("t1")
        assert len(loaded) == 1
        assert loaded[0].status is TaskItemStatus.SUCCESS
