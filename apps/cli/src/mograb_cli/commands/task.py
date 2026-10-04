# SPDX-License-Identifier: GPL-3.0-only
"""``mog task`` —— 任务控制（规划书 §31）。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="任务控制")


@app.command("list")
def list_tasks(
    status: str | None = typer.Option(None, "--status", "-s", help="按状态过滤"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """列出任务。"""
    raise NotImplementedError("task list 待 TaskManager 接入后实现")


@app.command("show")
def show_task(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """查看任务详情与逐章进度。"""
    raise NotImplementedError("task show 待 TaskManager 接入后实现")


@app.command("pause")
def pause(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """暂停任务。"""
    raise NotImplementedError("task pause 待 TaskManager 接入后实现")


@app.command("resume")
def resume(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """继续任务。"""
    raise NotImplementedError("task resume 待 TaskManager 接入后实现")


@app.command("cancel")
def cancel(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """取消任务。"""
    raise NotImplementedError("task cancel 待 TaskManager 接入后实现")


@app.command("retry")
def retry(task_id: str = typer.Argument(..., help="任务 ID")) -> None:
    """重试失败的任务。"""
    raise NotImplementedError("task retry 待 TaskManager 接入后实现")


__all__ = ["app"]
