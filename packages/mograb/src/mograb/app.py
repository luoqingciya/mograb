# SPDX-License-Identifier: GPL-3.0-only
"""应用装配（composition root）。

CLI 和 API 要的是同一套东西：数据库、仓储、HTTP 客户端、书源引擎、内容管线、
下载调度器、任务管理器。这套装配只该有一份 —— 两边各接一遍迟早会走样，
而且改一个依赖要记得改两个地方。

所以集中在这里，:func:`create_application` 是唯一入口。

关于任务执行有两条路径，是有意分开的：

- **CLI 就地跑**（:meth:`Application.run_task`）：命令行进程跑完就退出，
  起 worker 池再等调度没有意义。任务记录照样写库，``mog task list`` 能看到历史。
- **API server 走队列**：长驻进程，worker 池 + 队列，支持暂停/继续/取消，
  SSE 推实时进度。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AppSettings, Paths, get_paths, load_settings
from .content.pipeline import ContentPipeline
from .domain.book import Book
from .domain.enums import ExportStatus, TaskType
from .domain.export import ExportRecord
from .domain.ids import new_id
from .domain.task import Task
from .errors import EntityNotFoundError, TaskError
from .export import get_exporter
from .export.base import render_filename
from .logging.setup import configure_logging, get_logger
from .network import GlobalLimiter, HttpClient, HttpClientConfig, SourceLimiterRegistry
from .network.retry import RetryPolicy
from .source.engine import SourceEngine
from .source.request import BUILTIN_VARS
from .storage import (
    Database,
    SqliteBookRepository,
    SqliteChapterRepository,
    SqliteExportRepository,
    SqliteHttpCache,
    SqliteSettingsRepository,
    SqliteSourceRepository,
    SqliteTaskRepository,
)
from .task.manager import TaskManager
from .task.runner import StatusCallback, TaskHandler, TaskRunner
from .task.scheduler import DownloadScheduler, ProgressCallback

_logger = get_logger(__name__)


@dataclass(slots=True)
class Application:
    """装配好的应用。

    字段都是具体实现而不是协议 —— 这是 composition root，本来就该知道
    用的是哪个实现。业务代码拿到的仍然是协议类型。
    """

    settings: AppSettings
    paths: Paths

    database: Database
    sources: SqliteSourceRepository
    books: SqliteBookRepository
    chapters: SqliteChapterRepository
    tasks: SqliteTaskRepository
    exports: SqliteExportRepository
    cache: SqliteHttpCache
    preferences: SqliteSettingsRepository

    http: HttpClient
    engine: SourceEngine
    pipeline: ContentPipeline
    scheduler: DownloadScheduler

    # TaskManager 的 handlers 来自本类的方法，构造顺序上有个环，
    # 所以先留空，装配完再补上（见 create_application）
    task_manager: TaskManager = field(init=False)

    # 命令行显示进度用。只对 run_task 生效，见那里的说明。
    _progress_hook: ProgressCallback | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        """关掉后台 worker 和连接。"""
        await self.task_manager.stop()
        await self.http.aclose()
        await self.database.dispose()

    # ------------------------------------------------------------------
    # 任务
    # ------------------------------------------------------------------
    def task_handlers(self) -> dict[str, TaskHandler]:
        """任务类型到处理函数的映射。

        下载和更新走同一个 handler —— ``scheduler.run()`` 本身就是增量的，
        已经是最新时会直接返回空计划，没必要分两套。
        """
        return {
            TaskType.DOWNLOAD_BOOK.value: self._handle_download,
            TaskType.UPDATE_BOOK.value: self._handle_download,
            TaskType.EXPORT_BOOK.value: self._handle_export,
            TaskType.REFRESH_SOURCE.value: self._handle_refresh_source,
        }

    async def run_task(
        self,
        task_type: TaskType,
        *,
        book_id: str | None = None,
        source_id: str | None = None,
        params: dict[str, Any] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> Task:
        """建任务、就地跑完、返回结果。CLI 用这个。

        状态机处理走的是和 WorkerPool 同一个 :class:`TaskRunner`，
        所以「部分章节失败算成功还是失败」这类判断不会两处不一致。

        ``on_progress`` 是给命令行显示进度用的。它存在实例上，所以**同一个
        Application 实例一次只能跑一个任务** —— 对 CLI 来说天然成立
        （一个进程一个命令）。API server 走的是 worker 池，不走这里。
        """
        self._progress_hook = on_progress
        try:
            task = await self.task_manager.create(
                task_type,
                book_id=book_id,
                source_id=source_id,
                params=params,
                enqueue=False,
            )
            runner = TaskRunner(self.task_handlers(), on_status_change=self._save_task)
            return await runner.run(task)
        finally:
            self._progress_hook = None

    async def _save_task(self, task: Task) -> None:
        await self.tasks.save(task)

    # ------------------------------------------------------------------
    # 处理函数
    # ------------------------------------------------------------------
    async def _handle_download(self, task: Task) -> None:
        if not task.book_id:
            raise TaskError("下载任务缺少 book_id", details={"task_id": task.id})

        report = await self.scheduler.run(
            task.book_id,
            on_progress=self._progress_hook or self._progress(task),
        )

        task.total = report.plan.total
        task.completed = report.downloaded
        task.failed = report.failed
        if report.plan.missing:
            task.params = {**task.params, "missing": report.plan.missing}

        # 全挂才算任务失败。部分失败记在 task.failed 里 ——
        # 一本书里有几章抓不到很常见，不该让整个任务标红。
        if report.downloaded == 0 and report.failed > 0:
            first = report.failures[0]
            raise TaskError(
                f"所有章节都下载失败：{first.message}",
                details={"code": first.code, "failed": report.failed},
            )

    async def _handle_export(self, task: Task) -> None:
        if not task.book_id:
            raise TaskError("导出任务缺少 book_id", details={"task_id": task.id})

        book = await self.books.get(task.book_id)
        if book is None:
            raise EntityNotFoundError(f"书籍不存在: {task.book_id}")

        fmt = str(task.params.get("format") or self.settings.output.format)
        exporter = get_exporter(fmt)
        target = self.resolve_export_target(book, task.params.get("target"))

        # API 那边会先建一条 PENDING 记录再把 id 塞进 params，
        # 这样调用方拿到 id 就能查状态。CLI 不给就现建一个。
        record = ExportRecord(
            id=str(task.params.get("export_id") or new_id("export")),
            book_id=book.id,
            format=exporter.format,
            status=ExportStatus.RUNNING,
            created_at=datetime.now(UTC),
        )
        await self.exports.save(record)

        try:
            chapters = await self.chapters.list_by_book(book.id)
            result = await exporter.export(book, chapters, target)
        except Exception as exc:
            await self.exports.save(
                record.model_copy(
                    update={
                        "status": ExportStatus.FAILED,
                        "error_message": str(exc),
                        "finished_at": datetime.now(UTC),
                    }
                )
            )
            raise

        await self.exports.save(
            record.model_copy(
                update={
                    "status": ExportStatus.SUCCESS,
                    "path": str(result.path),
                    "size_bytes": result.size_bytes,
                    "finished_at": datetime.now(UTC),
                }
            )
        )
        task.params = {**task.params, "export_id": record.id, "path": str(result.path)}
        task.total = 1
        task.completed = 1

    async def _handle_refresh_source(self, task: Task) -> None:
        entries = await self.sources.rescan()
        task.total = len(entries)
        task.completed = len(entries)

    def _progress(self, task: Task) -> ProgressCallback:
        """把调度器的进度回写到任务对象上。

        只改内存里的对象，不逐章写库 —— 一本三千章的书会有三千次写库，
        为了进度条不值当。API server 推 SSE 时读的是同一个对象。
        """

        async def on_progress(done: int, total: int) -> None:
            task.completed = done
            task.total = total

        return on_progress

    # ------------------------------------------------------------------
    # 路径
    # ------------------------------------------------------------------
    def resolve_export_target(self, book: Book, explicit: str | Path | None = None) -> Path:
        """算出导出目标路径。

        ``output.directory`` 是相对路径时，相对于**数据目录**而不是 cwd ——
        默认的 ``exports`` 就落在 ``<数据目录>/exports``，和 ``paths.exports_dir``
        是同一个地方。
        """
        if explicit:
            return Path(explicit).expanduser()

        configured = Path(self.settings.output.directory)
        directory = configured if configured.is_absolute() else self.paths.root / configured
        name = render_filename(self.settings.output.template, book=book)
        return directory / f"{name}.{self.settings.output.format}"


def build_task_manager(
    app: Application,
    *,
    worker_count: int | None = None,
    on_status_change: StatusCallback | None = None,
) -> TaskManager:
    """按应用配置建任务管理器。

    单独一个函数是因为 :class:`Application` 是 dataclass，TaskManager 需要
    拿到 handlers，而 handlers 又是 Application 的方法 —— 构造顺序上有个环，
    用工厂函数绕开。

    ``on_status_change`` 给 API server 用：把任务进度推给 SSE。
    """
    return TaskManager(
        app.tasks,
        app.task_handlers(),
        worker_count=worker_count or max(2, app.settings.download.concurrency),
        on_status_change=on_status_change,
    )


@asynccontextmanager
async def create_application(
    *,
    settings: AppSettings | None = None,
    paths: Paths | None = None,
    ensure_paths: bool = True,
    log_level: str | None = None,
) -> AsyncIterator[Application]:
    """装配出一个可用的应用，退出时自动清理。

    Args:
        settings: 不传就读配置文件 + 环境变量。
        paths: 不传就按运行目录解析。
        ensure_paths: 是否创建数据目录。只读命令可以传 False。
        log_level: 覆盖日志级别。CLI 默认要安静，会传 ``WARNING``；
            不传则用配置里的值。
    """
    resolved_settings = settings or load_settings()
    resolved_paths = paths or get_paths()

    if ensure_paths:
        resolved_paths.ensure()

    configure_logging(
        level=log_level or resolved_settings.logging.level,
        log_dir=resolved_paths.logs_dir,
        json_output=resolved_settings.logging.json_output,
    )

    database = Database(resolved_paths.database)
    await database.init_schema()

    sources = SqliteSourceRepository(database, resolved_paths.sources_dir)
    books = SqliteBookRepository(database)
    chapters = SqliteChapterRepository(database)
    tasks = SqliteTaskRepository(database)
    exports = SqliteExportRepository(database)
    preferences = SqliteSettingsRepository(database)

    cache = SqliteHttpCache(
        database,
        max_size_bytes=(
            resolved_settings.cache.max_size_bytes if resolved_settings.cache.enabled else 0
        ),
    )

    limiters = SourceLimiterRegistry(
        GlobalLimiter(concurrency=resolved_settings.download.concurrency),
        default_concurrency=resolved_settings.download.per_source_concurrency,
        default_min_interval=resolved_settings.download.request_interval_ms / 1000,
    )
    http = HttpClient(
        HttpClientConfig(
            timeout_ms=resolved_settings.download.timeout_ms,
            retry=RetryPolicy(max_retries=resolved_settings.download.retry),
            user_agent=BUILTIN_VARS["user_agent"],
        ),
        cache=cache if resolved_settings.cache.enabled else None,
        limiters=limiters,
    )
    await http.__aenter__()

    engine = SourceEngine(http)
    pipeline = ContentPipeline()
    scheduler = DownloadScheduler(
        engine=engine,
        sources=sources,
        books=books,
        chapters=chapters,
        pipeline=pipeline,
    )

    app = Application(
        settings=resolved_settings,
        paths=resolved_paths,
        database=database,
        sources=sources,
        books=books,
        chapters=chapters,
        tasks=tasks,
        exports=exports,
        cache=cache,
        preferences=preferences,
        http=http,
        engine=engine,
        pipeline=pipeline,
        scheduler=scheduler,
    )
    app.task_manager = build_task_manager(app)

    _logger.debug("app.ready", root=str(resolved_paths.root))
    try:
        yield app
    finally:
        await app.aclose()


__all__ = ["Application", "build_task_manager", "create_application"]
