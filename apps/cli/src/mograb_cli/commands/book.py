# SPDX-License-Identifier: GPL-3.0-only
"""``mog book`` —— 书籍信息（规划书 §31）。"""

from __future__ import annotations

import typer

from mograb.errors import EntityNotFoundError

from ._common import command, console, emit, open_app


@command
async def info(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    chapters: bool = typer.Option(False, "--chapters", "-c", help="一并列出章节"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看书籍详情与章节统计。"""
    async with open_app(ensure_paths=False) as application:
        book = await application.books.get(book_id)
        if book is None:
            raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})
        listing = await application.chapters.list_by_book(book_id) if chapters else []

    emit(
        {
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "source_id": book.source_id,
            "source_book_id": book.source_book_id,
            "url": book.url,
            "status": book.status.value,
            "language": book.language,
            "chapter_count": book.chapter_count,
            "word_count": book.word_count,
            "latest_chapter": book.latest_chapter,
            "created_at": book.created_at,
            "updated_at": book.updated_at,
            "chapters": [
                {"index": c.index, "title": c.title, "word_count": c.word_count} for c in listing
            ],
        },
        json_output=json_output,
    )
    if json_output:
        return

    console.print(f"[bold]{book.title}[/bold]")
    console.print(f"  ID        {book.id}")
    console.print(f"  作者      {book.author or '-'}")
    console.print(f"  来源      {book.source_id} / {book.source_book_id}")
    console.print(f"  状态      {book.status.value}")
    console.print(f"  章节      {book.chapter_count}  共 {book.word_count} 字")
    if book.latest_chapter:
        console.print(f"  最新章节  {book.latest_chapter}")
    console.print(f"  来源页    {book.url}")
    console.print(f"  更新时间  {book.updated_at:%Y-%m-%d %H:%M}")

    if listing:
        console.print()
        for chapter in listing:
            console.print(f"  {chapter.index:>5}  {chapter.title}")


__all__ = ["info"]
