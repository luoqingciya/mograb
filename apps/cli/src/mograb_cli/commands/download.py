# SPDX-License-Identifier: GPL-3.0-only
"""``mog download`` —— 下载书籍（规划书 §31）。

就地跑完再退出，不走队列。命令行进程跑完就结束，起 worker 池再等调度没意义；
后台执行是 API server 的事。任务记录照样写库，``mog task list`` 能看到历史。
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from mograb.domain.enums import TaskStatus, TaskType
from mograb.errors import EntityNotFoundError

from ._common import command, console, emit, open_app


def _progress_bar() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )


@command
async def download(
    book_id: str | None = typer.Argument(None, help="MoGrab 书籍 ID"),
    url: str | None = typer.Option(None, "--url", "-u", help="直接给书籍页 URL"),
    source: str | None = typer.Option(None, "--source", "-s", help="书源 ID（配合 --url）"),
    export_format: str | None = typer.Option(
        None, "--format", "-f", help="下载完成后导出（txt/markdown/epub）"
    ),
    output: Path | None = typer.Option(None, "--output", "-o", help="导出路径"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """下载整本书。已经下过的章节会跳过。"""
    if url is None and book_id is None:
        console.print("[red]要么给 book_id，要么给 --url[/red]")
        raise typer.Exit(code=2)
    if url is not None and source is None:
        console.print("[red]用 --url 时必须同时指定 --source[/red]")
        raise typer.Exit(code=2)

    async with open_app() as application:
        if url is not None:
            assert source is not None
            book = await application.scheduler.ensure_book(source, url)
        else:
            assert book_id is not None
            found = await application.books.get(book_id)
            if found is None:
                raise EntityNotFoundError(f"书籍不存在: {book_id}", details={"book_id": book_id})
            book = found

        if not json_output:
            console.print(f"[bold]{book.title}[/bold]  ({book.id})")

        with _progress_bar() as progress:
            bar = progress.add_task("下载章节", total=None)

            async def on_progress(done: int, total: int) -> None:
                progress.update(bar, total=total, completed=done)

            task = await application.run_task(
                TaskType.DOWNLOAD_BOOK, book_id=book.id, on_progress=on_progress
            )

        export_path = None
        if export_format:
            export_task = await application.run_task(
                TaskType.EXPORT_BOOK,
                book_id=book.id,
                params={"format": export_format, "target": str(output) if output else None},
            )
            if export_task.status is TaskStatus.SUCCESS:
                export_path = export_task.params.get("path")

        refreshed = await application.books.get(book.id)

    result = {
        "book_id": book.id,
        "title": book.title,
        "status": task.status.value,
        "downloaded": task.completed,
        "failed": task.failed,
        "total": task.total,
        "error": task.error_message,
        "export_path": export_path,
    }
    emit(result, json_output=json_output)
    if json_output:
        return

    if task.status is TaskStatus.SUCCESS:
        console.print(
            f"完成：新下载 [bold]{task.completed}[/bold] 章，"
            f"失败 {task.failed} 章，共 {task.total} 章"
        )
        if refreshed is not None:
            console.print(
                f"[dim]本地已有 {refreshed.chapter_count} 章 / {refreshed.word_count} 字[/dim]"
            )
        if export_path:
            console.print(f"已导出 → {export_path}")
    else:
        console.print(f"[red]任务失败[/red] [{task.error_code}] {task.error_message}")
        raise typer.Exit(code=1)


__all__ = ["download"]
