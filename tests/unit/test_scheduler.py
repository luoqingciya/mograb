# SPDX-License-Identifier: GPL-3.0-only
"""下载调度器测试。

用假实现替换引擎和仓储，重点覆盖编排逻辑本身：
增量 diff 怎么变成下载计划、失败章节怎么处理、落库和统计的先后顺序。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mograb.content.pipeline import ContentPipeline
from mograb.domain.book import Book
from mograb.domain.chapter import Chapter
from mograb.domain.enums import BookStatus, HealthStatus
from mograb.domain.source import InstalledSource, SourceSpec
from mograb.errors import (
    ContentValidationError,
    EntityNotFoundError,
    SourceExecutionError,
    SourceNotFoundError,
    SourceUnsupportedError,
)
from mograb.source.engine import BookDraft, ChapterDraft
from mograb.task.scheduler import DownloadScheduler

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
BOOK_URL = "https://demo.example.com/book/1"
# 每章正文都够长，能过内容校验
LONG_TEXT = "这是一段足够长的正文内容，用来通过内容校验。" * 4


def make_spec(source_id: str = "demo", *, concurrency: int = 2) -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "spec_version": 1,
            "id": source_id,
            "name": f"Demo {source_id}",
            "version": "1.0.0",
            "capabilities": ["book", "chapters", "content"],
            "network": {"concurrency": concurrency},
            "book": {
                "request": {"method": "GET", "url": "{{book.url}}"},
                "fields": {"title": "h1"},
            },
            "chapters": {
                "request": {"method": "GET", "url": "{{book.url}}"},
                "result": {"list": ".ch a", "fields": {"title": "@text", "url": "@href"}},
            },
            "content": {
                "request": {"method": "GET", "url": "{{chapter.url}}"},
                "body": "#content",
            },
        }
    )


def make_drafts(count: int, *, start: int = 1) -> list[ChapterDraft]:
    return [
        ChapterDraft(
            title=f"第{i}章",
            url=f"https://demo.example.com/book/1/{i}",
            index=i - 1,
            source_chapter_id=f"c{i}",
        )
        for i in range(start, start + count)
    ]


# ---------------------------------------------------------------------------
# 假实现
# ---------------------------------------------------------------------------
class FakeEngine:
    def __init__(
        self,
        *,
        drafts: list[ChapterDraft] | None = None,
        contents: dict[str, str] | None = None,
        fail_urls: set[str] | None = None,
        book_status: BookStatus = BookStatus.UNKNOWN,
        book_extra: dict[str, str | None] | None = None,
    ) -> None:
        self.drafts = drafts if drafts is not None else make_drafts(3)
        self.contents = contents or {}
        self.fail_urls = fail_urls or set()
        self.book_status = book_status
        self.book_extra = book_extra or {}
        self.book_calls = 0
        self.chapter_calls = 0
        self.content_calls: list[str] = []

    async def fetch_book(self, source: SourceSpec, book_url: str) -> BookDraft:
        self.book_calls += 1
        return BookDraft(
            source_id=source.id,
            source_book_id="1",
            url=book_url,
            title="测试书",
            author="作者",
            status=self.book_status,
            extra=dict(self.book_extra),
        )

    async def fetch_chapters(self, source: SourceSpec, book_url: str) -> list[ChapterDraft]:
        self.chapter_calls += 1
        return list(self.drafts)

    async def fetch_content(
        self, source: SourceSpec, chapter_url: str, *, chapter_index: int | None = None
    ) -> str:
        self.content_calls.append(chapter_url)
        if chapter_url in self.fail_urls:
            raise SourceExecutionError("抓不到正文", details={"url": chapter_url})
        return self.contents.get(chapter_url, LONG_TEXT)


class FakeSourceRepository:
    def __init__(self, entries: dict[str, InstalledSource] | None = None) -> None:
        self.entries = entries or {}

    async def get(self, source_id: str) -> InstalledSource | None:
        return self.entries.get(source_id)


class FakeBookRepository:
    def __init__(self, books: dict[str, Book] | None = None) -> None:
        self.books = books or {}
        self.saves = 0

    async def get(self, book_id: str) -> Book | None:
        return self.books.get(book_id)

    async def get_by_identity(self, source_id: str, source_book_id: str) -> Book | None:
        for book in self.books.values():
            if book.source_id == source_id and book.source_book_id == source_book_id:
                return book
        return None

    async def save(self, book: Book) -> None:
        self.saves += 1
        self.books[book.id] = book


class FakeChapterRepository:
    def __init__(self, chapters: list[Chapter] | None = None) -> None:
        self.chapters = {c.id: c for c in (chapters or [])}
        self.save_many_calls = 0

    async def list_by_book(self, book_id: str) -> list[Chapter]:
        found = [c for c in self.chapters.values() if c.book_id == book_id]
        return sorted(found, key=lambda c: c.index)

    async def save_many(self, chapters: list[Chapter]) -> None:
        self.save_many_calls += 1
        for chapter in chapters:
            self.chapters[chapter.id] = chapter

    async def stats_by_book(self, book_id: str) -> tuple[int, int]:
        found = [c for c in self.chapters.values() if c.book_id == book_id]
        return len(found), sum(c.word_count for c in found)


class FakeExporter:
    format = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Path]] = []

    async def export(self, book: Book, chapters: list[Chapter], target: Path):
        from mograb.export.base import ExportResult

        self.calls.append((book.id, len(chapters), target))
        return ExportResult(
            book_id=book.id,
            format=None,  # type: ignore[arg-type]
            path=target,
            size_bytes=1,
            chapter_count=len(chapters),
        )


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def make_book(book_id: str = "book_1", **overrides) -> Book:
    data = {
        "id": book_id,
        "source_id": "demo",
        "source_book_id": "1",
        "url": BOOK_URL,
        "title": "测试书",
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return Book(**data)


def make_source(**overrides) -> InstalledSource:
    data = {
        "spec": make_spec(),
        "enabled": True,
        "health": HealthStatus.HEALTHY,
        "installed_version": "1.0.0",
    }
    data.update(overrides)
    return InstalledSource(**data)


def make_scheduler(
    *,
    engine: FakeEngine | None = None,
    sources: FakeSourceRepository | None = None,
    books: FakeBookRepository | None = None,
    chapters: FakeChapterRepository | None = None,
    pipeline: ContentPipeline | None = None,
    exporter: FakeExporter | None = None,
) -> tuple[
    DownloadScheduler, FakeEngine, FakeSourceRepository, FakeBookRepository, FakeChapterRepository
]:
    eng = engine or FakeEngine()
    src = sources or FakeSourceRepository({"demo": make_source()})
    bks = books or FakeBookRepository({"book_1": make_book()})
    chs = chapters or FakeChapterRepository()
    scheduler = DownloadScheduler(
        engine=eng,  # type: ignore[arg-type]
        sources=src,  # type: ignore[arg-type]
        books=bks,  # type: ignore[arg-type]
        chapters=chs,  # type: ignore[arg-type]
        pipeline=pipeline,
        exporter=exporter,  # type: ignore[arg-type]
    )
    return scheduler, eng, src, bks, chs


# ---------------------------------------------------------------------------
# ensure_book
# ---------------------------------------------------------------------------
class TestEnsureBook:
    async def test_creates_new_book(self) -> None:
        scheduler, _, _, books, _ = make_scheduler(books=FakeBookRepository())

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.title == "测试书"
        assert book.url == BOOK_URL
        assert book.source_book_id == "1"
        assert book.id.startswith("book_")
        assert books.saves == 1

    async def test_existing_book_is_refreshed_not_duplicated(self) -> None:
        existing = make_book(title="旧标题")
        scheduler, _, _, books, _ = make_scheduler(books=FakeBookRepository({"book_1": existing}))

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.id == "book_1"  # 没新建
        assert book.title == "测试书"  # 元数据刷新了
        assert len(books.books) == 1

    async def test_missing_source_raises(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(sources=FakeSourceRepository())
        with pytest.raises(SourceNotFoundError):
            await scheduler.ensure_book("demo", BOOK_URL)


class TestBookDraftReachesDomain:
    """书源提取到的状态和自定义字段必须真的落到 ``Book`` 上。

    这三条链路以前都是断的：``BookStatus`` 枚举的文档写着「由书源尽力解析」，
    但 ``BookDraft`` 里没有 ``status``；``draft.extra`` 引擎收集了却全仓库
    没人消费。结果是书源写什么都白写 —— 声明了没接线。
    """

    async def test_status_落到新书(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(
            books=FakeBookRepository(),
            engine=FakeEngine(book_status=BookStatus.COMPLETED),
        )

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.status is BookStatus.COMPLETED

    async def test_status_刷新已有书(self) -> None:
        """上次是连载中，这次书源说完结了，要更新过来。"""
        existing = make_book(status=BookStatus.ONGOING)
        scheduler, _, _, _, _ = make_scheduler(
            books=FakeBookRepository({"book_1": existing}),
            engine=FakeEngine(book_status=BookStatus.COMPLETED),
        )

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.status is BookStatus.COMPLETED

    async def test_未提供时保持_UNKNOWN(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(books=FakeBookRepository())

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.status is BookStatus.UNKNOWN

    async def test_extra_落到_metadata(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(
            books=FakeBookRepository(),
            engine=FakeEngine(book_extra={"category": "玄幻奇幻"}),
        )

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.metadata == {"category": "玄幻奇幻"}

    async def test_刷新时保留已有_metadata_键(self) -> None:
        """书源没提供的键不该被刷新抹掉。"""
        existing = make_book(metadata={"用户备注": "想读", "category": "旧分类"})
        scheduler, _, _, _, _ = make_scheduler(
            books=FakeBookRepository({"book_1": existing}),
            engine=FakeEngine(book_extra={"category": "玄幻奇幻"}),
        )

        book = await scheduler.ensure_book("demo", BOOK_URL)

        assert book.metadata["用户备注"] == "想读"  # 保留
        assert book.metadata["category"] == "玄幻奇幻"  # 书源覆盖


# ---------------------------------------------------------------------------
# plan_update
# ---------------------------------------------------------------------------
class TestPlanUpdate:
    async def test_all_new_when_local_empty(self) -> None:
        scheduler, _, _, _, _ = make_scheduler()

        plan = await scheduler.plan_update("book_1")

        assert len(plan.to_download) == 3
        assert plan.skipped == 0
        assert plan.is_noop is False

    async def test_noop_when_up_to_date(self) -> None:
        drafts = make_drafts(3)
        local = [
            Chapter(
                id=f"chap_{d.index}",
                book_id="book_1",
                source_chapter_id=d.source_chapter_id,
                title=d.title,
                url=d.url,
                index=d.index,
                created_at=NOW,
                updated_at=NOW,
            )
            for d in drafts
        ]
        scheduler, _, _, _, _ = make_scheduler(
            engine=FakeEngine(drafts=drafts), chapters=FakeChapterRepository(local)
        )

        plan = await scheduler.plan_update("book_1")

        assert plan.is_noop is True
        assert plan.skipped == 3

    async def test_only_new_chapters_are_planned(self) -> None:
        drafts = make_drafts(5)
        local = [
            Chapter(
                id=f"chap_{d.index}",
                book_id="book_1",
                source_chapter_id=d.source_chapter_id,
                title=d.title,
                url=d.url,
                index=d.index,
                created_at=NOW,
                updated_at=NOW,
            )
            for d in drafts[:3]
        ]
        scheduler, _, _, _, _ = make_scheduler(
            engine=FakeEngine(drafts=drafts), chapters=FakeChapterRepository(local)
        )

        plan = await scheduler.plan_update("book_1")

        assert [d.index for d in plan.to_download] == [3, 4]
        assert plan.latest_chapter == "第5章"

    async def test_missing_book_raises(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(books=FakeBookRepository())
        with pytest.raises(EntityNotFoundError):
            await scheduler.plan_update("nope")

    async def test_missing_source_raises(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(sources=FakeSourceRepository())
        with pytest.raises(SourceNotFoundError):
            await scheduler.plan_update("book_1")

    @pytest.mark.parametrize(
        ("enabled", "health"),
        [(False, HealthStatus.HEALTHY), (True, HealthStatus.BROKEN)],
    )
    async def test_unusable_source_raises(self, enabled: bool, health: HealthStatus) -> None:
        sources = FakeSourceRepository({"demo": make_source(enabled=enabled, health=health)})
        scheduler, _, _, _, _ = make_scheduler(sources=sources)

        with pytest.raises(SourceUnsupportedError):
            await scheduler.plan_update("book_1")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
class TestRun:
    async def test_downloads_and_persists(self) -> None:
        scheduler, engine, _, _, chapters = make_scheduler()

        report = await scheduler.run("book_1")

        assert report.downloaded == 3
        assert report.failed == 0
        assert report.ok is True
        assert len(engine.content_calls) == 3
        assert len(await chapters.list_by_book("book_1")) == 3

    async def test_noop_skips_network_and_db(self) -> None:
        drafts = make_drafts(2)
        local = [
            Chapter(
                id=f"chap_{d.index}",
                book_id="book_1",
                source_chapter_id=d.source_chapter_id,
                title=d.title,
                url=d.url,
                index=d.index,
                created_at=NOW,
                updated_at=NOW,
            )
            for d in drafts
        ]
        engine = FakeEngine(drafts=drafts)
        scheduler, _, _, books, chapters = make_scheduler(
            engine=engine, chapters=FakeChapterRepository(local)
        )
        books.saves = 0

        report = await scheduler.run("book_1")

        assert report.is_noop is True
        assert engine.content_calls == []
        assert chapters.save_many_calls == 0
        assert books.saves == 0

    async def test_partial_failure_keeps_successes(self) -> None:
        """单章失败不该让整本书白跑。"""
        drafts = make_drafts(3)
        engine = FakeEngine(drafts=drafts, fail_urls={drafts[1].url})
        scheduler, _, _, _, chapters = make_scheduler(engine=engine)

        report = await scheduler.run("book_1")

        assert report.downloaded == 2
        assert report.failed == 1
        assert report.ok is False
        assert report.failures[0].title == "第2章"
        assert report.failures[0].code == "SOURCE_EXECUTION_ERROR"
        assert len(await chapters.list_by_book("book_1")) == 2

    async def test_content_validation_failure_is_recorded(self) -> None:
        """正文校验不通过也算这一章失败，不是整本书失败。"""
        drafts = make_drafts(2)
        engine = FakeEngine(drafts=drafts, contents={drafts[0].url: "太短"})
        scheduler, _, _, _, _ = make_scheduler(engine=engine, pipeline=ContentPipeline())

        report = await scheduler.run("book_1")

        assert report.downloaded == 1
        assert report.failed == 1
        assert report.failures[0].code == ContentValidationError.code

    async def test_pipeline_cleans_content(self) -> None:
        drafts = make_drafts(1)
        dirty = (
            "汪淼觉得自己像一条被拎出水的鱼。\n"
            "他坐在办公桌前，面前摊着一份光盘。\n"
            "请记住本站：www.example.com\n"
            "电话铃响了，他拿起听筒。\n"
            "听见史强的声音从另一头传过来。"
        )
        engine = FakeEngine(drafts=drafts, contents={drafts[0].url: dirty})
        scheduler, _, _, _, chapters = make_scheduler(engine=engine, pipeline=ContentPipeline())

        await scheduler.run("book_1")

        saved = (await chapters.list_by_book("book_1"))[0]
        assert saved.content is not None
        assert "请记住本站" not in saved.content
        assert "汪淼" in saved.content
        assert saved.content_hash is not None
        assert saved.word_count > 0

    async def test_updates_book_stats(self) -> None:
        scheduler, _, _, books, _ = make_scheduler()

        await scheduler.run("book_1")

        book = books.books["book_1"]
        assert book.chapter_count == 3
        assert book.word_count > 0
        assert book.latest_chapter == "第3章"

    async def test_progress_callback_reports_monotonically(self) -> None:
        scheduler, _, _, _, _ = make_scheduler()
        seen: list[tuple[int, int]] = []

        async def on_progress(done: int, total: int) -> None:
            seen.append((done, total))

        await scheduler.run("book_1", on_progress=on_progress)

        assert len(seen) == 3
        assert [d for d, _ in seen] == [1, 2, 3]
        assert all(t == 3 for _, t in seen)

    async def test_concurrency_is_bounded(self) -> None:
        """并发度受书源 network.concurrency 约束。"""
        drafts = make_drafts(8)
        active = 0
        peak = 0

        class CountingEngine(FakeEngine):
            async def fetch_content(self, source, chapter_url, *, chapter_index=None):
                nonlocal active, peak
                active += 1
                peak = max(peak, active)
                try:
                    import asyncio

                    await asyncio.sleep(0.01)
                    return LONG_TEXT
                finally:
                    active -= 1

        scheduler, _, _, _, _ = make_scheduler(
            engine=CountingEngine(drafts=drafts),
            sources=FakeSourceRepository({"demo": make_source(spec=make_spec(concurrency=2))}),
        )

        await scheduler.run("book_1")

        assert peak <= 2

    async def test_export_when_target_given(self, tmp_path: Path) -> None:
        exporter = FakeExporter()
        scheduler, _, _, _, _ = make_scheduler(exporter=exporter)
        target = tmp_path / "out.epub"

        report = await scheduler.run("book_1", export_to=target)

        assert report.export_path == target
        assert exporter.calls == [("book_1", 3, target)]

    async def test_export_skipped_without_target(self) -> None:
        exporter = FakeExporter()
        scheduler, _, _, _, _ = make_scheduler(exporter=exporter)

        report = await scheduler.run("book_1")

        assert report.export_path is None
        assert exporter.calls == []

    async def test_missing_book_raises(self) -> None:
        scheduler, _, _, _, _ = make_scheduler(books=FakeBookRepository())
        with pytest.raises(EntityNotFoundError):
            await scheduler.run("nope")


class TestUnhandledException:
    async def test_unexpected_error_is_contained(self) -> None:
        """非 MoGrabError 的异常也要被收进 failures，不能中断整本书。"""

        class ExplodingEngine(FakeEngine):
            async def fetch_content(self, source, chapter_url, *, chapter_index=None):
                if chapter_url.endswith("/1"):
                    raise ValueError("意料之外")
                return LONG_TEXT

        scheduler, _, _, _, _ = make_scheduler(engine=ExplodingEngine(drafts=make_drafts(2)))

        report = await scheduler.run("book_1")

        assert report.failed == 1
        assert report.failures[0].code == "UNEXPECTED"
        assert report.downloaded == 1
