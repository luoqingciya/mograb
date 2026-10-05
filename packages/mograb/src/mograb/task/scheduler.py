# SPDX-License-Identifier: GPL-3.0-only
"""下载调度与增量更新（规划书 §18、§20）。

模块里有两块东西：

1. :func:`compute_chapter_diff` —— **纯函数**的章节差异计算。
   这是增量更新的核心，可以完全离线测试（§47 明确要求覆盖 Chapter Identity）。

2. :class:`DownloadScheduler` —— 按 §18 的顺序编排一次完整下载::

       Load Book → Load Chapters → Determine Missing → Download
       → Clean → Validate → Persist → (Export)

关键一致性约束（§39）::

       Download → Validate → **Transaction** → Persist

只有落库成功之后才把章节算作下载成功，避免「下载成功但库里没有」。

关于依赖方向：调度器会 import :mod:`mograb.storage.repository` 里的仓储协议，
但不 import 任何具体实现。task 依赖 storage 的**接口**是合理的 ——
调度负责编排，持久化交给存储层。反方向没有依赖，不构成环。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ..content.normalizer import count_words
from ..content.pipeline import ContentPipeline
from ..domain.book import Book
from ..domain.chapter import Chapter, compute_content_hash, normalize_url
from ..domain.ids import new_id
from ..domain.source import InstalledSource, SourceSpec
from ..errors import (
    EntityNotFoundError,
    MoGrabError,
    SourceNotFoundError,
    SourceUnsupportedError,
    TaskCancelledError,
)
from ..export.base import Exporter
from ..logging.setup import get_logger
from ..source.engine import ChapterDraft, SourceEngine
from ..storage.repository import BookRepository, ChapterRepository, SourceRepository

_logger = get_logger(__name__)

ProgressCallback = Callable[[int, int], Awaitable[None]]

StopCheck = Callable[[], bool]
"""返回 True 表示该停了。

