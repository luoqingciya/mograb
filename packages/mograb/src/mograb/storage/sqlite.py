# SPDX-License-Identifier: GPL-3.0-only
"""SQLite 实现（规划书 §23、§25）。

选择 SQLite 的理由（§23）：单机优先、CLI/Desktop 通用、零部署、迁移简单。

实现要点：

- 使用 SQLAlchemy 2.0 async + aiosqlite。
- 写入开启 WAL 模式，提升并发读性能。
- **事务边界**：:meth:`Database.transaction` 提供原子写入，
  满足 §39「Download → Validate → Transaction → Persist」的一致性要求。
- 时间戳统一为 UTC ISO 字符串（见 :func:`mograb.storage.models.utc_now_iso`）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import BookStatus, TaskStatus, TaskType
from ..domain.task import Task, TaskItem
from ..logging.setup import get_logger
from .models import (
    Base,
    BookRow,
    ChapterRow,
    SettingRow,
    TaskItemRow,
    TaskRow,
    utc_now_iso,
)

_logger = get_logger(__name__)


class Database:
    """数据库连接与事务管理。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{self._path}",
            echo=False,
            future=True,
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        self._install_pragmas()

    def _install_pragmas(self) -> None:
        """启用 WAL 与外键约束。"""

        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_pragma(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    async def init_schema(self) -> None:
        """建表（幂等）。正式迁移由 Alembic 负责。"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _logger.info("storage.schema_ready", path=str(self._path))

    async def dispose(self) -> None:
        """释放连接池。"""
        await self._engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """获取会话（不自动提交）。"""
        async with self._session_factory() as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """事务上下文：正常退出提交，异常回滚。"""
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# ---------------------------------------------------------------------------
# 书籍仓储
# ---------------------------------------------------------------------------
class SqliteBookRepository:
    """:class:`~mograb.storage.repository.BookRepository` 的 SQLite 实现。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, book_id: str) -> Book | None:
        async with self._db.session() as session:
            row = await session.get(BookRow, book_id)
            return _to_book(row) if row else None

    async def get_by_identity(self, source_id: str, source_book_id: str) -> Book | None:
        async with self._db.session() as session:
            stmt = select(BookRow).where(
                BookRow.source_id == source_id,
                BookRow.source_book_id == source_book_id,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            return _to_book(row) if row else None

    async def save(self, book: Book) -> None:
        async with self._db.transaction() as session:
            await _upsert_book(session, book)

    async def save_many(self, books: list[Book]) -> None:
        """批量写入（单事务）。"""
        async with self._db.transaction() as session:
            for book in books:
                await _upsert_book(session, book)

    async def list_all(self, *, limit: int = 100, offset: int = 0) -> list[Book]:
        async with self._db.session() as session:
            stmt = select(BookRow).order_by(BookRow.updated_at.desc()).limit(limit).offset(offset)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_book(r) for r in rows]

    async def delete(self, book_id: str) -> bool:
        async with self._db.transaction() as session:
            row = await session.get(BookRow, book_id)
            if row is None:
                return False
            await session.delete(row)
            return True

    async def count(self) -> int:
        from sqlalchemy import func

        async with self._db.session() as session:
            return int(
                (await session.execute(select(func.count()).select_from(BookRow))).scalar_one()
            )


