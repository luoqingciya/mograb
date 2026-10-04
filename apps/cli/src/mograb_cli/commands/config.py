# SPDX-License-Identifier: GPL-3.0-only
"""``mog config`` —— 配置管理（规划书 §35）。"""

from __future__ import annotations

import typer

from mograb.config import get_paths, runtime_dir, write_default_config

from ._common import console, emit

app = typer.Typer(no_args_is_help=True, help="配置管理")


@app.command("init")
def init(
    overwrite: bool = typer.Option(False, "--force", help="覆盖已存在的配置文件"),
) -> None:
    """生成默认配置文件。"""
    paths = get_paths()
    path = write_default_config(paths.config_file, overwrite=overwrite)
    console.print(f"已写入配置文件: [bold]{path}[/bold]")


@app.command("path")
def show_path(
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """显示程序目录与数据目录位置。"""
    paths = get_paths()
    data = {
        "runtime": str(runtime_dir()),
        "data": str(paths.root),
        "config": str(paths.config_file),
        "database": str(paths.database),
        "cache": str(paths.cache_dir),
        "covers": str(paths.covers_dir),
        "exports": str(paths.exports_dir),
        "logs": str(paths.logs_dir),
        "sources": str(paths.sources_dir),
    }
    if json_output:
        emit(data, json_output=True)
        return
    for key, value in data.items():
        console.print(f"[bold]{key:10s}[/bold] {value}")


@app.command("show")
def show() -> None:
    """显示当前生效配置。"""
    raise NotImplementedError("config show 待 load_settings 接入后实现")


__all__ = ["app"]
