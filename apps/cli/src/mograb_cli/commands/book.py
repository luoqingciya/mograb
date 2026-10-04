# SPDX-License-Identifier: GPL-3.0-only
"""``mog book`` —— 书籍信息（规划书 §31）。"""

from __future__ import annotations

import typer


def info(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """查看书籍详情与章节统计。"""
    raise NotImplementedError("book info 待 Storage 接入后实现")


__all__ = ["info"]