# ---------------------------------------------------------------------------
# 章节仓储
# ---------------------------------------------------------------------------
class SqliteChapterRepository:
    """:class:`~mograb.storage.repository.ChapterRepository` 的 SQLite 实现。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, chapter_id: str) -> Chapter | None:
        async with self._db.session() as session:
            row = await session.get(ChapterRow, chapter_id)
            return _to_chapter(row) if row else None

    async def list_by_book(self, book_id: str) -> list[Chapter]:
        async with self._db.session() as session:
            stmt = (
                select(ChapterRow).where(ChapterRow.book_id == book_id).order_by(ChapterRow.index)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_chapter(r) for r in rows]

    async def list_identities(self, book_id: str) -> list[tuple[str, str]]:
        """返回 ``(identity_key, content_hash)`` 列表，供增量 diff 使用。"""
        async with self._db.session() as session:
            stmt = select(ChapterRow.identity_key, ChapterRow.content_hash).where(
                ChapterRow.book_id == book_id
            )
            return [(k, h or "") for k, h in (await session.execute(stmt)).all()]

    async def save(self, chapter: Chapter) -> None:
        async with self._db.transaction() as session:
            await _upsert_chapter(session, chapter)

    async def save_many(self, chapters: list[Chapter]) -> None:
        """批量写入章节（**单事务**，保证原子性，见 §39）。"""
        async with self._db.transaction() as session:
            for chapter in chapters:
                await _upsert_chapter(session, chapter)

    async def delete_by_book(self, book_id: str) -> int:
        async with self._db.transaction() as session:
            result = await session.execute(delete(ChapterRow).where(ChapterRow.book_id == book_id))
            # AsyncSession.execute 的静态返回类型为 Result（不含 rowcount）；
            # DELETE 实际返回 CursorResult，故用 getattr 安全读取。
            return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# 任务仓储
# ---------------------------------------------------------------------------
class SqliteTaskRepository:
    """:class:`~mograb.storage.repository.TaskRepository` 的 SQLite 实现。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, task_id: str) -> Task | None:
        async with self._db.session() as session:
            row = await session.get(TaskRow, task_id)
            return _to_task(row) if row else None

    async def save(self, task: Task) -> None:
        async with self._db.transaction() as session:
            row = await session.get(TaskRow, task.id)
            if row is None:
                session.add(_to_task_row(task))
            else:
                _apply_task(task, row)

    async def list_all(self, *, status: TaskStatus | None = None) -> list[Task]:
        async with self._db.session() as session:
            stmt = select(TaskRow).order_by(TaskRow.created_at.desc())
            if status is not None:
                stmt = stmt.where(TaskRow.status == status.value)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_task(r) for r in rows]

    async def list_by_status(self, status: TaskStatus) -> list[Task]:
        return await self.list_all(status=status)

    async def list_items(self, task_id: str) -> list[TaskItem]:
        async with self._db.session() as session:
            stmt = (
                select(TaskItemRow)
                .where(TaskItemRow.task_id == task_id)
                .order_by(TaskItemRow.chapter_index)
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_task_item(r) for r in rows]

    async def save_item(self, item: TaskItem) -> None:
        async with self._db.transaction() as session:
            row = await session.get(TaskItemRow, item.id)
            if row is None:
                session.add(_to_task_item_row(item))
            else:
                _apply_task_item(item, row)


