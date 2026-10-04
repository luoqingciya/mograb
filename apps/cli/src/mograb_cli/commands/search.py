# SPDX-License-Identifier: GPL-3.0-only
"""``mog search`` —— 搜索小说（规划书 §31）。"""

from __future__ import annotations

import typer


def search(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    source: list[str] = typer.Option(
        None, "--source", "-s", help="限定书源 ID（可重复；默认全部启用书源）"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="每源返回上限"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """跨书源搜索。

    规划书 §29 的 ``GET /search`` 未说明是否跨源聚合；此处裁决为
    **默认跨源聚合**，可用 ``--source`` 限定，结果按来源分组展示。
    """
    raise NotImplementedError("search 待 API / Source Engine 接入后实现")


__all__ = ["search"]
