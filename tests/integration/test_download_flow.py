# SPDX-License-Identifier: GPL-3.0-only
"""端到端下载流程测试（离线）。

这个测试把真实组件串起来跑一遍：真实的书源引擎、真实的 SQLite 仓储、
真实的内容管线、真实的导出器，只有网络那一层换成 fixture HTML。

它对应 v0.1.0 的验收标准 —— 「能完整下载一本小说」：
搜索结果给的 URL → 登记书籍 → 抓目录 → 抓正文 → 清洗校验 → 落库 → 导出。

跑通了说明各层接口对得上；哪一层改了签名，这里会先红。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mograb.content.pipeline import ContentPipeline
from mograb.domain.enums import SourceCapability
from mograb.export.txt import TxtExporter
from mograb.source.engine import SourceEngine
from mograb.source.loader import load_source_file
from mograb.storage import (
    Database,
    SqliteBookRepository,
    SqliteChapterRepository,
    SqliteSourceRepository,
)
from mograb.task.scheduler import DownloadScheduler

pytestmark = pytest.mark.integration

BOOK_URL = "https://example.com/book/1001"


class FixtureFetcher:
    """按 URL 返回 fixture HTML，不发真实请求。

    匹配有优先级：``/chapter/`` 要排在 ``/book/1001`` 前面，
    否则章节页会被书的详情页抢走。
    """

    def __init__(self, fixtures_dir: Path) -> None:
        self._dir = fixtures_dir
        self.calls: list[str] = []

    async def fetch(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)

        if "/chapter/" in url:
            name = "chapter.html"
        elif url.endswith("/search"):
            name = "search.html"
        elif "/book/" in url:
            name = "book.html"
        else:
            raise AssertionError(f"没为这个 URL 准备 fixture: {url}")

        return _Response((self._dir / name).read_bytes(), url)


class _Response:
    def __init__(self, content: bytes, url: str) -> None:
        self.content = content
        self.encoding = "utf-8"
        self.status_code = 200
        self.url = url


@pytest.fixture
async def wired(tmp_path: Path, example_source_dir: Path):
    """把一整套真实组件接起来。"""
    database = Database(tmp_path / "mograb.db")
    await database.init_schema()

    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()

    sources = SqliteSourceRepository(database, sources_dir)
    books = SqliteBookRepository(database)
    chapters = SqliteChapterRepository(database)

    spec = load_source_file(example_source_dir / "source.yaml")
    await sources.save(spec)

    fetcher = FixtureFetcher(example_source_dir / "fixtures")
    scheduler = DownloadScheduler(
        engine=SourceEngine(fetcher),
        sources=sources,
        books=books,
        chapters=chapters,
        pipeline=ContentPipeline(),
    )

    yield scheduler, sources, books, chapters, fetcher, tmp_path
    await database.dispose()


class TestFullDownload:
    async def test_book_is_registered_from_url(self, wired) -> None:
        scheduler, _, books, _, _, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)

        assert book.title == "三体"
        assert book.author == "刘慈欣"
        assert book.source_book_id == "1001"
        assert book.url == BOOK_URL
        assert await books.get(book.id) is not None

    async def test_downloads_whole_book(self, wired) -> None:
        """核心验收：一本书从头下到尾。"""
        scheduler, _, books, chapters, _, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)
        report = await scheduler.run(book.id)

        assert report.downloaded == 3
        assert report.failed == 0
        assert report.ok is True

        saved = await chapters.list_by_book(book.id)
        assert [c.title for c in saved] == [
            "第一章 科学边界",
            "第二章 台球",
            "第三章 射手和农场主",
        ]
        assert [c.index for c in saved] == [0, 1, 2]

        # 正文经过清洗：script 和广告都被去掉了
        first = saved[0]
        assert first.content is not None
        assert "汪淼" in first.content
        assert "console.log" not in first.content
        assert "请记住本站" not in first.content
        assert first.content_hash is not None

        # 书籍统计在落库后刷新过
        refreshed = await books.get(book.id)
        assert refreshed is not None
        assert refreshed.chapter_count == 3
        assert refreshed.word_count > 0
        assert refreshed.latest_chapter == "第三章 射手和农场主"

    async def test_second_run_is_noop(self, wired) -> None:
        """再跑一次不该重复下载。"""
        scheduler, _, _, chapters, fetcher, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)
        await scheduler.run(book.id)

        content_calls_before = [u for u in fetcher.calls if "/chapter/" in u]
        report = await scheduler.run(book.id)

        assert report.is_noop is True
        assert report.downloaded == 0
        # 一次正文请求都没发
        assert [u for u in fetcher.calls if "/chapter/" in u] == content_calls_before
        assert len(await chapters.list_by_book(book.id)) == 3

    async def test_plan_then_run_agree(self, wired) -> None:
        """先 --dry-run 看一眼，再真跑，两者要对得上。"""
        scheduler, _, _, _, fetcher, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)
        calls_after_plan = len(fetcher.calls)

        plan = await scheduler.plan_update(book.id)
        assert len(plan.to_download) == 3
        assert plan.is_noop is False

        report = await scheduler.run(book.id)
        assert report.downloaded == len(plan.to_download)
        assert calls_after_plan > 0  # 计划阶段确实抓了目录

    async def test_incremental_update_picks_up_new_chapters(self, wired) -> None:
        """远程多出两章时，只下这两章。"""
        scheduler, _, _, chapters, _, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)
        await scheduler.run(book.id)

        # 模拟站点更新：往远程目录里追加两章
        from mograb.source.engine import ChapterDraft

        original = scheduler._engine
        base_drafts = await original.fetch_chapters(
            (await scheduler._sources.get("example")).spec,
            book.url,
        )
        extra = [
            ChapterDraft(
                title="第四章 三体游戏",
                url=f"https://example.com/book/1001/chapter/{i}",
                index=i - 1,
                source_chapter_id=f"c{i}",
            )
            for i in (4, 5)
        ]

        class ExtendedEngine:
            def __init__(self, inner, drafts):
                self._inner = inner
                self._drafts = drafts

            async def fetch_chapters(self, source, book_url):
                return list(self._drafts)

            async def fetch_content(self, source, url, *, chapter_index=None):
                return await self._inner.fetch_content(source, url, chapter_index=chapter_index)

            async def fetch_book(self, source, book_url):
                return await self._inner.fetch_book(source, book_url)

        scheduler._engine = ExtendedEngine(original, [*base_drafts, *extra])

        plan = await scheduler.plan_update(book.id)
        assert [d.index for d in plan.to_download] == [3, 4]

        report = await scheduler.run(book.id)
        assert report.downloaded == 2
        assert len(await chapters.list_by_book(book.id)) == 5


class TestExportAfterDownload:
    async def test_txt_export_contains_chapters(self, wired) -> None:
        scheduler, _, _, _, _, tmp_path = wired
        scheduler._exporter = TxtExporter()

        book = await scheduler.ensure_book("example", BOOK_URL)
        target = tmp_path / "三体.txt"
        report = await scheduler.run(book.id, export_to=target)

        assert report.export_path == target
        assert target.is_file()

        text = target.read_text(encoding="utf-8")
        assert "三体" in text
        assert "第一章 科学边界" in text
        assert "第三章 射手和农场主" in text


class TestSourceCapabilityGuard:
    async def test_source_without_chapters_capability_fails(self, wired) -> None:
        """书源缺 chapters 能力时，抓目录要报错而不是静默返回空。"""
        scheduler, sources, _, _, _, _ = wired

        book = await scheduler.ensure_book("example", BOOK_URL)
        entry = await sources.get("example")
        assert entry is not None
        assert entry.spec.supports(SourceCapability.CHAPTERS)

        stripped = entry.spec.model_copy(
            update={
                "capabilities": [c for c in entry.spec.capabilities if c.value != "chapters"],
                "chapters": None,
            }
        )
        await sources.save(stripped)

        from mograb.errors import SourceUnsupportedError

        with pytest.raises(SourceUnsupportedError):
            await scheduler.plan_update(book.id)
