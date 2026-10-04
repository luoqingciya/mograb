# SPDX-License-Identifier: GPL-3.0-only
"""``mog export`` —— 导出书籍（规划书 §26、§31）。"""

from __future__ import annotations

from pathlib import Path

import typer

from mograb.domain.enums import TaskStatus, TaskType
from mograb.errors import EntityNotFoundError

from ._common import command, console, emit, open_app


@command
async def export(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    format: str | None = typer.Option(None, "--format", "-f", help="txt / markdown / epub"),
    output: Path | None = typer.Option(None, "--output", "-o", help="输出文件路径"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """导出为 TXT / Markdown / EPUB。

    不传 ``--format`` 就用配置里的默认格式；不传 ``--output`` 就按
    ``output.directory`` 和文件名模板落到数据目录下的 exports/。
    """
    async with open_app() as application:
        book = await application.books.get(book_id)
        if book is None:
            raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})

        if book.chapter_count == 0:
            console.print("[yellow]这本书还没有下载任何章节[/yellow]")
            raise typer.Exit(code=1)

        task = await application.run_task(
            TaskType.EXPORT_BOOK,
            book_id=book.id,
            params={
                "format": format,
                "target": str(output) if output else None,
            },
        )

    emit(
        {
            "book_id": book.id,
            "status": task.status.value,
            "path": task.params.get("path"),
            "error": task.error_message,
        },
        json_output=json_output,
    )
    if json_output:
        return

    if task.status is TaskStatus.SUCCESS:
        console.print(f"已导出 → [bold]{task.params.get('path')}[/bold]")
    else:
        console.print(f"[red]导出失败[/red] [{task.error_code}] {task.error_message}")
        raise typer.Exit(code=1)


__all__ = ["export"]
