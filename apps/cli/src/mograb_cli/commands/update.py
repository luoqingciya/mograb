# SPDX-License-Identifier: GPL-3.0-only
"""``mog update`` —— 增量更新（规划书 §20、§31）。"""

from __future__ import annotations

import typer


def update(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    dry_run: bool = typer.Option(False, "--dry-run", help="只输出差异计划，不实际下载"),
    deep: bool = typer.Option(False, "--deep", help="重新比对已下载章节的内容哈希（更慢但更彻底）"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """比对本地与远程目录，下载新增/变更章节。"""
    raise NotImplementedError("update 待 DownloadScheduler 接入后实现")


__all__ = ["update"]
