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
from ..domain.chapter import Chapter, ChapterSearchHit, ChapterSummary
from ..domain.enums import HealthStatus, TaskStatus
from ..domain.export import ExportRecord
from ..domain.source import InstalledSource, SourceSpec
from ..domain.task import Task, TaskItem


@runtime_checkable
class SourceRepository(Protocol):
    """书源仓储。

    书源定义存在磁盘上（``<sources_dir>/<id>/source.yaml``），
    数据库只存「装没装、启没启用、体检结果、版本历史」这类本机记账。
    所以这个仓储同时碰文件系统和数据库 —— 它持久化的是整个
    :class:`InstalledSource` 聚合，而不只是一行数据。
    """

    async def get(self, source_id: str) -> InstalledSource | None: ...

    async def save(self, source: SourceSpec) -> None:
        """安装或覆盖一个书源。已存在时把当前版本记进 previous_version。"""
        ...

    async def list_all(self) -> list[InstalledSource]: ...

    async def list_enabled(self) -> list[InstalledSource]:
        """只返回启用且未失效的，调度器挑书源用这个。"""
        ...

    async def delete(self, source_id: str) -> bool: ...

    async def set_enabled(self, source_id: str, enabled: bool) -> None: ...

    async def set_health(self, source_id: str, health: HealthStatus) -> None: ...

    async def rescan(self) -> list[InstalledSource]:
        """用磁盘上的定义重建索引。手改过文件、或换机器拷过来时用。"""
        ...


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

    async def list_summaries(self, book_id: str) -> list[ChapterSummary]:
        """列章节目录（**不含正文**）。

        列目录别用 :meth:`list_by_book` —— 那个会把整本书的正文读进内存。
        实测 2036 章的书，前者 19.3 MB、后者 0.1 MB，而用户看到的都是
        一串标题。
        """
        ...

    async def get_by_index(self, book_id: str, index: int) -> Chapter | None:
        """按序号取单章（含正文）。

        **别用 ``list_by_book`` 再筛** —— 那个会把整本书的正文都读进内存，
        一本几千章的书就是几十兆。只为读一章不值得。
        """
        ...

    async def list_identities(self, book_id: str) -> list[tuple[str, str]]: ...

    async def stats_by_book(self, book_id: str) -> tuple[int, int]:
        """返回 ``(章节数, 总字数)``。

        单独开一个方法是因为更新书籍统计时不该把全部正文读进内存 ——
        一本几千章的书，只为数个数就把几十兆正文捞出来太浪费。
        """
        ...

    async def save(self, chapter: Chapter) -> None: ...

    async def save_many(self, chapters: list[Chapter]) -> None: ...

    async def delete_by_book(self, book_id: str) -> int: ...

    async def search_content(
        self,
        keyword: str,
        *,
        book_id: str | None = None,
        limit: int = 50,
    ) -> list[ChapterSearchHit]:
        """在已下载的章节正文里搜关键词（纯本地，不访问网络）。

        Args:
            keyword: 关键词，按**字面子串**匹配（不解析正则）。
            book_id: 限定某一本书；为 None 时搜整个库。
            limit: 返回条数上限。

        只返回命中处的片段，不返回整章正文 —— 否则搜一次就要把整个库
        的正文读进内存。
        """
        ...


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
    """导出记录仓储。

    导出是异步作业（§29），所以这里存的是作业状态而非成品流水。
    """

    async def save(self, record: ExportRecord) -> None: ...

    async def get(self, export_id: str) -> ExportRecord | None: ...

    async def list_by_book(self, book_id: str) -> list[ExportRecord]: ...

    async def list_recent(self, *, limit: int = ...) -> list[ExportRecord]: ...


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
