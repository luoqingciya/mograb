# SPDX-License-Identifier: GPL-3.0-only
"""``mog export`` —— 导出书籍（规划书 §26、§31）。"""

from __future__ import annotations

import typer


def export(
    book_id: str = typer.Argument(..., help="MoGrab 书籍 ID"),
    format: str = typer.Option("epub", "--format", "-f", help="txt / markdown / epub"),
    output: str | None = typer.Option(None, "--output", "-o", help="输出目录或文件路径"),
    template: str | None = typer.Option(None, "--template", "-t", help="文件名模板"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """导出为 TXT / Markdown / EPUB。"""
    raise NotImplementedError("export 待 Storage + Export 接入后实现")


__all__ = ["export"]
