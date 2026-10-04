# SPDX-License-Identifier: GPL-3.0-only
"""``mog cache`` —— 缓存管理（规划书 §16、§31）。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="缓存管理")


@app.command("stats")
def stats(json_output: bool = typer.Option(False, "--json", help="以 JSON 输出")) -> None:
    """查看缓存条目数与占用空间。"""
    raise NotImplementedError("cache stats 待 HttpCache 接入后实现")


@app.command("clear")
def clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """清空全部缓存。"""
    raise NotImplementedError("cache clear 待 HttpCache 接入后实现")


@app.command("clear-source")
def clear_source(source_id: str = typer.Argument(..., help="书源 ID")) -> None:
    """清空指定书源的缓存。"""
    raise NotImplementedError("cache clear-source 待 HttpCache 接入后实现")


__all__ = ["app"]
