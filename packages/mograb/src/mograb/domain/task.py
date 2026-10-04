# SPDX-License-Identifier: GPL-3.0-only
"""Task 领域模型（规划书 §17、§18）。

规划书列出了任务状态但**未定义状态转移规则**；本模块将状态机形式化，
并提供 :meth:`Task.transition_to` 作为唯一合法的状态变更入口，
非法转移抛 ``InvalidTaskTransitionError``。

补全项（对应规划书 §39「数据一致性」）：
任务携带 ``resume_cursor`` 与 ``book_id``，使进程崩溃后可以恢复执行。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..errors import InvalidTaskTransitionError
from .enums import TERMINAL_TASK_STATUSES, TaskItemStatus, TaskStatus, TaskType, can_transition


class TaskItem(BaseModel):
    """任务下的单个工作单元（通常是一章）。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    task_id: str
    chapter_id: str | None = None
    chapter_index: int | None = None
    title: str | None = None

    status: TaskItemStatus = TaskItemStatus.PENDING
    attempts: int = 0
    error_code: str | None = None
    error_message: str | None = None

    created_at: datetime
    updated_at: datetime


class Task(BaseModel):
    """一个下载 / 更新 / 导出任务。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    priority: int = Field(default=0, ge=0, le=100)

    # --- 关联 ---
    source_id: str | None = None
    book_id: str | None = None

    # --- 进度 ---
    total: int = 0
    completed: int = 0
    failed: int = 0
    retry_count: int = 0
    max_retries: int = Field(default=3, ge=0, le=10)

    # --- 恢复点（进程崩溃后续跑）---
    resume_cursor: int | None = Field(default=None, description="已处理到的章节序号，用于断点续传")

    # --- 错误 ---
    error_code: str | None = None
    error_message: str | None = None

    # --- 时间戳 ---
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    # ---- 派生 ----
    @property
    def progress(self) -> float:
        """完成比例，区间 [0, 1]；total 为 0 时返回 0。"""
        if self.total <= 0:
            return 0.0
        return min(1.0, (self.completed + self.failed) / self.total)

    @property
    def is_terminal(self) -> bool:
        """是否处于终态。"""
        return self.status in TERMINAL_TASK_STATUSES

    # ---- 状态机 ----
    def transition_to(self, new_status: TaskStatus) -> None:
        """变更状态，非法转移抛 :class:`InvalidTaskTransitionError`。

        这是修改 ``status`` 的唯一合法途径；Repository 层在持久化前
        应再次校验，防止绕过。
        """
        if new_status == self.status:
            return
        if not can_transition(self.status, new_status):
            raise InvalidTaskTransitionError(
                f"非法状态转移: {self.status.value} -> {new_status.value}",
                details={"task_id": self.id, "from": self.status.value, "to": new_status.value},
            )
        self.status = new_status


__all__ = ["Task", "TaskItem"]