**同步的**：它在每章的下载协程里调用，不该引入额外的 await 点。
调用方（`Application._handle_download`）查的是内存里的取消标志，本来就同步。
"""
"""进度回调，参数是 ``(已完成, 总数)``。Task Worker 接它来推 SSE。"""


# ---------------------------------------------------------------------------
# 章节差异
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ChapterDiff:
    """本地目录与远程目录的差异结果。"""

    new: list[ChapterDraft] = field(default_factory=list)
    changed: list[ChapterDraft] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    """本地存在但远程已消失的章节身份键（仅告警，不删除）。"""
    unchanged: list[ChapterDraft] = field(default_factory=list)

    @property
    def to_download(self) -> list[ChapterDraft]:
        """需要下载的章节 = 新增 + 内容变化。"""
        return [*self.new, *self.changed]

    @property
    def total(self) -> int:
        return len(self.new) + len(self.changed) + len(self.missing) + len(self.unchanged)


def _candidate_keys(
    *, source_chapter_id: str | None, url: str | None, index: int, title: str
) -> set[str]:
    """生成一个章节的全部候选身份键。

    使用**候选集合**而非单一键，是为了让 diff 对「书源某次更新后
    不再返回 source_chapter_id」这类变化保持鲁棒：只要 URL 身份仍能对上，
    就不会把整本书误判为「全新章节」。

    Returns:
        至少包含一个键；优先级信息由键前缀（``sid:`` > ``url:`` > ``idx:``）表达。
    """
    keys: set[str] = set()
    if source_chapter_id:
        keys.add(f"sid:{source_chapter_id}")
    if url:
        keys.add(f"url:{normalize_url(url)}")
    if not keys:
        keys.add(f"idx:{index}:{title}")
    return keys


def compute_chapter_diff(
    local: list[Chapter],
    remote: list[ChapterDraft],
) -> ChapterDiff:
    """计算章节差异。

    判定规则：

    - 远程有、本地无 → ``new``
    - 两边都有，且 ``title`` 或规范化 ``url`` 变化 → ``changed``
    - 两边都有且未变 → ``unchanged``
    - 本地有、远程无 → ``missing``（**不自动删除**，仅提示用户）

    匹配基于**候选身份集合的交集**（见 :func:`_candidate_keys`）。

    Note:
        内容级变更（``content_hash``）需在下载后比对，此处只做目录级比对；
        目录级未变但内容被站点静默修改的情况由 ``mog update --deep`` 覆盖。
    """
    local_index: dict[str, Chapter] = {}
    for chapter in local:
        for key in _candidate_keys(
            source_chapter_id=chapter.source_chapter_id,
            url=chapter.url,
            index=chapter.index,
            title=chapter.title,
        ):
            local_index.setdefault(key, chapter)

    matched: set[str] = set()
    diff = ChapterDiff()

    for draft in remote:
        candidates = _candidate_keys(
            source_chapter_id=draft.source_chapter_id,
            url=draft.url,
            index=draft.index,
            title=draft.title,
        )
        existing: Chapter | None = None
        for key in candidates:
            found = local_index.get(key)
            if found is not None and found.id not in matched:
                existing = found
                break

        if existing is None:
            diff.new.append(draft)
            continue

        matched.add(existing.id)
        if existing.title != draft.title or normalize_url(existing.url) != normalize_url(draft.url):
            diff.changed.append(draft)
        else:
            diff.unchanged.append(draft)

    diff.missing = [c.identity_key for c in local if c.id not in matched]
    return diff


# ---------------------------------------------------------------------------
# 计划与结果
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class DownloadPlan:
    """一次下载/更新要做的事。"""

    book_id: str
    total: int
    """远程目录里的章节总数。"""
    to_download: list[ChapterDraft]
    skipped: int = 0
    """目录没变、跳过下载的章节数。"""
    missing: list[str] = field(default_factory=list)
    """本地有但远程没了 —— 只提示，不删。"""
    latest_chapter: str | None = None
    """远程目录的最后一章标题。"""

    @property
    def is_noop(self) -> bool:
        """已是最新，无需下载。"""
        return not self.to_download


@dataclass(slots=True)
class ChapterFailure:
    """单章下载失败。"""

    title: str
    url: str
    code: str
    message: str


@dataclass(slots=True)
class DownloadReport:
    """一次下载/更新的结果。

    分成「计划」和「结果」两层：计划是打算做什么，结果是实际发生了什么。
    两者混在一个类型里，读代码时就分不清哪些字段是执行前填的、哪些是执行后填的。
    """

    plan: DownloadPlan
    downloaded: int = 0
    failed: int = 0
    failures: list[ChapterFailure] = field(default_factory=list)
    export_path: Path | None = None

    @property
    def ok(self) -> bool:
        """没有失败章节。"""
        return self.failed == 0

    @property
    def is_noop(self) -> bool:
        return self.plan.is_noop


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
class DownloadScheduler:
    """按 §18 的流程编排下载。

    依赖都是注入的，方便测试时替换成假实现：

    - ``engine``：书源执行器（抓详情、目录、正文）
    - ``sources`` / ``books`` / ``chapters``：仓储
    - ``pipeline``：正文清洗与校验。不传就只做最基础的空白规范化
    - ``exporter``：可选。只有显式给了导出目标才会用
    """

    def __init__(
        self,
        *,
        engine: SourceEngine,
        sources: SourceRepository,
        books: BookRepository,
        chapters: ChapterRepository,
        pipeline: ContentPipeline | None = None,
        exporter: Exporter | None = None,
    ) -> None:
        self._engine = engine
        self._sources = sources
        self._books = books
        self._chapters = chapters
        self._pipeline = pipeline
        self._exporter = exporter

    # ------------------------------------------------------------------
    # 书籍登记
    # ------------------------------------------------------------------
    async def ensure_book(self, source_id: str, book_url: str) -> Book:
        """按 URL 登记书籍：已有就刷新元数据，没有就新建。

        ``mog download <url>`` 走这条路。按 ``(source_id, source_book_id)``
        判断是否已存在，所以同一本书重复下载不会产生两条记录。
        """
        source = await self._require_source(source_id)
        draft = await self._engine.fetch_book(source.spec, book_url)
        now = datetime.now(UTC)

        existing = await self._books.get_by_identity(source_id, draft.source_book_id)
        if existing is not None:
            refreshed = existing.model_copy(
                update={
                    "url": draft.url,
                    "title": draft.title,
                    "author": draft.author,
                    "intro": draft.intro,
                    "cover_url": draft.cover_url,
                    "latest_chapter": draft.latest_chapter,
                    "status": draft.status,
                    # 书源自定义字段合并进 metadata，保留用户/其他书源已写入的键
                    "metadata": {**existing.metadata, **draft.extra},
                    "updated_at": now,
                }
            )
            await self._books.save(refreshed)
            return refreshed

        book = Book(
            id=new_id("book"),
            source_id=source_id,
            source_book_id=draft.source_book_id,
            url=draft.url,
            title=draft.title,
            author=draft.author,
            intro=draft.intro,
            cover_url=draft.cover_url,
            latest_chapter=draft.latest_chapter,
            status=draft.status,
            metadata=dict(draft.extra),
            created_at=now,
            updated_at=now,
        )
        await self._books.save(book)
        _logger.info("task.book_registered", book_id=book.id, source_id=source_id)
        return book

    # ------------------------------------------------------------------
    # 计划
    # ------------------------------------------------------------------
    async def plan_update(self, book_id: str) -> DownloadPlan:
        """算出要下载哪些章节，不实际下载。

        对应 ``mog update <book-id> --dry-run`` 与 §20 的流程。
        """
        book, source = await self._load(book_id)
        return await self._build_plan(book, source)

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------
    async def run(
        self,
        book_id: str,
        *,
        on_progress: ProgressCallback | None = None,
        should_stop: StopCheck | None = None,
        export_to: Path | None = None,
    ) -> DownloadReport:
        """执行完整下载流程（§18）。

        Args:
            on_progress: 每章结束后回调 ``(已完成, 总数)``，用于推进度。
            should_stop: 返回 True 就中断，抛 :class:`TaskCancelledError`。
                **取消一个正在跑的下载靠它** —— 没有它的话 `mog task cancel`
                只改状态，下载照跑不误。
            export_to: 给了就在落库后导出到这个路径。路径由调用方按配置和
                模板算好 —— 调度器不该知道配置文件长什么样。
        """
        book, source = await self._load(book_id)
        plan = await self._build_plan(book, source)
        report = DownloadReport(plan=plan)

        if plan.is_noop:
            _logger.info("task.already_up_to_date", book_id=book_id, chapters=plan.total)
            return report

        chapters, failures = await self._download_chapters(
            source.spec, book.id, plan.to_download, on_progress, should_stop
        )
        report.failures = failures
        report.failed = len(failures)

        if chapters:
            # 单事务落库。成功之后才计数 —— 顺序反了就会出现
            # 「报告说下载了 100 章，库里只有 60 章」。
            await self._chapters.save_many(chapters)
            report.downloaded = len(chapters)

        await self._refresh_book_stats(book, plan)

        if export_to is not None and self._exporter is not None:
            report.export_path = await self._export(book, export_to)

        _logger.info(
            "task.download_finished",
            book_id=book_id,
            downloaded=report.downloaded,
            failed=report.failed,
            skipped=plan.skipped,
        )
        return report

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _load(self, book_id: str) -> tuple[Book, InstalledSource]:
        """取出书籍和它对应的书源，顺手校验书源可用。"""
        book = await self._books.get(book_id)
        if book is None:
            raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})

        source = await self._require_source(book.source_id)
        if not source.is_usable:
            raise SourceUnsupportedError(
                f"书源当前不可用: {book.source_id}",
                details={
                    "source_id": book.source_id,
                    "enabled": source.enabled,
                    "health": source.health.value,
                },
            )
        return book, source

    async def _require_source(self, source_id: str) -> InstalledSource:
        source = await self._sources.get(source_id)
        if source is None:
            raise SourceNotFoundError(f"书源未安装: {source_id}", details={"source_id": source_id})
        return source

    async def _build_plan(self, book: Book, source: InstalledSource) -> DownloadPlan:
        """抓远程目录、和本地比一遍，得出要下载什么。"""
        drafts = await self._engine.fetch_chapters(source.spec, book.url)
        local = await self._chapters.list_by_book(book.id)
        diff = compute_chapter_diff(local, drafts)

        if diff.missing:
            _logger.warning(
                "task.chapters_missing_remotely",
                book_id=book.id,
                count=len(diff.missing),
            )

        return DownloadPlan(
            book_id=book.id,
            total=len(drafts),
            to_download=diff.to_download,
            skipped=len(diff.unchanged),
            missing=diff.missing,
            latest_chapter=drafts[-1].title if drafts else None,
        )

    async def _download_chapters(
        self,
        spec: SourceSpec,
        book_id: str,
        drafts: list[ChapterDraft],
        on_progress: ProgressCallback | None,
        should_stop: StopCheck | None = None,
    ) -> tuple[list[Chapter], list[ChapterFailure]]:
        """并发下载一批章节。

        并发度取书源自己的 ``network.concurrency``。注意网络层还有一道按书源
        隔离的限流器，这里再加信号量是为了**限制在途协程数量** ——
        一本三千章的书如果一次性铺开，内存和连接数都不好看。

        ``should_stop`` 在**拿到信号量之后、发请求之前**检查。放这个位置
        有讲究：放在最前面的话，所有协程在开工那一刻就检查完了，
        后来的取消谁也看不见。
        """
        semaphore = asyncio.Semaphore(max(1, spec.network.concurrency))
        total = len(drafts)
        done = 0

        async def fetch_one(draft: ChapterDraft) -> Chapter | ChapterFailure:
            nonlocal done
            async with semaphore:
                if should_stop is not None and should_stop():
                    raise TaskCancelledError("下载已取消")
                try:
                    return await self._fetch_chapter(spec, book_id, draft)
                except MoGrabError as exc:
                    return ChapterFailure(
                        title=draft.title, url=draft.url, code=exc.code, message=exc.message
                    )
                except Exception as exc:
                    _logger.error("task.chapter_unexpected_error", url=draft.url, error=str(exc))
                    return ChapterFailure(
                        title=draft.title, url=draft.url, code="UNEXPECTED", message=str(exc)
                    )
                finally:
                    # 没有 await 参与，单线程事件循环下自增是安全的
                    done += 1
                    if on_progress is not None:
                        await on_progress(done, total)

        # 用 TaskGroup 而不是 gather：取消时 gather 会把其余协程**丢在后台继续跑**
        # （它只把第一个异常抛出来，不取消兄弟），TaskGroup 会一起取消并等干净。
        # 章节级的失败不抛异常（`fetch_one` 收进 ChapterFailure），
        # 所以这里的取消语义不会误伤正常的失败收集。
        try:
            async with asyncio.TaskGroup() as group:
                running = [group.create_task(fetch_one(draft)) for draft in drafts]
        except BaseExceptionGroup as group_error:
            # **TaskGroup 会把异常包成 ExceptionGroup**，而 TaskRunner 是按
            # `except TaskCancelledError` 判断的 —— 不拆开的话取消会被当成
            # 「意料之外的失败」，任务标成 FAILED 而不是 CANCELLED。
            cancelled = group_error.subgroup(TaskCancelledError)
            if cancelled is not None:
                raise TaskCancelledError("下载已取消") from None
            raise

        results = [task.result() for task in running]
        chapters = [r for r in results if isinstance(r, Chapter)]
        failures = [r for r in results if isinstance(r, ChapterFailure)]
        return chapters, failures

    async def _fetch_chapter(self, spec: SourceSpec, book_id: str, draft: ChapterDraft) -> Chapter:
        """抓一章正文，清洗校验后组装成领域对象。"""
        raw = await self._engine.fetch_content(spec, draft.url, chapter_index=draft.index)
        now = datetime.now(UTC)

        if self._pipeline is not None:
            # 清洗和校验是 CPU 活（正则为主），丢到线程里别堵住事件循环
            processed = await asyncio.to_thread(self._pipeline.process, raw)
            text = processed.text
            word_count = processed.word_count
            content_hash = processed.content_hash
        else:
            text = raw.strip()
            word_count = count_words(text)
            content_hash = compute_content_hash(text)

        return Chapter(
            id=new_id("chap"),
            book_id=book_id,
            source_chapter_id=draft.source_chapter_id,
            title=draft.title,
            url=draft.url,
            index=draft.index,
            content=text,
            content_hash=content_hash,
            word_count=word_count,
            created_at=now,
            updated_at=now,
        )

    async def _refresh_book_stats(self, book: Book, plan: DownloadPlan) -> None:
        """落库之后刷新书籍的派生统计。"""
        count, words = await self._chapters.stats_by_book(book.id)
        book.chapter_count = count
        book.word_count = words
        if plan.latest_chapter is not None:
            book.latest_chapter = plan.latest_chapter
        book.updated_at = datetime.now(UTC)
        await self._books.save(book)

    async def _export(self, book: Book, target: Path) -> Path:
        """导出整本书。要的是全部章节，不只是这次新下的。"""
        chapters = await self._chapters.list_by_book(book.id)
        result = await self._exporter.export(book, chapters, target)  # type: ignore[union-attr]
        return result.path


__all__ = [
    "ChapterDiff",
    "ChapterFailure",
    "DownloadPlan",
    "DownloadReport",
    "DownloadScheduler",
    "ProgressCallback",
    "compute_chapter_diff",
]
