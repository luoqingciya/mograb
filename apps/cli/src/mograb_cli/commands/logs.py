# SPDX-License-Identifier: GPL-3.0-only
"""``mog logs`` —— 日志查看（规划书 §36）。

日志按用途分成三个文件（app / task / source），这里按需读其中一个。
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from mograb.config import get_paths

from ._common import console

_FILES = {"app": "app.log", "task": "task.log", "source": "source.log"}

POLL_INTERVAL = 0.5


def _tail(path: Path, count: int) -> list[str]:
    """读文件末尾若干行。

    直接全读再切片 —— 日志有轮转上限（单文件 10MB），一次读进内存没问题，
    换成从后往前 seek 反而容易在编码边界上出错。
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-count:] if count > 0 else lines


def logs(
    target: str = typer.Option("app", "--target", "-t", help="app / task / source"),
    follow: bool = typer.Option(False, "--follow", "-f", help="持续跟踪输出"),
    lines: int = typer.Option(50, "--lines", "-n", help="显示末尾行数"),
) -> None:
    """查看日志。"""
    if target not in _FILES:
        valid = ", ".join(_FILES)
        raise typer.BadParameter(f"未知日志 {target!r}，可选：{valid}")

    path = get_paths().logs_dir / _FILES[target]
    if not path.is_file():
        console.print(f"[yellow]日志文件还不存在[/yellow] {path}")
        console.print("[dim]跑一次会写日志的命令就有了[/dim]")
        return

    for line in _tail(path, lines):
        console.print(line, highlight=False)

    if not follow:
        return

    console.print(f"[dim]跟踪 {path}（Ctrl+C 退出）[/dim]")
    offset = path.stat().st_size
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size < offset:
                # 文件被轮转了，从头开始读
                offset = 0
            if size == offset:
                continue
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(offset)
                for line in handle:
                    console.print(line.rstrip("\n"), highlight=False)
                offset = handle.tell()
    except KeyboardInterrupt:
        raise typer.Exit() from None


__all__ = ["logs"]
