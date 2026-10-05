# SPDX-License-Identifier: GPL-3.0-only
"""``mog book`` —— 书籍信息（规划书 §31）。

**不给 ID 就是书架列表。** 这条很关键：`mog export` / `mog update` 都要
`book_id`，而那个 ID 是 ULID 拼出来的（`book_01M459...`），没人记得住。
原先只有一个「必须给 ID」的命令，用户下载完关掉终端就再也找不回自己的书了。
"""

from __future__ import annotations

import typer
from rich.table import Table

from mograb.errors import EntityNotFoundError

from ._common import command, console, emit, open_app

DEFAULT_LIMIT = 50


@command
async def info(
    book_id: str | None = typer.Argument(None, help="MoGrab 书籍 ID。不填则列出全部书籍"),
    chapters: bool = typer.Option(False, "--chapters", "-c", help="一并列出章节（需给 ID）"),
    limit: int = typer.Option(
        DEFAULT_LIMIT, "--limit", "-n", min=1, max=500, help="列表模式下最多显示几本"
    ),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看书籍详情；不给 ID 时列出已下载的全部书籍。"""
    if book_id is None:
        if chapters:
            console.print("[red]--chapters 要配合 book_id 用[/red]")
            raise typer.Exit(code=2)
        await _list_books(limit=limit, json_output=json_output)
        return

    async with open_app() as application:
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


async def _list_books(*, limit: int, json_output: bool) -> None:
    """列出已下载的书籍，最近更新的在前。"""
    async with open_app() as application:
        books = await application.books.list_all(limit=limit)

    emit(
        [
            {
                "id": b.id,
                "title": b.title,
                "author": b.author,
                "source_id": b.source_id,
                "status": b.status.value,
                "chapter_count": b.chapter_count,
                "word_count": b.word_count,
                "updated_at": b.updated_at,
            }
            for b in books
        ],
        json_output=json_output,
    )
    if json_output:
        return

    if not books:
        console.print("[yellow]书架是空的[/yellow]")
        console.print("[dim]用 `mog search <关键词>` 找书，再 `mog download` 下载[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    # **ID 绝不能截断** —— 它就是要被复制去 `mog export` 的那个东西。
    # Rich 默认会把列压到终端宽度以内，于是显示成 `book_01M4590…`，白给。
    table.add_column("ID", no_wrap=True)
    table.add_column("书名", overflow="fold")
    table.add_column("作者", no_wrap=True)
    table.add_column("章节", justify="right", no_wrap=True)
    table.add_column("更新", no_wrap=True)
    for b in books:
        table.add_row(
            b.id,
            b.title,
            b.author or "-",
            str(b.chapter_count),
            f"{b.updated_at:%Y-%m-%d}",
        )
    console.print(table)
    console.print("[dim]用 `mog book <ID>` 看详情（含字数），`mog export <ID>` 导出[/dim]")

    if len(books) >= limit:
        console.print(f"[dim]只显示了前 {limit} 本，用 `--limit` 调整[/dim]")


__all__ = ["info"]
