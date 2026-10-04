# SPDX-License-Identifier: GPL-3.0-only
"""``mog update`` —— 增量更新（规划书 §20、§31）。"""

from __future__ import annotations

import typer
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from mograb.domain.enums import TaskStatus, TaskType

from ._common import command, console, emit, open_app


@command
async def update(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只输出差异计划，不实际下载"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """比对本地与远程目录，只下载新增和变更的章节。"""
    async with open_app() as application:
        if dry_run:
            plan = await application.scheduler.plan_update(book_id)
            emit(
                {
                    "book_id": plan.book_id,
                    "total": plan.total,
                    "to_download": len(plan.to_download),
                    "skipped": plan.skipped,
                    "missing": plan.missing,
                    "latest_chapter": plan.latest_chapter,
                },
                json_output=json_output,
            )
            if json_output:
                return

            console.print(f"远程共 {plan.total} 章")
            console.print(f"  需下载  [bold]{len(plan.to_download)}[/bold]")
            console.print(f"  已是最新 {plan.skipped}")
            if plan.missing:
                console.print(f"  [yellow]远程已消失 {len(plan.missing)}[/yellow]（不会删除本地）")
            if plan.is_noop:
                console.print("[green]已是最新，无需下载[/green]")
            return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            bar = progress.add_task("更新章节", total=None)

            async def on_progress(done: int, total: int) -> None:
                progress.update(bar, total=total, completed=done)

            task = await application.run_task(
                TaskType.UPDATE_BOOK, book_id=book_id, on_progress=on_progress
            )

    emit(
        {
            "book_id": book_id,
            "status": task.status.value,
            "downloaded": task.completed,
            "failed": task.failed,
            "total": task.total,
            "missing": task.params.get("missing", []),
            "error": task.error_message,
        },
        json_output=json_output,
    )
    if json_output:
        return

    if task.status is TaskStatus.SUCCESS:
        if task.completed == 0:
            console.print("[green]已是最新，没有新章节[/green]")
        else:
            console.print(f"更新完成：新增 [bold]{task.completed}[/bold] 章，失败 {task.failed} 章")
        missing = task.params.get("missing") or []
        if missing:
            console.print(
                f"[yellow]有 {len(missing)} 章在远程已找不到[/yellow]（本地保留，未删除）"
            )
    else:
        console.print(f"[red]任务失败[/red] [{task.error_code}] {task.error_message}")
        raise typer.Exit(code=1)


__all__ = ["update"]
