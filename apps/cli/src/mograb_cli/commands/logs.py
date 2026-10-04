# SPDX-License-Identifier: GPL-3.0-only
"""``mog logs`` —— 日志查看（规划书 §36）。"""

from __future__ import annotations

import typer


def logs(
    target: str = typer.Option("app", "--target", "-t", help="app / task / source"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续跟踪输出"),
    lines: int = typer.Option(50, "--lines", "-n", help="显示末尾行数"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看日志文件。"""
    raise NotImplementedError("logs 待日志子系统接入后实现")


__all__ = ["logs"]
