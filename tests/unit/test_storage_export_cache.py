# SPDX-License-Identifier: GPL-3.0-only
"""导出记录仓储与 HTTP 缓存测试。

缓存部分重点测三层失效：TTL、显式清除、容量淘汰。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from mograb.domain.enums import ExportFormat, ExportStatus
from mograb.domain.export import ExportRecord
from mograb.network.cache import CacheEntry, make_entry
from mograb.storage import Database, SqliteExportRepository, SqliteHttpCache
from mograb.storage.models import BookRow, HttpCacheRow, SourceRow

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.init_schema()

    # exports.book_id -> books.id -> sources.id，两级外键都要先铺好
    async with database.transaction() as session:
        session.add(
            SourceRow(
                id="src",
                name="Src",
                version="1.0.0",
                installed_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
        session.add(
            BookRow(
                id="book_1",
                source_id="src",
                source_book_id="1",
                title="三体",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
        session.add(
            BookRow(
                id="book_2",
                source_id="src",
                source_book_id="2",
                title="球状闪电",
                created_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )

    yield database
    await database.dispose()


@pytest.fixture
def exports(db: Database) -> SqliteExportRepository:
    return SqliteExportRepository(db)


def make_record(export_id: str = "exp_1", **overrides) -> ExportRecord:
    data = {
        "id": export_id,
        "book_id": "book_1",
        "format": ExportFormat.EPUB,
        "status": ExportStatus.PENDING,
        "created_at": NOW,
    }
    data.update(overrides)
    return ExportRecord(**data)


class TestExportRepository:
    async def test_save_and_get(self, exports: SqliteExportRepository) -> None:
        await exports.save(make_record())
        loaded = await exports.get("exp_1")
        assert loaded is not None
        assert loaded.format is ExportFormat.EPUB
        assert loaded.status is ExportStatus.PENDING
        assert loaded.path is None

    async def test_get_missing_returns_none(self, exports: SqliteExportRepository) -> None:
        assert await exports.get("nope") is None

    async def test_status_progresses_to_success(self, exports: SqliteExportRepository) -> None:
        """导出是异步作业：先 pending，跑完才有 path。"""
        await exports.save(make_record())

        await exports.save(
            make_record(
                status=ExportStatus.SUCCESS,
                path="exports/三体.epub",
                size_bytes=2048,
                finished_at=NOW + timedelta(seconds=30),
            )
        )

        loaded = await exports.get("exp_1")
        assert loaded is not None
        assert loaded.status is ExportStatus.SUCCESS
        assert loaded.path == "exports/三体.epub"
        assert loaded.size_bytes == 2048
        assert loaded.is_terminal is True

    async def test_failure_records_message(self, exports: SqliteExportRepository) -> None:
        await exports.save(
            make_record(
                status=ExportStatus.FAILED,
                error_message="磁盘满了",
                finished_at=NOW,
            )
        )
        loaded = await exports.get("exp_1")
        assert loaded is not None
        assert loaded.error_message == "磁盘满了"
        assert loaded.is_terminal is True

    async def test_list_by_book(self, exports: SqliteExportRepository) -> None:
        await exports.save(make_record("e1", book_id="book_1"))
        await exports.save(make_record("e2", book_id="book_2"))
        await exports.save(make_record("e3", book_id="book_1"))

        found = await exports.list_by_book("book_1")
        assert sorted(r.id for r in found) == ["e1", "e3"]

    async def test_list_by_book_orders_newest_first(self, exports: SqliteExportRepository) -> None:
        await exports.save(make_record("old", created_at=NOW))
        await exports.save(make_record("new", created_at=NOW + timedelta(hours=1)))

        found = await exports.list_by_book("book_1")
        assert [r.id for r in found] == ["new", "old"]

    async def test_list_recent_respects_limit(self, exports: SqliteExportRepository) -> None:
        for i in range(5):
            await exports.save(make_record(f"e{i}", created_at=NOW + timedelta(minutes=i)))
        assert len(await exports.list_recent(limit=2)) == 2

    async def test_delete(self, exports: SqliteExportRepository) -> None:
        await exports.save(make_record())
        assert await exports.delete("exp_1") is True
        assert await exports.delete("exp_1") is False
        assert await exports.get("exp_1") is None


@pytest.fixture
def cache(db: Database) -> SqliteHttpCache:
    return SqliteHttpCache(db)


class TestHttpCacheBasics:
    async def test_put_and_get(self, cache: SqliteHttpCache) -> None:
        entry = make_entry(
            key="k1",
            source_id="s1",
            url="https://x.com/a",
            status_code=200,
            content=b"<p>ok</p>",
            encoding="utf-8",
            ttl_seconds=60,
        )
        await cache.put(entry)

        loaded = await cache.get("k1")
        assert loaded is not None
        assert loaded.content == b"<p>ok</p>"
        assert loaded.encoding == "utf-8"
        assert loaded.status_code == 200

    async def test_get_missing_returns_none(self, cache: SqliteHttpCache) -> None:
        assert await cache.get("nope") is None

    async def test_binary_content_roundtrip(self, cache: SqliteHttpCache) -> None:
        """正文可能是 GBK 字节，不能当文本存。"""
        raw = "中文正文".encode("gb18030")
        await cache.put(
            make_entry(
                key="k1", source_id="s", url="u", status_code=200, content=raw, encoding="gb18030"
            )
        )
        loaded = await cache.get("k1")
        assert loaded is not None
        assert loaded.content == raw

    async def test_overwrite_same_key(self, cache: SqliteHttpCache) -> None:
        await cache.put(
            make_entry(key="k", source_id="s", url="u", status_code=200, content=b"old")
        )
        await cache.put(
            make_entry(key="k", source_id="s", url="u", status_code=200, content=b"new")
        )
        loaded = await cache.get("k")
        assert loaded is not None and loaded.content == b"new"
        assert (await cache.stats())["entries"] == 1


class TestTtlExpiry:
    async def test_expired_entry_returns_none(self, cache: SqliteHttpCache) -> None:
        stale = CacheEntry(
            key="k",
            source_id="s",
            url="u",
            status_code=200,
            content=b"x",
            encoding=None,
            created_at=datetime.now(UTC) - timedelta(days=8),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        await cache.put(stale)

        assert await cache.get("k") is None

    async def test_expired_entry_is_deleted_on_read(self, cache: SqliteHttpCache) -> None:
        """读到过期条目顺手删掉，不用等下一次清理。"""
        stale = CacheEntry(
            key="k",
            source_id="s",
            url="u",
            status_code=200,
            content=b"x",
            encoding=None,
            created_at=datetime.now(UTC) - timedelta(days=8),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        await cache.put(stale)
        await cache.get("k")

        assert (await cache.stats())["entries"] == 0

    async def test_fresh_entry_survives(self, cache: SqliteHttpCache) -> None:
        await cache.put(
            make_entry(
                key="k", source_id="s", url="u", status_code=200, content=b"x", ttl_seconds=3600
            )
        )
        assert await cache.get("k") is not None

    async def test_purge_expired_bulk(self, cache: SqliteHttpCache) -> None:
        for i in range(3):
            await cache.put(
                CacheEntry(
                    key=f"stale{i}",
                    source_id="s",
                    url=f"u{i}",
                    status_code=200,
                    content=b"x",
                    encoding=None,
                    created_at=datetime.now(UTC) - timedelta(days=8),
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                )
            )
        await cache.put(
            make_entry(
                key="fresh", source_id="s", url="u", status_code=200, content=b"x", ttl_seconds=600
            )
        )

        assert await cache.purge_expired() == 3
        assert (await cache.stats())["entries"] == 1


class TestExplicitInvalidation:
    async def test_invalidate_url(self, cache: SqliteHttpCache) -> None:
        await cache.put(
            make_entry(
                key="a", source_id="s1", url="https://x.com/1", status_code=200, content=b"a"
            )
        )
        await cache.put(
            make_entry(
                key="b", source_id="s1", url="https://x.com/2", status_code=200, content=b"b"
            )
        )

        assert await cache.invalidate_url("s1", "https://x.com/1") == 1
        assert await cache.get("a") is None
        assert await cache.get("b") is not None

    async def test_invalidate_source_only_hits_that_source(self, cache: SqliteHttpCache) -> None:
        await cache.put(make_entry(key="a", source_id="s1", url="u", status_code=200, content=b"a"))
        await cache.put(make_entry(key="b", source_id="s2", url="u", status_code=200, content=b"b"))

        assert await cache.invalidate_source("s1") == 1
        assert await cache.get("b") is not None

    async def test_clear(self, cache: SqliteHttpCache) -> None:
        for i in range(3):
            await cache.put(
                make_entry(key=f"k{i}", source_id="s", url=f"u{i}", status_code=200, content=b"x")
            )

        assert await cache.clear() == 3
        assert (await cache.stats())["entries"] == 0

    async def test_invalidate_missing_returns_zero(self, cache: SqliteHttpCache) -> None:
        assert await cache.invalidate_url("s", "nope") == 0
        assert await cache.invalidate_source("nope") == 0


class TestCapacity:
    async def test_unlimited_when_zero(self, db: Database) -> None:
        cache = SqliteHttpCache(db, max_size_bytes=0)
        for i in range(10):
            await cache.put(
                make_entry(
                    key=f"k{i}", source_id="s", url=f"u{i}", status_code=200, content=b"x" * 100
                )
            )
        assert (await cache.stats())["entries"] == 10

    async def test_evicts_when_over_limit(self, db: Database) -> None:
        cache = SqliteHttpCache(db, max_size_bytes=250)
        for i in range(5):
            await cache.put(
                make_entry(
                    key=f"k{i}", source_id="s", url=f"u{i}", status_code=200, content=b"x" * 100
                )
            )

        stats = await cache.stats()
        assert stats["size_bytes"] <= 250
        assert stats["entries"] < 5

    async def test_evicts_least_recently_accessed(self, db: Database) -> None:
        """淘汰顺序按最久未访问，不是按插入顺序。"""
        cache = SqliteHttpCache(db, max_size_bytes=250)

        # 三个条目，各 100 字节
        for i in range(3):
            await cache.put(
                make_entry(
                    key=f"k{i}", source_id="s", url=f"u{i}", status_code=200, content=b"x" * 100
                )
            )

        # 手工把 k1 的访问时间改成最新，k0 最旧 —— 这样淘汰顺序才确定
        async with db.transaction() as session:
            for key, offset in (("k0", 3), ("k1", 0), ("k2", 2)):
                await session.execute(
                    update(HttpCacheRow)
                    .where(HttpCacheRow.key == key)
                    .values(accessed_at=(datetime.now(UTC) - timedelta(hours=offset)).isoformat())
                )

        # 再塞一个，触发淘汰：应删掉最旧的 k0
        await cache.put(
            make_entry(key="k3", source_id="s", url="u3", status_code=200, content=b"x" * 100)
        )

        assert await cache.get("k0") is None
        assert await cache.get("k1") is not None
        assert await cache.get("k3") is not None

    async def test_enforce_capacity_returns_count(self, db: Database) -> None:
        cache = SqliteHttpCache(db, max_size_bytes=150)
        for i in range(3):
            await cache.put(
                make_entry(
                    key=f"k{i}", source_id="s", url=f"u{i}", status_code=200, content=b"x" * 100
                )
            )
        # put 时已经淘汰过，这里再调一次应该没事可做
        assert await cache.enforce_capacity() == 0

    async def test_stats_reports_limit(self, db: Database) -> None:
        cache = SqliteHttpCache(db, max_size_bytes=1024)
        assert (await cache.stats())["max_size_bytes"] == 1024
