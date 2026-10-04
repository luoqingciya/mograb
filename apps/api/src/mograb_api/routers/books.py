# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/books`` —— 书籍与章节（规划书 §29）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/books", tags=["books"])


class ChapterSummary(BaseModel):
    """章节摘要（不含正文）。"""

    id: str
    title: str
    index: int
    word_count: int = 0
    has_content: bool = False


@router.get("", summary="列出书架")
async def list_books(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, object]]:
    """列出已下载书籍。"""
    # TODO(storage): 接入 BookRepository.list_all()
    return []


@router.get("/{book_id}", summary="书籍详情")
async def get_book(book_id: str) -> dict[str, object]:
    """查看书籍详情。"""
    raise HTTPException(status_code=404, detail=f"书籍不存在: {book_id}")


@router.get("/{book_id}/chapters", response_model=list[ChapterSummary], summary="章节列表")
async def list_chapters(book_id: str) -> list[ChapterSummary]:
    """列出章节目录（不含正文）。"""
    # TODO(storage): 接入 ChapterRepository.list_by_book()
    return []


@router.get("/{book_id}/chapters/{chapter_id}", summary="章节正文")
async def get_chapter(book_id: str, chapter_id: str) -> dict[str, object]:
    """读取单章正文。"""
    raise HTTPException(status_code=404, detail=f"章节不存在: {chapter_id}")


@router.post("/{book_id}/update", summary="增量更新")
async def update_book(book_id: str, dry_run: bool = Query(False)) -> dict[str, object]:
    """比对远程目录并创建更新任务（规划书 §20）。"""
    raise HTTPException(status_code=501, detail="尚未实现")
