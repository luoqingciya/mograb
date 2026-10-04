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

import asyncio
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import (
    BookStatus,
    ExportFormat,
    ExportStatus,
    HealthStatus,
    TaskStatus,
    TaskType,
)
from ..domain.export import ExportRecord
from ..domain.source import SOURCE_ID_RE, InstalledSource, SourceSpec
from ..domain.task import Task, TaskItem
from ..logging.setup import get_logger
from ..network.cache import CacheEntry
from ..source.loader import load_source_file, write_source_file
from .models import (
    Base,
    BookRow,
    ChapterRow,
    ExportRow,
    HttpCacheRow,
    SettingRow,
    SourceRow,
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

    async def stats_by_book(self, book_id: str) -> tuple[int, int]:
        """返回 ``(章节数, 总字数)``。一次聚合查询，不读正文。"""
        async with self._db.session() as session:
            count, words = (
                await session.execute(
                    select(
                        func.count(ChapterRow.id),
                        func.coalesce(func.sum(ChapterRow.word_count), 0),
                    ).where(ChapterRow.book_id == book_id)
                )
            ).one()
        return int(count), int(words)

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
# 书源仓储
# ---------------------------------------------------------------------------
class SqliteSourceRepository:
    """书源仓储：磁盘存定义，数据库存记账。

    分工是这样的：

    - ``<sources_dir>/<id>/source.yaml`` 是**定义的唯一真相**。用户可以自己
      往里丢文件，换机器直接拷目录。
    - 数据库那张表只记「装没装、启没启用、体检结果、从哪个版本升上来的」，
      这些不属于书源定义，导出书源时也不该带出去。

    因此索引丢了不是灾难 —— :meth:`rescan` 能从磁盘重建。
    反过来文件丢了，索引里的那行就没意义，会被跳过。
    """

    def __init__(self, db: Database, sources_dir: Path) -> None:
        self._db = db
        self._dir = Path(sources_dir)

    def source_path(self, source_id: str) -> Path:
        """书源定义文件的位置。"""
        return self._dir / source_id / "source.yaml"

    # ------------------------------------------------------------------
    async def get(self, source_id: str) -> InstalledSource | None:
        async with self._db.session() as session:
            row = await session.get(SourceRow, source_id)
            if row is None:
                return None
            meta = _source_meta(row)

        spec = await asyncio.to_thread(_read_source_spec, self.source_path(source_id))
        if spec is None:
            # 索引里有、磁盘上没有 —— 数据不一致，当没装处理
            _logger.warning("storage.source_file_missing", source_id=source_id)
            return None
        return InstalledSource(spec=spec, **meta)

    async def save(self, source: SourceSpec) -> None:
        """安装或覆盖。先落盘再写索引 —— 磁盘写失败就不该留下索引。"""
        await asyncio.to_thread(write_source_file, source, self.source_path(source.id))

        now = utc_now_iso()
        async with self._db.transaction() as session:
            row = await session.get(SourceRow, source.id)
            if row is None:
                session.add(
                    SourceRow(
                        id=source.id,
                        name=source.name,
                        version=source.version,
                        spec_version=source.spec_version,
                        homepage=source.homepage,
                        license=source.license,
                        capabilities=[c.value for c in source.capabilities],
                        enabled=True,
                        installed_version=source.version,
                        previous_version=None,
                        health=HealthStatus.UNKNOWN.value,
                        installed_at=now,
                        updated_at=now,
                    )
                )
                return

            row.name = source.name
            row.version = source.version
            row.spec_version = source.spec_version
            row.homepage = source.homepage
            row.license = source.license
            row.capabilities = [c.value for c in source.capabilities]
            row.updated_at = now
            # 版本真变了才记 previous。同版本重装不该把回滚点冲掉。
            if row.installed_version != source.version:
                row.previous_version = row.installed_version
                row.installed_version = source.version

    async def list_all(self) -> list[InstalledSource]:
        async with self._db.session() as session:
            rows = (await session.execute(select(SourceRow))).scalars().all()
            entries = [(row.id, _source_meta(row)) for row in rows]

        installed: list[InstalledSource] = []
        for source_id, meta in entries:
            spec = await asyncio.to_thread(_read_source_spec, self.source_path(source_id))
            if spec is None:
                _logger.warning("storage.source_file_missing", source_id=source_id)
                continue
            installed.append(InstalledSource(spec=spec, **meta))
        return installed

    async def list_enabled(self) -> list[InstalledSource]:
        """启用且未失效的书源。调度器挑源时用这个。"""
        return [entry for entry in await self.list_all() if entry.is_usable]

    async def delete(self, source_id: str) -> bool:
        # 目录名来自 ID，先挡住越界输入再动文件系统
        if not SOURCE_ID_RE.match(source_id):
            return False

        async with self._db.transaction() as session:
            row = await session.get(SourceRow, source_id)
            if row is None:
                return False
            await session.delete(row)

        target = self._dir / source_id
        if target.is_dir():
            await asyncio.to_thread(shutil.rmtree, target, True)
        return True

    async def set_enabled(self, source_id: str, enabled: bool) -> None:
        async with self._db.transaction() as session:
            row = await session.get(SourceRow, source_id)
            if row is None:
                from ..errors import SourceNotFoundError

                raise SourceNotFoundError(
                    f"书源未安装: {source_id}", details={"source_id": source_id}
                )
            row.enabled = enabled
            row.updated_at = utc_now_iso()

    async def set_health(self, source_id: str, health: HealthStatus) -> None:
        async with self._db.transaction() as session:
            row = await session.get(SourceRow, source_id)
            if row is None:
                from ..errors import SourceNotFoundError

                raise SourceNotFoundError(
                    f"书源未安装: {source_id}", details={"source_id": source_id}
                )
            row.health = health.value
            row.updated_at = utc_now_iso()

    async def rescan(self) -> list[InstalledSource]:
        """用磁盘上的定义重建索引。

        手改过 ``source.yaml``、或者把整个 data 目录拷到另一台机器上时用。
        已存在的行只更新定义相关的字段，``enabled`` 和 ``health`` 保留 ——
        用户手动改过的开关不该被一次扫描重置。
        """
        if not self._dir.is_dir():
            return []

        found: list[SourceSpec] = []
        for path in sorted(self._dir.glob("*/source.yaml")):
            spec = await asyncio.to_thread(_read_source_spec, path)
            if spec is not None:
                found.append(spec)

        now = utc_now_iso()
        found_ids = {spec.id for spec in found}
        async with self._db.transaction() as session:
            existing = {row.id: row for row in (await session.execute(select(SourceRow))).scalars()}
            for spec in found:
                row = existing.get(spec.id)
                if row is None:
                    session.add(
                        SourceRow(
                            id=spec.id,
                            name=spec.name,
                            version=spec.version,
                            spec_version=spec.spec_version,
                            homepage=spec.homepage,
                            license=spec.license,
                            capabilities=[c.value for c in spec.capabilities],
                            enabled=True,
                            installed_version=spec.version,
                            previous_version=None,
                            health=HealthStatus.UNKNOWN.value,
                            installed_at=now,
                            updated_at=now,
                        )
                    )
                    continue
                row.name = spec.name
                row.version = spec.version
                row.spec_version = spec.spec_version
                row.homepage = spec.homepage
                row.license = spec.license
                row.capabilities = [c.value for c in spec.capabilities]
                row.installed_version = spec.version
                row.updated_at = now

            # 磁盘上没有的，索引里也不该留着
            for source_id, row in existing.items():
                if source_id not in found_ids:
                    await session.delete(row)

        return await self.list_all()


# ---------------------------------------------------------------------------
# 导出记录仓储
# ---------------------------------------------------------------------------
class SqliteExportRepository:
    """导出作业记录。

    导出是异步的（§29），所以这里存的是作业状态：创建时 PENDING，
    跑完变 SUCCESS 或 FAILED。``path`` 在完成前是 None。
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def save(self, record: ExportRecord) -> None:
        async with self._db.transaction() as session:
            row = await session.get(ExportRow, record.id)
            if row is None:
                session.add(_to_export_row(record))
            else:
                _apply_export(record, row)

    async def get(self, export_id: str) -> ExportRecord | None:
        async with self._db.session() as session:
            row = await session.get(ExportRow, export_id)
            return _to_export(row) if row else None

    async def list_by_book(self, book_id: str) -> list[ExportRecord]:
        async with self._db.session() as session:
            stmt = (
                select(ExportRow)
                .where(ExportRow.book_id == book_id)
                .order_by(ExportRow.created_at.desc())
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_export(r) for r in rows]

    async def list_recent(self, *, limit: int = 50) -> list[ExportRecord]:
        async with self._db.session() as session:
            stmt = select(ExportRow).order_by(ExportRow.created_at.desc()).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_export(r) for r in rows]

    async def delete(self, export_id: str) -> bool:
        async with self._db.transaction() as session:
            row = await session.get(ExportRow, export_id)
            if row is None:
                return False
            await session.delete(row)
            return True


# ---------------------------------------------------------------------------
# HTTP 缓存
# ---------------------------------------------------------------------------
ACCESS_REFRESH_INTERVAL = timedelta(hours=1)
"""命中时间的更新粒度。

严格 LRU 要在每次读取时回写 ``accessed_at``，代价是缓存命中变成一次写库。
这里按小时粒度更新：够用来做容量淘汰的排序，又不会让读操作频繁触发写入。
"""


class SqliteHttpCache:
    """HTTP 缓存的 SQLite 实现（规划书 §16）。

    失效分三层，这里都有：

    - **TTL**：条目自带 ``expires_at``，读的时候发现过期就顺手删掉
    - **显式**：``invalidate_url`` / ``invalidate_source`` / ``clear``
    - **容量**：``max_size_bytes`` 满了按「最久未访问」淘汰

    ``max_size_bytes`` 传 0 表示不限容量（测试和临时用）。
    """

    def __init__(self, db: Database, *, max_size_bytes: int = 0) -> None:
        self._db = db
        self._max_size_bytes = max(0, max_size_bytes)

    # ------------------------------------------------------------------
    async def get(self, key: str) -> CacheEntry | None:
        now = datetime.now(UTC)
        async with self._db.transaction() as session:
            row = await session.get(HttpCacheRow, key)
            if row is None:
                return None

            if _parse_dt(row.expires_at) <= now:
                await session.delete(row)
                return None

            # 近似 LRU：只有距上次记录超过一小时才回写，避免每次读都写库
            accessed = _parse_dt(row.accessed_at)
            if now - accessed >= ACCESS_REFRESH_INTERVAL:
                row.accessed_at = now.isoformat()

            return _to_cache_entry(row)

    async def put(self, entry: CacheEntry) -> None:
        async with self._db.transaction() as session:
            row = await session.get(HttpCacheRow, entry.key)
            if row is None:
                session.add(_to_cache_row(entry))
            else:
                _apply_cache_entry(entry, row)

        await self.enforce_capacity()

    async def invalidate_url(self, source_id: str, url: str) -> int:
        async with self._db.transaction() as session:
            result = await session.execute(
                delete(HttpCacheRow).where(
                    HttpCacheRow.source_id == source_id,
                    HttpCacheRow.url == url,
                )
            )
            return int(getattr(result, "rowcount", 0) or 0)

    async def invalidate_source(self, source_id: str) -> int:
        async with self._db.transaction() as session:
            result = await session.execute(
                delete(HttpCacheRow).where(HttpCacheRow.source_id == source_id)
            )
            return int(getattr(result, "rowcount", 0) or 0)

    async def clear(self) -> int:
        async with self._db.transaction() as session:
            result = await session.execute(delete(HttpCacheRow))
            return int(getattr(result, "rowcount", 0) or 0)

    async def stats(self) -> dict[str, int]:
        async with self._db.session() as session:
            count, total = (
                await session.execute(
                    select(
                        func.count(HttpCacheRow.key),
                        func.coalesce(func.sum(HttpCacheRow.size_bytes), 0),
                    )
                )
            ).one()
        return {
            "entries": int(count),
            "size_bytes": int(total),
            "max_size_bytes": self._max_size_bytes,
        }

    # ------------------------------------------------------------------
    async def purge_expired(self) -> int:
        """清掉已过期的条目。返回删除数量。"""
        async with self._db.transaction() as session:
            result = await session.execute(
                delete(HttpCacheRow).where(HttpCacheRow.expires_at <= datetime.now(UTC).isoformat())
            )
            return int(getattr(result, "rowcount", 0) or 0)

    async def enforce_capacity(self) -> int:
        """超出容量上限时按最久未访问淘汰。返回淘汰数量。

        一次查询拿全量 (key, size) 排序后累减，再一条 DELETE 批量删 ——
        比循环「查一条删一条」少很多次往返。
        """
        if self._max_size_bytes <= 0:
            return 0

        async with self._db.transaction() as session:
            rows = (
                await session.execute(
                    select(HttpCacheRow.key, HttpCacheRow.size_bytes).order_by(
                        HttpCacheRow.accessed_at
                    )
                )
            ).all()
            total = sum(size for _, size in rows)
            if total <= self._max_size_bytes:
                return 0

            doomed: list[str] = []
            for key, size in rows:
                if total <= self._max_size_bytes:
                    break
                doomed.append(key)
                total -= size

            if doomed:
                await session.execute(delete(HttpCacheRow).where(HttpCacheRow.key.in_(doomed)))

        if doomed:
            _logger.info("storage.cache_evicted", removed=len(doomed))
        return len(doomed)


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
        url=row.url,
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
    row.url = book.url
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
        params=row.params or {},
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
    row.params = task.params
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


def _source_meta(row: SourceRow) -> dict[str, Any]:
    """把书源行里「不属于书源定义」的字段抽成字典。

    单独抽出来是因为后面要出 session 读文件，不能挂着 ORM 实例到处跑。
    """
    return {
        "enabled": row.enabled,
        "health": HealthStatus(row.health),
        "installed_version": row.installed_version,
        "previous_version": row.previous_version,
        "installed_at": _parse_dt(row.installed_at) if row.installed_at else None,
        "updated_at": _parse_dt(row.updated_at) if row.updated_at else None,
    }


def _read_source_spec(path: Path) -> SourceSpec | None:
    """读一个书源定义文件，失败返回 None。

    单个书源坏掉不该让整个 ``list_all()`` 崩掉 —— 用户可能手改错了某一份，
    其余书源还得能用。调用方负责打日志。
    """
    if not path.is_file():
        return None
    try:
        return load_source_file(path)
    except Exception as exc:
        _logger.warning("storage.source_load_failed", path=str(path), error=str(exc))
        return None


def _to_export(row: ExportRow) -> ExportRecord:
    return ExportRecord(
        id=row.id,
        book_id=row.book_id,
        format=ExportFormat(row.format),
        status=ExportStatus(row.status),
        path=row.path,
        size_bytes=row.size_bytes,
        error_message=row.error_message,
        created_at=_parse_dt(row.created_at),
        finished_at=_parse_dt(row.finished_at) if row.finished_at else None,
    )


def _to_export_row(record: ExportRecord) -> ExportRow:
    row = ExportRow(id=record.id)
    _apply_export(record, row)
    row.created_at = record.created_at.isoformat()
    return row


def _apply_export(record: ExportRecord, row: ExportRow) -> None:
    row.book_id = record.book_id
    row.format = record.format.value
    row.status = record.status.value
    row.path = record.path
    row.size_bytes = record.size_bytes
    row.error_message = record.error_message
    row.finished_at = record.finished_at.isoformat() if record.finished_at else None


def _to_cache_entry(row: HttpCacheRow) -> CacheEntry:
    return CacheEntry(
        key=row.key,
        source_id=row.source_id,
        url=row.url,
        status_code=row.status_code,
        content=row.content,
        encoding=row.encoding,
        created_at=_parse_dt(row.created_at),
        expires_at=_parse_dt(row.expires_at),
    )


def _to_cache_row(entry: CacheEntry) -> HttpCacheRow:
    row = HttpCacheRow(key=entry.key)
    _apply_cache_entry(entry, row)
    row.created_at = entry.created_at.isoformat()
    row.accessed_at = datetime.now(UTC).isoformat()
    return row


def _apply_cache_entry(entry: CacheEntry, row: HttpCacheRow) -> None:
    row.source_id = entry.source_id
    row.url = entry.url
    row.status_code = entry.status_code
    row.content = entry.content
    row.encoding = entry.encoding
    row.expires_at = entry.expires_at.isoformat()
    row.size_bytes = entry.size


def _parse_dt(value: str) -> datetime:
    """解析 ISO 时间戳。"""
    return datetime.fromisoformat(value)


__all__ = [
    "ACCESS_REFRESH_INTERVAL",
    "Database",
    "SqliteBookRepository",
    "SqliteChapterRepository",
    "SqliteExportRepository",
    "SqliteHttpCache",
    "SqliteSettingsRepository",
    "SqliteSourceRepository",
    "SqliteTaskRepository",
]
