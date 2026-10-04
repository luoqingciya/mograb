# SPDX-License-Identifier: GPL-3.0-only
"""仓储接口（规划书 §25）。

业务层**不得直接写 SQL**。所有持久化都通过仓储协议完成，
以便未来替换底层数据库（SQLite → PostgreSQL）而无需改动业务代码。

命名约定：所有方法均为 ``async``，即使 SQLite 是同步的 —— 由实现层
用 ``run_in_executor`` 或 aiosqlite 桥接，保证接口不因后端而变。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import TaskStatus
from ..domain.source import SourceSpec
from ..domain.task import Task, TaskItem


@runtime_checkable
class SourceRepository(Protocol):
    """书源仓储。"""

    async def get(self, source_id: str) -> SourceSpec | None: ...

    async def save(self, source: SourceSpec) -> None: ...

    async def list_all(self) -> list[SourceSpec]: ...

    async def delete(self, source_id: str) -> bool: ...

    async def set_enabled(self, source_id: str, enabled: bool) -> None: ...


@runtime_checkable
class BookRepository(Protocol):
    """书籍仓储。"""

    async def get(self, book_id: str) -> Book | None: ...

    async def get_by_identity(self, source_id: str, source_book_id: str) -> Book | None: ...

    async def save(self, book: Book) -> None: ...

    async def list_all(self, *, limit: int = ..., offset: int = ...) -> list[Book]: ...

    async def delete(self, book_id: str) -> bool: ...

    async def count(self) -> int: ...


@runtime_checkable
class ChapterRepository(Protocol):
    """章节仓储。"""

    async def get(self, chapter_id: str) -> Chapter | None: ...

    async def list_by_book(self, book_id: str) -> list[Chapter]: ...

    async def list_identities(self, book_id: str) -> list[tuple[str, str]]: ...

    async def save(self, chapter: Chapter) -> None: ...

    async def save_many(self, chapters: list[Chapter]) -> None: ...

    async def delete_by_book(self, book_id: str) -> int: ...


@runtime_checkable
class TaskRepository(Protocol):
    """任务仓储（与 :mod:`mograb.task.manager` 的协议一致）。"""

    async def get(self, task_id: str) -> Task | None: ...

    async def save(self, task: Task) -> None: ...

    async def list_all(self, *, status: TaskStatus | None = ...) -> list[Task]: ...

    async def list_by_status(self, status: TaskStatus) -> list[Task]: ...

    async def list_items(self, task_id: str) -> list[TaskItem]: ...

    async def save_item(self, item: TaskItem) -> None: ...


@runtime_checkable
class ExportRepository(Protocol):
    """导出记录仓储。"""

    async def save(self, record: object) -> None: ...

    async def list_by_book(self, book_id: str) -> list[object]: ...


@runtime_checkable
class SettingsRepository(Protocol):
    """键值配置仓储。"""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str) -> None: ...

    async def all(self) -> dict[str, str]: ...


__all__ = [
    "BookRepository",
    "ChapterRepository",
    "ExportRepository",
    "SettingsRepository",
    "SourceRepository",
    "TaskRepository",
]
