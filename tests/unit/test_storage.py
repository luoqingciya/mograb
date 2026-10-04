# SPDX-License-Identifier: GPL-3.0-only
"""存储层测试。

用临时文件 SQLite（不是 :memory:，因为连接池下每个连接会是独立的库）。
覆盖仓储的读写、幂等 upsert、事务回滚和唯一约束。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from mograb.domain.book import Book
from mograb.domain.chapter import Chapter
from mograb.domain.enums import BookStatus, TaskItemStatus, TaskStatus, TaskType
from mograb.domain.task import Task, TaskItem
from mograb.storage import Database
from mograb.storage.models import BookRow, SourceRow
from mograb.storage.sqlite import (
    SqliteBookRepository,
    SqliteChapterRepository,
    SqliteSettingsRepository,
    SqliteTaskRepository,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
SOURCE_ID = "example"


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.init_schema()
    # books.source_id 有外键约束（PRAGMA foreign_keys=ON），先建一条书源记录
    async with database.transaction() as session:
        session.add(
            SourceRow(
                id=SOURCE_ID,
                name="Example",
                version="1.0.0",
                installed_at=NOW.isoformat(),
                updated_at=NOW.isoformat(),
            )
        )
    yield database
    await database.dispose()


@pytest.fixture
def books(db: Database) -> SqliteBookRepository:
    return SqliteBookRepository(db)


@pytest.fixture
async def chapters(db: Database) -> SqliteChapterRepository:
    # chapters.book_id 有外键约束，先落一本书
    await SqliteBookRepository(db).save(make_book())
    return SqliteChapterRepository(db)


@pytest.fixture
def tasks(db: Database) -> SqliteTaskRepository:
    return SqliteTaskRepository(db)


@pytest.fixture
def settings(db: Database) -> SqliteSettingsRepository:
    return SqliteSettingsRepository(db)


def make_book(book_id: str = "book_1", **overrides) -> Book:
    data = {
        "id": book_id,
        "source_id": "example",
        "source_book_id": "1001",
        "url": "https://example.com/book/1001",
        "title": "三体",
        "author": "刘慈欣",
        "intro": "简介",
        "language": "zh-CN",
        "status": BookStatus.COMPLETED,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return Book(**data)


def make_chapter(chapter_id: str = "chap_1", book_id: str = "book_1", **overrides) -> Chapter:
    data = {
        "id": chapter_id,
        "book_id": book_id,
        "source_chapter_id": "c1",
        "title": "第一章",
        "url": "https://example.com/1",
        "index": 0,
        "content": "正文内容",
        "content_hash": "abc123",
        "word_count": 4,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return Chapter(**data)


class TestSchema:
    async def test_init_creates_tables(self, db: Database) -> None:
        async with db.session() as session:
            from sqlalchemy import text

            rows = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
            names = {r[0] for r in rows}
        for expected in (
            "sources",
            "books",
            "chapters",
            "tasks",
            "task_items",
            "exports",
            "http_cache",
            "settings",
        ):
            assert expected in names, f"缺表: {expected}"

    async def test_init_is_idempotent(self, tmp_path: Path) -> None:
        database = Database(tmp_path / "twice.db")
        await database.init_schema()
        await database.init_schema()
        await database.dispose()


class TestBookRepository:
    async def test_save_and_get(self, books: SqliteBookRepository) -> None:
        book = make_book()
        await books.save(book)
        loaded = await books.get("book_1")
        assert loaded is not None
        assert loaded.title == "三体"
        assert loaded.status is BookStatus.COMPLETED
        assert loaded.language == "zh-CN"

    async def test_get_missing_returns_none(self, books: SqliteBookRepository) -> None:
        assert await books.get("nope") is None

    async def test_get_by_identity(self, books: SqliteBookRepository) -> None:
        await books.save(make_book())
        found = await books.get_by_identity("example", "1001")
        assert found is not None and found.id == "book_1"
        assert await books.get_by_identity("example", "9999") is None

    async def test_save_is_idempotent(self, books: SqliteBookRepository) -> None:
        """按主键 upsert，重复写入不产生新行。"""
        book = make_book()
        await books.save(book)
        await books.save(book.model_copy(update={"title": "三体（改）"}))
        assert await books.count() == 1
        loaded = await books.get("book_1")
        assert loaded is not None and loaded.title == "三体（改）"

    async def test_metadata_roundtrip(self, books: SqliteBookRepository) -> None:
        await books.save(make_book(metadata={"tag": "科幻", "n": 1}))
        loaded = await books.get("book_1")
        assert loaded is not None
        assert loaded.metadata == {"tag": "科幻", "n": 1}

    async def test_list_all_orders_by_updated_desc(self, books: SqliteBookRepository) -> None:
        older = make_book("book_old", source_book_id="1", updated_at=NOW)
        newer = make_book(
            "book_new", source_book_id="2", updated_at=datetime(2026, 6, 1, tzinfo=UTC)
        )
        await books.save(older)
        await books.save(newer)
        listed = await books.list_all()
        assert [b.id for b in listed] == ["book_new", "book_old"]

    async def test_list_all_pagination(self, books: SqliteBookRepository) -> None:
        for i in range(5):
            await books.save(make_book(f"book_{i}", source_book_id=str(i)))
        assert len(await books.list_all(limit=2)) == 2
        assert len(await books.list_all(limit=2, offset=4)) == 1

    async def test_delete(self, books: SqliteBookRepository) -> None:
        await books.save(make_book())
        assert await books.delete("book_1") is True
        assert await books.delete("book_1") is False
        assert await books.get("book_1") is None

    async def test_save_many(self, books: SqliteBookRepository) -> None:
        await books.save_many([make_book(f"book_{i}", source_book_id=str(i)) for i in range(3)])
        assert await books.count() == 3

    async def test_unique_identity_constraint(self, books: SqliteBookRepository) -> None:
        """同一 (source_id, source_book_id) 不能有两行。"""
        await books.save(make_book("book_1"))
        with pytest.raises(IntegrityError):
            await books.save(make_book("book_2"))


class TestChapterRepository:
    async def test_save_and_get(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(make_chapter())
        loaded = await chapters.get("chap_1")
        assert loaded is not None
        assert loaded.title == "第一章"
        assert loaded.content == "正文内容"

    async def test_identity_key_persisted(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(make_chapter())
        loaded = await chapters.get("chap_1")
        assert loaded is not None
        # identity_key 由模型派生，落库后应能还原出同样的身份
        assert loaded.identity_key == "sid:c1"

    async def test_list_by_book_orders_by_index(self, chapters: SqliteChapterRepository) -> None:
        for i in (2, 0, 1):
            await chapters.save(make_chapter(f"chap_{i}", index=i, source_chapter_id=f"c{i}"))
        listed = await chapters.list_by_book("book_1")
        assert [c.index for c in listed] == [0, 1, 2]

    async def test_list_identities(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(make_chapter("chap_1", source_chapter_id="c1"))
        await chapters.save(make_chapter("chap_2", source_chapter_id="c2", content_hash="h2"))
        pairs = await chapters.list_identities("book_1")
        assert ("sid:c1", "abc123") in pairs
        assert ("sid:c2", "h2") in pairs

    async def test_save_many_single_transaction(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save_many(
            [make_chapter(f"chap_{i}", source_chapter_id=f"c{i}", index=i) for i in range(5)]
        )
        assert len(await chapters.list_by_book("book_1")) == 5

    async def test_delete_by_book(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save_many(
            [make_chapter(f"chap_{i}", source_chapter_id=f"c{i}") for i in range(3)]
        )
        assert await chapters.delete_by_book("book_1") == 3
        assert await chapters.list_by_book("book_1") == []

    async def test_unique_identity_per_book(self, chapters: SqliteChapterRepository) -> None:
        """同一本书内 identity_key 不能重复。"""
        await chapters.save(make_chapter("chap_1", source_chapter_id="c1"))
        with pytest.raises(IntegrityError):
            await chapters.save(make_chapter("chap_2", source_chapter_id="c1"))


class TestTaskRepository:
    def make_task(self, task_id: str = "task_1", **overrides) -> Task:
        data = {
            "id": task_id,
            "type": TaskType.DOWNLOAD_BOOK,
            "status": TaskStatus.PENDING,
            "created_at": NOW,
        }
        data.update(overrides)
        return Task(**data)

    async def test_save_and_get(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(self.make_task())
        loaded = await tasks.get("task_1")
        assert loaded is not None
        assert loaded.type is TaskType.DOWNLOAD_BOOK
        assert loaded.status is TaskStatus.PENDING

    async def test_update_existing(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(self.make_task())
        await tasks.save(self.make_task(status=TaskStatus.RUNNING, completed=5))
        loaded = await tasks.get("task_1")
        assert loaded is not None
        assert loaded.status is TaskStatus.RUNNING
        assert loaded.completed == 5

    async def test_list_by_status(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(self.make_task("task_a", status=TaskStatus.RUNNING))
        await tasks.save(self.make_task("task_b", status=TaskStatus.SUCCESS))
        running = await tasks.list_by_status(TaskStatus.RUNNING)
        assert [t.id for t in running] == ["task_a"]

    async def test_list_all_with_filter(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(self.make_task("task_a", status=TaskStatus.FAILED))
        assert len(await tasks.list_all()) == 1
        assert len(await tasks.list_all(status=TaskStatus.PENDING)) == 0

    async def test_task_items_roundtrip(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(self.make_task())
        item = TaskItem(
            id="item_1",
            task_id="task_1",
            chapter_index=0,
            title="第一章",
            status=TaskItemStatus.SUCCESS,
            attempts=2,
            created_at=NOW,
            updated_at=NOW,
        )
        await tasks.save_item(item)
        loaded = await tasks.list_items("task_1")
        assert len(loaded) == 1
        assert loaded[0].status is TaskItemStatus.SUCCESS
        assert loaded[0].attempts == 2

    async def test_error_fields_roundtrip(self, tasks: SqliteTaskRepository) -> None:
        await tasks.save(
            self.make_task(error_code="NETWORK_TIMEOUT", error_message="超时", retry_count=2)
        )
        loaded = await tasks.get("task_1")
        assert loaded is not None
        assert loaded.error_code == "NETWORK_TIMEOUT"
        assert loaded.retry_count == 2


class TestSettingsRepository:
    async def test_get_missing_returns_none(self, settings: SqliteSettingsRepository) -> None:
        assert await settings.get("nope") is None

    async def test_set_and_get(self, settings: SqliteSettingsRepository) -> None:
        await settings.set("theme", "dark")
        assert await settings.get("theme") == "dark"

    async def test_set_overwrites(self, settings: SqliteSettingsRepository) -> None:
        await settings.set("theme", "dark")
        await settings.set("theme", "light")
        assert await settings.get("theme") == "light"

    async def test_all(self, settings: SqliteSettingsRepository) -> None:
        await settings.set("a", "1")
        await settings.set("b", "2")
        assert await settings.all() == {"a": "1", "b": "2"}


class TestTransaction:
    async def test_commit_on_success(self, db: Database, books: SqliteBookRepository) -> None:
        async with db.transaction() as session:
            session.add(
                BookRow(
                    id="x",
                    source_id=SOURCE_ID,
                    source_book_id="1",
                    title="t",
                    created_at=NOW.isoformat(),
                    updated_at=NOW.isoformat(),
                )
            )
        assert await books.get("x") is not None

    async def test_rollback_on_error(self, db: Database, books: SqliteBookRepository) -> None:
        with pytest.raises(RuntimeError):
            async with db.transaction() as session:
                session.add(
                    BookRow(
                        id="y",
                        source_id=SOURCE_ID,
                        source_book_id="2",
                        title="t",
                        created_at=NOW.isoformat(),
                        updated_at=NOW.isoformat(),
                    )
                )
                raise RuntimeError("模拟失败")
        assert await books.get("y") is None


class TestChapterContentSearch:
    """本地全文搜索（纯本地，不访问网络）。

    用 ``LIKE`` 做字面子串匹配。**关键词里的 ``%`` 和 ``_`` 必须转义** ——
    否则搜「100%」会退化成「100 开头且后面任意」，搜「a_b」会连「axb」一起命中。
    """

    @staticmethod
    def _chapter(idx: int, content: str, book_id: str = "book_1") -> Chapter:
        """造一章。身份字段必须逐章不同 ——
        ``(book_id, identity_key)`` 上有唯一约束，用默认值会让多章撞在一起。
        """
        return make_chapter(
            f"chap_{idx}",
            book_id,
            source_chapter_id=f"c{idx}",
            url=f"https://example.com/{idx}",
            index=idx,
            content=content,
        )

    async def test_命中并给出片段(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(self._chapter(1, "李善德接到一个差事，要把鲜荔枝从岭南运到长安。"))

        hits = await chapters.search_content("荔枝")

        assert len(hits) == 1
        assert hits[0].book_title == "三体"  # 书名是 join 出来的
        assert hits[0].chapter_title == "第一章"
        assert "荔枝" in hits[0].snippet

    async def test_只返回片段不返回全文(self, chapters: SqliteChapterRepository) -> None:
        """一本几千章的书，搜一次就把几十兆正文读进内存是不可接受的。"""
        long_text = "前缀" * 500 + "目标词" + "后缀" * 500
        await chapters.save(self._chapter(1, long_text))

        hits = await chapters.search_content("目标词")

        assert len(hits[0].snippet) < 200
        assert "目标词" in hits[0].snippet

    async def test_未命中返回空(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(self._chapter(1, "正文内容"))

        assert await chapters.search_content("不存在的词") == []

    async def test_百分号不被当通配符(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(self._chapter(1, "进度百分之百，100% 完成"))
        await chapters.save(self._chapter(2, "100 个苹果"))

        hits = await chapters.search_content("100%")

        assert len(hits) == 1
        assert "100%" in hits[0].snippet

    async def test_下划线不被当通配符(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(self._chapter(1, "字段名是 a_b"))
        await chapters.save(self._chapter(2, "字段名是 axb"))

        hits = await chapters.search_content("a_b")

        assert len(hits) == 1
        assert "a_b" in hits[0].snippet

    async def test_限定书籍(self, chapters: SqliteChapterRepository, db: Database) -> None:
        await SqliteBookRepository(db).save(make_book(book_id="book_2", source_book_id="2002"))
        await chapters.save(self._chapter(1, "这里有荔枝"))
        await chapters.save(self._chapter(2, "这里也有荔枝", book_id="book_2"))

        assert len(await chapters.search_content("荔枝")) == 2
        only = await chapters.search_content("荔枝", book_id="book_2")
        assert [h.book_id for h in only] == ["book_2"]

    async def test_空关键词返回空(self, chapters: SqliteChapterRepository) -> None:
        """空串会让 LIKE '%%' 命中一切，必须挡住。"""
        await chapters.save(self._chapter(1, "正文内容"))

        assert await chapters.search_content("") == []

    async def test_尊重_limit(self, chapters: SqliteChapterRepository) -> None:
        for i in range(5):
            await chapters.save(self._chapter(i, f"第{i}章 有荔枝"))

        assert len(await chapters.search_content("荔枝", limit=2)) == 2

    async def test_按书与章节序号排序(self, chapters: SqliteChapterRepository) -> None:
        await chapters.save(self._chapter(2, "荔枝"))
        await chapters.save(self._chapter(1, "荔枝"))

        hits = await chapters.search_content("荔枝")

        assert [h.chapter_index for h in hits] == [1, 2]
