# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/books`` —— 书籍与章节（规划书 §29）。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from mograb.domain.chapter import Chapter
from mograb.domain.chapter import ChapterSummary as DomainChapterSummary
from mograb.errors import EntityNotFoundError

from ..deps import ApplicationDep

router = APIRouter(prefix="/books", tags=["books"])


class BookOut(BaseModel):
    """书籍视图。"""

    id: str
    source_id: str
    source_book_id: str
    url: str
    title: str
    author: str | None = None
    intro: str | None = None
    language: str | None = None
    cover_url: str | None = None
    status: str
    latest_chapter: str | None = None
    chapter_count: int
    word_count: int
    created_at: datetime
    updated_at: datetime


class ChapterSummary(BaseModel):
    """章节摘要（不含正文）。

    目录可能有几千章，带上正文响应体会大得离谱，所以正文单独取。
    """

    id: str
    title: str
    index: int
    word_count: int
    has_content: bool


class ChapterDetail(ChapterSummary):
    """章节正文。"""

    url: str
    content: str | None = None
    content_hash: str | None = None


def _to_book(book) -> BookOut:
    return BookOut(
        id=book.id,
        source_id=book.source_id,
        source_book_id=book.source_book_id,
        url=book.url,
        title=book.title,
        author=book.author,
        intro=book.intro,
        language=book.language,
        cover_url=book.cover_url,
        status=book.status.value,
        latest_chapter=book.latest_chapter,
        chapter_count=book.chapter_count,
        word_count=book.word_count,
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


def _summary_from_chapter(chapter: Chapter) -> ChapterSummary:
    """从完整章节（含正文）构造摘要。

    只有「读单章正文」那条路用得上 —— 它本来就拿到整章了。
    列目录走 `_summary_out`，不加载正文。
    """
    return ChapterSummary(
        id=chapter.id,
        title=chapter.title,
        index=chapter.index,
        word_count=chapter.word_count,
        has_content=bool(chapter.content),
    )


def _summary_out(summary: DomainChapterSummary) -> ChapterSummary:
    """领域摘要 → API schema。

    领域那边已经算好了 `has_content`（SQL 里的布尔投影），这里不用再碰正文。
    """
    return ChapterSummary(
        id=summary.id,
        title=summary.title,
        index=summary.index,
        word_count=summary.word_count,
        has_content=summary.has_content,
    )


@router.get("", response_model=list[BookOut], summary="列出书架")
async def list_books(
    application: ApplicationDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[BookOut]:
    """列出已下载书籍，最近更新的在前。"""
    books = await application.books.list_all(limit=limit, offset=offset)
    return [_to_book(b) for b in books]


@router.get("/{book_id}", response_model=BookOut, summary="书籍详情")
async def get_book(book_id: str, application: ApplicationDep) -> BookOut:
    """查看书籍详情。"""
    book = await application.books.get(book_id)
    if book is None:
        raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})
    return _to_book(book)


@router.get("/{book_id}/chapters", response_model=list[ChapterSummary], summary="章节列表")
async def list_chapters(book_id: str, application: ApplicationDep) -> list[ChapterSummary]:
    """列出章节目录（不含正文）。"""
    book = await application.books.get(book_id)
    if book is None:
        raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})
    # 只要摘要 —— `list_by_book` 会把整本书的正文读进内存
    return [_summary_out(s) for s in await application.chapters.list_summaries(book_id)]


@router.get("/{book_id}/chapters/{chapter_id}", response_model=ChapterDetail, summary="章节正文")
async def get_chapter(book_id: str, chapter_id: str, application: ApplicationDep) -> ChapterDetail:
    """读取单章正文。"""
    chapter = await application.chapters.get(chapter_id)
    if chapter is None or chapter.book_id != book_id:
        raise EntityNotFoundError(
            f"章节不存在: {chapter_id}",
            details={"book_id": book_id, "chapter_id": chapter_id},
        )
    return ChapterDetail(
        **_summary_from_chapter(chapter).model_dump(),
        url=chapter.url,
        content=chapter.content,
        content_hash=chapter.content_hash,
    )


class UpdateResult(BaseModel):
    """增量更新计划。"""

    book_id: str
    total: int
    to_download: int
    skipped: int
    missing: list[str] = Field(default_factory=list)
    latest_chapter: str | None = None
    dry_run: bool


@router.post("/{book_id}/update", response_model=UpdateResult, summary="增量更新")
async def update_book(
    book_id: str,
    application: ApplicationDep,
    dry_run: bool = Query(True, description="只算差异，不下载"),
) -> UpdateResult:
    """比对远程目录，按需下载新增/变更章节（规划书 §20）。

    默认 ``dry_run=true`` —— 这是个会打网络和写库的操作，
    想真跑得显式说一声。
    """
    plan = await application.scheduler.plan_update(book_id)

    if not dry_run and not plan.is_noop:
        from mograb.domain.enums import TaskType

        task = await application.run_task(TaskType.UPDATE_BOOK, book_id=book_id)
        if task.completed or task.failed:
            plan = await application.scheduler.plan_update(book_id)

    return UpdateResult(
        book_id=plan.book_id,
        total=plan.total,
        to_download=len(plan.to_download),
        skipped=plan.skipped,
        missing=plan.missing,
        latest_chapter=plan.latest_chapter,
        dry_run=dry_run,
    )
