# SPDX-License-Identifier: GPL-3.0-only
"""下载进度要**广播**出去，不能只改内存里的对象。

盯的是 ``Application._progress``。

背景：状态通知（``TaskRunner._notify``）只在**状态跃迁**时触发，
所以 SSE 原先只在「开始」和「结束」各推一条，中间什么都没有。
而桌面端的任务页没有轮询、全靠 SSE —— 进度条因此会从 0 直接跳到完成。
``_progress`` 的 docstring 却写着「API server 推 SSE 时读的是同一个对象」，
是个「声明了没接线」。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mograb.app import PROGRESS_NOTIFY_INTERVAL_SECONDS, create_application
from mograb.domain.enums import TaskStatus, TaskType
from mograb.domain.task import Task

pytestmark = pytest.mark.unit


def _make_task() -> Task:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Task(
        id="task_probe",
        type=TaskType.DOWNLOAD_BOOK,
        status=TaskStatus.RUNNING,
        book_id="book_x",
        total=100,
        completed=0,
        created_at=now,
    )


class TestProgressNotification:
    async def test_进度变化会通知监听器(self) -> None:
        async with create_application() as app:
            seen: list[tuple[int, int]] = []

            async def listener(task: Task) -> None:
                seen.append((task.completed, task.total))

            app._progress_listener = listener
            task = _make_task()
            on_progress = app._progress(task)

            await on_progress(0, 100)
            # 限流：1 秒内只推一条，所以中途的更新被丢掉
            await on_progress(50, 100)
            # 最后一条不受限流约束 —— 否则进度会停在 99%
            await on_progress(100, 100)

        assert seen[0] == (0, 100)
        assert seen[-1] == (100, 100)

    async def test_进度对象照旧被更新(self) -> None:
        """限流只影响「推不推」，不影响任务对象本身 —— 查详情还得准。"""
        async with create_application() as app:
            task = _make_task()
            on_progress = app._progress(task)

            await on_progress(37, 100)
            await on_progress(88, 100)

        assert task.completed == 88
        assert task.total == 100

    async def test_没有监听器时不炸(self) -> None:
        """CLI 就地跑任务时没有监听器（它自己有进度条）。"""
        async with create_application() as app:
            task = _make_task()

            await app._progress(task)(50, 100)

        assert task.completed == 50

    async def test_限流间隔是正数且不太大(self) -> None:
        """间隔太小会把事件流灌满，太大进度条会一顿一顿的。"""
        assert 0.2 <= PROGRESS_NOTIFY_INTERVAL_SECONDS <= 5.0
