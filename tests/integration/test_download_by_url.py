# SPDX-License-Identifier: GPL-3.0-only
"""任务创建的集成测试（离线）。

桌面端从搜索结果直接点下载时，手上只有一个详情页 URL，没有 ``book_id``。
这条路径走的是 ``source_id`` + ``params["url"]``，由
:meth:`~mograb.app.Application._resolve_download_target` 先把书登记进库再下。

顺带盯住任务创建的校验：``tasks.book_id`` 上有外键，不存在的 id 会让插入
直接抛 ``IntegrityError``。:meth:`~mograb.app.Application.create_task` 先查一遍，
把它换成带实体名的领域错误 —— 否则 API 那边是 500，不是 404。

测试从 :func:`~mograb.app.create_application` 装配出真实应用，
只把 HTTP 客户端换成 fixture 抓取器 —— 仓储、管线、调度器、任务状态机
都是真的。CLI 的 ``mog download <url>`` 也走这条路。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from mograb.app import Application, create_application
from mograb.domain.enums import ExportStatus, TaskStatus, TaskType
from mograb.errors import EntityNotFoundError, SourceNotFoundError, TaskParameterError
from mograb.source.engine import SourceEngine
from mograb.source.loader import load_source_file

pytestmark = pytest.mark.integration

BOOK_URL = "https://example.com/book/1001"


@pytest.fixture
async def app(example_source_dir, fixture_fetcher) -> AsyncIterator[Application]:
    """装配好的应用，网络层换成 fixture。"""
    async with create_application() as application:
        spec = load_source_file(example_source_dir / "source.yaml")
        await application.sources.save(spec)
        application.scheduler._engine = SourceEngine(fixture_fetcher)
        yield application


class TestDownloadByUrl:
    async def test_registers_book_then_downloads(self, app: Application) -> None:
        """只给 source_id + url，书会被登记，任务完成后 book_id 有值。"""
        task = await app.run_task(
            TaskType.DOWNLOAD_BOOK,
            source_id="example",
            params={"url": BOOK_URL},
        )

        assert task.status is TaskStatus.SUCCESS
        assert task.book_id is not None, "任务完成后要把 book_id 记回去"

        book = await app.books.get(task.book_id)
        assert book is not None
        assert book.title == "三体"
        assert book.source_book_id == "1001"

        chapters = await app.chapters.list_by_book(book.id)
        assert [c.index for c in chapters] == [0, 1, 2]
        assert task.completed == 3

    async def test_task_is_persisted_with_book_id(self, app: Application) -> None:
        """book_id 要落库 —— 前端刷新后靠它跳到书籍详情页。"""
        task = await app.run_task(
            TaskType.DOWNLOAD_BOOK,
            source_id="example",
            params={"url": BOOK_URL},
        )

        stored = await app.tasks.get(task.id)
        assert stored is not None
        assert stored.book_id == task.book_id

    async def test_same_url_twice_reuses_book(self, app: Application) -> None:
        """同一个 URL 提交两次不该产生两条书籍记录。"""
        first = await app.run_task(
            TaskType.DOWNLOAD_BOOK,
            source_id="example",
            params={"url": BOOK_URL},
        )
        second = await app.run_task(
            TaskType.DOWNLOAD_BOOK,
            source_id="example",
            params={"url": BOOK_URL},
        )

        assert first.book_id == second.book_id
        listed = await app.books.list_all()
        assert len(listed) == 1

    async def test_book_id_path_still_works(self, app: Application) -> None:
        """老路径（CLI 的 ``mog download <book-id>``）不受影响。"""
        book = await app.scheduler.ensure_book("example", BOOK_URL)

        task = await app.run_task(TaskType.DOWNLOAD_BOOK, book_id=book.id)

        assert task.status is TaskStatus.SUCCESS
        assert task.book_id == book.id


class TestMissingTarget:
    """定不出目标时，任务根本不该建出来 —— 在建的这一步就报错。"""

    async def test_no_target_is_rejected(self, app: Application) -> None:
        with pytest.raises(TaskParameterError) as excinfo:
            await app.run_task(TaskType.DOWNLOAD_BOOK, source_id="example")

        message = str(excinfo.value)
        assert "book_id" in message
        assert "url" in message

    async def test_url_without_source_is_rejected(self, app: Application) -> None:
        with pytest.raises(TaskParameterError):
            await app.run_task(TaskType.DOWNLOAD_BOOK, params={"url": BOOK_URL})

    async def test_unknown_book_is_rejected(self, app: Application) -> None:
        with pytest.raises(EntityNotFoundError):
            await app.run_task(TaskType.DOWNLOAD_BOOK, book_id="book_nope")

    async def test_unknown_source_is_rejected(self, app: Application) -> None:
        with pytest.raises(SourceNotFoundError):
            await app.run_task(
                TaskType.DOWNLOAD_BOOK,
                source_id="not-installed",
                params={"url": BOOK_URL},
            )

    async def test_nothing_is_persisted_on_rejection(self, app: Application) -> None:
        """建任务失败不该留下半条记录。"""
        with pytest.raises(TaskParameterError):
            await app.run_task(TaskType.DOWNLOAD_BOOK, source_id="example")

        assert await app.tasks.list_all() == []


class TestExportTask:
    """导出是四个 handler 之一，走的是同一套装配。"""

    @pytest.fixture
    async def downloaded(self, app: Application) -> str:
        task = await app.run_task(
            TaskType.DOWNLOAD_BOOK,
            source_id="example",
            params={"url": BOOK_URL},
        )
        assert task.book_id is not None
        return task.book_id

    async def test_export_to_explicit_path(
        self, app: Application, downloaded: str, tmp_path
    ) -> None:
        target = tmp_path / "三体.txt"

        task = await app.run_task(
            TaskType.EXPORT_BOOK,
            book_id=downloaded,
            params={"format": "txt", "target": str(target)},
        )

        assert task.status is TaskStatus.SUCCESS, task.error_message
        assert target.is_file()
        assert "第一章 科学边界" in target.read_text(encoding="utf-8")

        # 导出记录要落库，界面上靠它显示历史
        record = await app.exports.get(str(task.params["export_id"]))
        assert record is not None
        assert record.status is ExportStatus.SUCCESS
        assert record.path == str(target)

    async def test_export_without_target_uses_data_dir(
        self, app: Application, downloaded: str
    ) -> None:
        """不给 target 就落到数据目录下的 exports/，不是 cwd。"""
        task = await app.run_task(TaskType.EXPORT_BOOK, book_id=downloaded)

        assert task.status is TaskStatus.SUCCESS, task.error_message
        path = Path(str(task.params["path"]))
        assert path.is_file()
        assert path.parent == app.paths.root / "exports"

    @pytest.mark.parametrize(
        ("fmt", "suffix"),
        [("txt", ".txt"), ("markdown", ".markdown"), ("epub", ".epub")],
    )
    async def test_文件扩展名跟着实际导出格式(
        self, app: Application, downloaded: str, fmt: str, suffix: str
    ) -> None:
        """**扩展名必须跟实际格式一致。**

        踩过一次：``resolve_export_target`` 拿配置里的默认格式（epub）拼扩展名，
        而不是本次实际用的格式。于是 ``--format txt`` 产出一个内容是纯文本、
        名字却叫 ``.epub`` 的文件 —— 内容没错，但名字骗人，
        而且不报错。只有「指定格式但不指定路径」这个组合会触发。
        """
        task = await app.run_task(TaskType.EXPORT_BOOK, book_id=downloaded, params={"format": fmt})

        assert task.status is TaskStatus.SUCCESS, task.error_message
        path = Path(str(task.params["path"]))
        assert path.suffix == suffix, f"导出 {fmt} 却得到 {path.name}"

        # 内容也要对得上：epub 是 ZIP，其余是纯文本
        raw = path.read_bytes()
        assert raw.startswith(b"PK") if fmt == "epub" else not raw.startswith(b"PK")

    async def test_export_missing_book_is_rejected(self, app: Application) -> None:
        with pytest.raises(EntityNotFoundError):
            await app.run_task(TaskType.EXPORT_BOOK, book_id="book_nope")

    async def test_export_without_book_id_is_rejected(self, app: Application) -> None:
        with pytest.raises(TaskParameterError):
            await app.run_task(TaskType.EXPORT_BOOK)
