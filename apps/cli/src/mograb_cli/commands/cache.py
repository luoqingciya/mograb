# SPDX-License-Identifier: GPL-3.0-only
"""``mog cache`` —— 缓存管理（规划书 §16、§31）。"""

from __future__ import annotations

import typer

from ._common import command, console, emit, open_app

app = typer.Typer(no_args_is_help=True, help="缓存管理")


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


@app.command("stats")
@command
async def stats(
    purge: bool = typer.Option(False, "--purge", help="顺便清掉已过期的条目"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看缓存条目数与占用空间。"""
    async with open_app() as application:
        if purge:
            removed = await application.cache.purge_expired()
            if not json_output and removed:
                console.print(f"清掉 {removed} 条过期缓存")
        data = await application.cache.stats()

    emit(data, json_output=json_output)
    if json_output:
        return

    limit = data["max_size_bytes"]
    console.print(f"条目数    {data['entries']}")
    console.print(f"占用      {_human_size(data['size_bytes'])}")
    if limit:
        ratio = data["size_bytes"] / limit * 100
        console.print(f"上限      {_human_size(limit)}（已用 {ratio:.1f}%）")
    else:
        console.print("上限      不限")


@app.command("clear")
@command
async def clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """清空全部缓存。"""
    if not yes:
        typer.confirm("确定清空全部缓存吗？", abort=True)

    async with open_app() as application:
        removed = await application.cache.clear()

    console.print(f"已清掉 [bold]{removed}[/bold] 条缓存")


@app.command("clear-source")
@command
async def clear_source(source_id: str = typer.Argument(..., help="书源 ID")) -> None:
    """清空指定书源的缓存。

    站点改版后书源规则要调，先清掉这个源的缓存免得读到旧的。
    """
    async with open_app() as application:
        removed = await application.cache.invalidate_source(source_id)

    console.print(f"已清掉 [bold]{source_id}[/bold] 的 {removed} 条缓存")


__all__ = ["app"]
