# SPDX-License-Identifier: GPL-3.0-only
"""领域枚举。

所有枚举均为 ``str`` 子类，便于直接序列化到 JSON / SQLite / API。
新增取值必须同步更新 docs/domain-model/domain-model-v1.md。
"""

from __future__ import annotations

from enum import StrEnum


class SourceCapability(StrEnum):
    """书源能力声明（规划书 §9）。

    Core 不得假定书源具备全部能力，必须通过 :meth:`Source.supports` 判断。
    v1 冻结四项；其余为保留项，v1 引擎遇到时应报 ``SourceUnsupportedError``。
    """

    # --- v1 已实现 ---
    SEARCH = "search"
    BOOK = "book"
    CHAPTERS = "chapters"
    CONTENT = "content"
    # --- 保留（未来版本）---
    DISCOVER = "discover"
    IMAGE = "image"
    LOGIN = "login"
    COOKIE = "cookie"
    UPDATE = "update"


class BookStatus(StrEnum):
    """书籍连载状态（由书源尽力解析，未知时为 UNKNOWN）。"""

    UNKNOWN = "unknown"
    ONGOING = "ongoing"  # 连载中
    COMPLETED = "completed"  # 已完结


class TaskType(StrEnum):
    """任务类型。"""

    DOWNLOAD_BOOK = "download_book"
    UPDATE_BOOK = "update_book"
    EXPORT_BOOK = "export_book"
    REFRESH_SOURCE = "refresh_source"


class TaskStatus(StrEnum):
    """任务状态（规划书 §17）。

    合法转移关系见 :data:`TASK_TRANSITIONS`。
    """

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    RETRYING = "retrying"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskItemStatus(StrEnum):
    """单个下载项（通常是单章）的状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"  # 已存在且内容未变，跳过下载
    CANCELLED = "cancelled"


class ExportFormat(StrEnum):
    """导出格式。"""

    TXT = "txt"
    MARKDOWN = "markdown"
    EPUB = "epub"


class ExportStatus(StrEnum):
    """导出作业状态。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class HealthStatus(StrEnum):
    """书源健康度（规划书 §54）。"""

    HEALTHY = "healthy"  # 正常
    DEGRADED = "degraded"  # 部分能力异常
    BROKEN = "broken"  # 已失效
    UNSUPPORTED = "unsupported"  # 引擎版本不兼容
    UNKNOWN = "unknown"  # 尚未检测


class ChapterChangeKind(StrEnum):
    """增量更新中章节的差异类型（规划书 §20）。"""

    NEW = "new"
    CHANGED = "changed"
    MISSING = "missing"
    UNCHANGED = "unchanged"


# ---------------------------------------------------------------------------
# 任务状态机（规划书 §17 的补全）
# ---------------------------------------------------------------------------
# 说明：规划书列出了状态但未定义转移规则；此处将其形式化并作为唯一事实来源。
# key = 当前状态，value = 允许转移到的状态集合。
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.PAUSED,
            TaskStatus.RETRYING,
            TaskStatus.SUCCESS,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.FAILED}
    ),
    TaskStatus.RETRYING: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    # 终态：不允许再转移（重试通过创建新任务实现）
    TaskStatus.SUCCESS: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_TASK_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED}
)


def can_transition(src: TaskStatus, dst: TaskStatus) -> bool:
    """判断任务状态转移是否合法。"""
    return dst in TASK_TRANSITIONS.get(src, frozenset())


__all__ = [
    "TASK_TRANSITIONS",
    "TERMINAL_TASK_STATUSES",
    "BookStatus",
    "ChapterChangeKind",
    "ExportFormat",
    "ExportStatus",
    "HealthStatus",
    "SourceCapability",
    "TaskItemStatus",
    "TaskStatus",
    "TaskType",
    "can_transition",
]