# ---------------------------------------------------------------------------
# 配置仓储
# ---------------------------------------------------------------------------
class SqliteSettingsRepository:
    """键值配置仓储。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> str | None:
        async with self._db.session() as session:
            row = await session.get(SettingRow, key)
            return row.value if row else None

    async def set(self, key: str, value: str) -> None:
        async with self._db.transaction() as session:
            row = await session.get(SettingRow, key)
            if row is None:
                session.add(SettingRow(key=key, value=value, updated_at=utc_now_iso()))
            else:
                row.value = value
                row.updated_at = utc_now_iso()

    async def all(self) -> dict[str, str]:
        async with self._db.session() as session:
            rows = (await session.execute(select(SettingRow))).scalars().all()
            return {r.key: r.value for r in rows}


# ---------------------------------------------------------------------------
# 映射辅助
# ---------------------------------------------------------------------------
async def _upsert_book(session: AsyncSession, book: Book) -> None:
    """按主键写入或更新书籍（异步，当前会话内）。"""
    row = await session.get(BookRow, book.id)
    if row is None:
        session.add(_to_book_row(book))
    else:
        _apply_book(book, row)


async def _upsert_chapter(session: AsyncSession, chapter: Chapter) -> None:
    row = await session.get(ChapterRow, chapter.id)
    if row is None:
        session.add(_to_chapter_row(chapter))
    else:
        _apply_chapter(chapter, row)


def _to_book(row: BookRow) -> Book:
    return Book(
        id=row.id,
        source_id=row.source_id,
        source_book_id=row.source_book_id,
        title=row.title,
        author=row.author,
        intro=row.intro,
        language=row.language,
        cover_url=row.cover_url,
        cover_path=row.cover_path,
        status=BookStatus(row.status),
        latest_chapter=row.latest_chapter,
        word_count=row.word_count,
        chapter_count=row.chapter_count,
        created_at=_parse_dt(row.created_at),
        updated_at=_parse_dt(row.updated_at),
        metadata=row.meta or {},
    )


def _to_book_row(book: Book) -> BookRow:
    row = BookRow(id=book.id)
    _apply_book(book, row)
    row.created_at = book.created_at.isoformat()
    return row


def _apply_book(book: Book, row: BookRow) -> None:
    row.source_id = book.source_id
    row.source_book_id = book.source_book_id
    row.title = book.title
    row.author = book.author
    row.intro = book.intro
    row.language = book.language
    row.cover_url = book.cover_url
    row.cover_path = book.cover_path
    row.status = book.status.value
    row.latest_chapter = book.latest_chapter
    row.word_count = book.word_count
    row.chapter_count = book.chapter_count
    row.updated_at = book.updated_at.isoformat()
    row.meta = book.metadata


def _to_chapter(row: ChapterRow) -> Chapter:
    return Chapter(
        id=row.id,
        book_id=row.book_id,
        source_chapter_id=row.source_chapter_id,
        title=row.title,
        url=row.url,
        index=row.index,
        content=row.content,
        content_hash=row.content_hash,
        word_count=row.word_count,
        created_at=_parse_dt(row.created_at),
        updated_at=_parse_dt(row.updated_at),
    )


def _to_chapter_row(chapter: Chapter) -> ChapterRow:
    row = ChapterRow(id=chapter.id)
    _apply_chapter(chapter, row)
    row.created_at = chapter.created_at.isoformat()
    return row


def _apply_chapter(chapter: Chapter, row: ChapterRow) -> None:
    row.book_id = chapter.book_id
    row.source_chapter_id = chapter.source_chapter_id
    row.identity_key = chapter.identity_key
    row.title = chapter.title
    row.url = chapter.url
    row.normalized_url = chapter.normalized_url
    row.index = chapter.index
    row.content = chapter.content
    row.content_hash = chapter.content_hash
    row.word_count = chapter.word_count
    row.updated_at = chapter.updated_at.isoformat()


def _to_task(row: TaskRow) -> Task:
    return Task(
        id=row.id,
        type=TaskType(row.type),
        status=TaskStatus(row.status),
        priority=row.priority,
        source_id=row.source_id,
        book_id=row.book_id,
        total=row.total,
        completed=row.completed,
        failed=row.failed,
        retry_count=row.retry_count,
        max_retries=row.max_retries,
        resume_cursor=row.resume_cursor,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=_parse_dt(row.created_at),
        started_at=_parse_dt(row.started_at) if row.started_at else None,
        finished_at=_parse_dt(row.finished_at) if row.finished_at else None,
    )


def _to_task_row(task: Task) -> TaskRow:
    row = TaskRow(id=task.id)
    _apply_task(task, row)
    row.created_at = task.created_at.isoformat()
    return row


def _apply_task(task: Task, row: TaskRow) -> None:
    row.type = task.type.value
    row.status = task.status.value
    row.priority = task.priority
    row.source_id = task.source_id
    row.book_id = task.book_id
    row.total = task.total
    row.completed = task.completed
    row.failed = task.failed
    row.retry_count = task.retry_count
    row.max_retries = task.max_retries
    row.resume_cursor = task.resume_cursor
    row.error_code = task.error_code
    row.error_message = task.error_message
    row.started_at = task.started_at.isoformat() if task.started_at else None
    row.finished_at = task.finished_at.isoformat() if task.finished_at else None


def _to_task_item(row: TaskItemRow) -> TaskItem:
    from ..domain.enums import TaskItemStatus

    return TaskItem(
        id=row.id,
        task_id=row.task_id,
        chapter_id=row.chapter_id,
        chapter_index=row.chapter_index,
        title=row.title,
        status=TaskItemStatus(row.status),
        attempts=row.attempts,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=_parse_dt(row.created_at),
        updated_at=_parse_dt(row.updated_at),
    )


def _to_task_item_row(item: TaskItem) -> TaskItemRow:
    row = TaskItemRow(id=item.id)
    _apply_task_item(item, row)
    row.created_at = item.created_at.isoformat()
    return row


def _apply_task_item(item: TaskItem, row: TaskItemRow) -> None:
    row.task_id = item.task_id
    row.chapter_id = item.chapter_id
    row.chapter_index = item.chapter_index
    row.title = item.title
    row.status = item.status.value
    row.attempts = item.attempts
    row.error_code = item.error_code
    row.error_message = item.error_message
    row.updated_at = item.updated_at.isoformat()


def _parse_dt(value: str):
    """解析 ISO 时间戳。"""
    from datetime import datetime

    return datetime.fromisoformat(value)


__all__ = [
    "Database",
    "SqliteBookRepository",
    "SqliteChapterRepository",
    "SqliteSettingsRepository",
    "SqliteTaskRepository",
]
