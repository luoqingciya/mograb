# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 领域层 —— 全项目最稳定的契约。

本层只依赖 pydantic 与标准库，**不得**依赖 httpx / sqlalchemy / fastapi 等外围设施。
任何对领域模型的破坏性变更都必须同步 docs/domain-model/domain-model-v1.md。
"""

from .book import Book
from .chapter import Chapter, compute_content_hash, normalize_url
from .enums import (
    TASK_TRANSITIONS,
    TERMINAL_TASK_STATUSES,
    BookStatus,
    ChapterChangeKind,
    ExportFormat,
    ExportStatus,
    HealthStatus,
    SourceCapability,
    TaskItemStatus,
    TaskStatus,
    TaskType,
    can_transition,
)
from .export import ExportRecord
from .ids import new_id, new_ulid
from .source import (
    SPEC_VERSION,
    BookSpec,
    ChapterSpec,
    CleanSpec,
    ContentSpec,
    ExtractRule,
    InstalledSource,
    NetworkPolicy,
    Permissions,
    RequestSpec,
    ResponseSpec,
    ResultSpec,
    RuleType,
    SearchSpec,
    SourceSpec,
    Transform,
    TransformOp,
)
from .task import Task, TaskItem

__all__ = [
    "SPEC_VERSION",
    "TASK_TRANSITIONS",
    "TERMINAL_TASK_STATUSES",
    "Book",
    "BookSpec",
    "BookStatus",
    "Chapter",
    "ChapterChangeKind",
    "ChapterSpec",
    "CleanSpec",
    "ContentSpec",
    "ExportFormat",
    "ExportRecord",
    "ExportStatus",
    "ExtractRule",
    "HealthStatus",
    "InstalledSource",
    "NetworkPolicy",
    "Permissions",
    "RequestSpec",
    "ResponseSpec",
    "ResultSpec",
    "RuleType",
    "SearchSpec",
    "SourceCapability",
    "SourceSpec",
    "Task",
    "TaskItem",
    "TaskItemStatus",
    "TaskStatus",
    "TaskType",
    "Transform",
    "TransformOp",
    "can_transition",
    "compute_content_hash",
    "new_id",
    "new_ulid",
    "normalize_url",
]
