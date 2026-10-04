# SPDX-License-Identifier: GPL-3.0-only
"""``mog server`` —— 本地 API Server 控制（规划书 §34）。"""

from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="本地 API Server")


@app.command("start")
def start(
    host: str | None = typer.Option(None, "--host", help="监听地址（默认 127.0.0.1）"),
    port: int | None = typer.Option(None, "--port", "-p", help="监听端口"),
    foreground: bool = typer.Option(False, "--foreground", help="前台运行（默认后台守护）"),
) -> None:
    """启动本地 API Server。

    默认仅监听 ``127.0.0.1``（规划书 §40）。
    """
    raise NotImplementedError("server start 待 API 应用实现后接入")


@app.command("status")
def status(json_output: bool = typer.Option(False, "--json", help="以 JSON 输出")) -> None:
    """查看 Server 运行状态。"""
    raise NotImplementedError("server status 待 API 应用实现后接入")


@app.command("stop")
def stop() -> None:
    """停止本地 API Server。"""
    raise NotImplementedError("server stop 待 API 应用实现后接入")


__all__ = ["app"]
