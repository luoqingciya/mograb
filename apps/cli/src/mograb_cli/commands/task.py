# SPDX-License-Identifier: GPL-3.0-only
"""``mog task`` —— 任务控制（规划书 §31）。

读操作（list / show）直接查本地库。控制操作（pause / resume / cancel / retry）
必须走 API —— 任务状态在 server 进程的内存里，改数据库它不知道。
"""

from __future__ import annotations

import typer

from mograb.domain.enums import TaskStatus
from mograb.errors import EntityNotFoundError

from ._api import (
    ApiUnauthorized,
    ApiUnavailable,
    explain_unauthorized,
    explain_unavailable,
    request,
)
from ._common import command, console, emit, open_app

app = typer.Typer(no_args_is_help=True, help="任务控制")


def _parse_status(raw: str | None) -> TaskStatus | None:
    if raw is None:
        return None
    try:
        return TaskStatus(raw.lower())
    except ValueError as exc:
        valid = ", ".join(s.value for s in TaskStatus)
        raise typer.BadParameter(f"未知状态 {raw!r}，可选：{valid}") from exc


@app.command("list")
@command
async def list_tasks(
    status: str | None = typer.Option(None, "--status", "-s", help="按状态过滤"),
    limit: int = typer.Option(20, "--limit", "-n", help="最多显示多少条"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """列出任务，最新的在前。"""
    wanted = _parse_status(status)

    async with open_app() as application:
        tasks = await application.tasks.list_all(status=wanted)

    tasks = tasks[:limit]
    emit(
        [
            {
                "id": t.id,
                "type": t.type.value,
                "status": t.status.value,
                "book_id": t.book_id,
                "total": t.total,
                "completed": t.completed,
                "failed": t.failed,
                "created_at": t.created_at,
                "error": t.error_message,
            }
            for t in tasks
        ],
        json_output=json_output,
    )
    if json_output:
        return

    if not tasks:
        console.print("[yellow]没有任务[/yellow]")
        return

    from rich.table import Table

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("类型")
    table.add_column("状态")
    table.add_column("进度")
    table.add_column("创建时间")
    for t in tasks:
        progress = f"{t.completed}/{t.total}" if t.total else "-"
        if t.failed:
            progress += f" [red]败{t.failed}[/red]"
        table.add_row(
            t.id,
            t.type.value,
            t.status.value,
            progress,
            f"{t.created_at:%m-%d %H:%M}",
        )
    console.print(table)


@app.command("show")
@command
async def show_task(
    task_id: str = typer.Argument(..., help="任务 ID"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看任务详情。"""
    async with open_app() as application:
        task = await application.tasks.get(task_id)
        if task is None:
            raise EntityNotFoundError(f"任务不存在: {task_id}", details={"task_id": task_id})
        items = await application.tasks.list_items(task_id)

    emit(
        {
            "id": task.id,
            "type": task.type.value,
            "status": task.status.value,
            "book_id": task.book_id,
            "source_id": task.source_id,
            "total": task.total,
            "completed": task.completed,
            "failed": task.failed,
            "error_code": task.error_code,
            "error_message": task.error_message,
            "params": task.params,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "items": [
                {"index": i.chapter_index, "title": i.title, "status": i.status.value}
                for i in items
            ],
        },
        json_output=json_output,
    )
    if json_output:
        return

    console.print(f"[bold]{task.id}[/bold]")
    console.print(f"  类型      {task.type.value}")
    console.print(f"  状态      {task.status.value}")
    if task.book_id:
        console.print(f"  书籍      {task.book_id}")
    console.print(f"  进度      {task.completed}/{task.total}（失败 {task.failed}）")
    if task.error_code:
        console.print(f"  错误      [{task.error_code}] {task.error_message}")
    if task.created_at:
        console.print(f"  创建      {task.created_at:%Y-%m-%d %H:%M:%S}")
    if task.finished_at:
        console.print(f"  结束      {task.finished_at:%Y-%m-%d %H:%M:%S}")
    if items:
        console.print(f"\n  共 {len(items)} 个任务项")


async def _control(action: str, task_id: str) -> dict:
    """通过 API 控制一个任务。"""
    async with open_app() as application:
        settings = application.settings

    try:
        return await request(settings, "POST", f"/tasks/{task_id}/{action}")
    except ApiUnavailable:
        explain_unavailable(settings)
        raise typer.Exit(code=1) from None
    except ApiUnauthorized:
        explain_unauthorized()
        raise typer.Exit(code=1) from None


@app.command("pause")
@command
async def pause(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """暂停任务（需要 server 在运行）。"""
    await _control("pause", task_id)
    console.print(f"已暂停 [bold]{task_id}[/bold]")


@app.command("resume")
@command
async def resume(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """继续任务（需要 server 在运行）。"""
    await _control("resume", task_id)
    console.print(f"已继续 [bold]{task_id}[/bold]")


@app.command("cancel")
@command
async def cancel(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """取消任务（需要 server 在运行）。"""
    await _control("cancel", task_id)
    console.print(f"已取消 [bold]{task_id}[/bold]")


@app.command("retry")
@command
async def retry(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """重试失败的任务（需要 server 在运行）。

    终态不可逆，所以这是**新建一个任务**而不是复活旧的。
    """
    result = await _control("retry", task_id)
    new_id = (result or {}).get("id", "?")
    console.print(f"已创建重试任务 [bold]{new_id}[/bold]")


__all__ = ["app"]
