# SPDX-License-Identifier: GPL-3.0-only
"""``mog download`` —— 下载书籍（规划书 §31）。"""

from __future__ import annotations

import typer


def download(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    source: str | None = typer.Option(None, "--source", "-s", help="书源 ID"),
    url: str | None = typer.Option(None, "--url", "-u", help="直接以书籍页 URL 下载"),
    concurrency: int | None = typer.Option(None, "--concurrency", "-c", help="覆盖并发度"),
    export_format: str | None = typer.Option(
        None, "--format", "-f", help="下载完成后导出格式（txt/markdown/epub）"
    ),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """创建下载任务（异步，可通过 ``mog task`` 跟踪）。"""
    raise NotImplementedError("download 待 Task Engine 接入后实现")


__all__ = ["download"]
