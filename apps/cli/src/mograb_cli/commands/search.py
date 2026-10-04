# SPDX-License-Identifier: GPL-3.0-only
"""``mog search`` —— 跨书源搜索（规划书 §31）。

默认在所有启用的、具备 search 能力的书源上并发搜。单个书源失败不影响整体，
失败信息单独列出来 —— 一个源挂了不该让整次搜索白跑。
"""

from __future__ import annotations

import asyncio

import typer

from mograb.domain.enums import SourceCapability

from ._common import command, console, emit, open_app


@command
async def search(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    source: list[str] | None = typer.Option(
        None, "--source", "-s", help="限定书源 ID（可重复；默认全部启用书源）"
    ),
    limit: int = typer.Option(20, "--limit", "-n", help="每源返回上限"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """在书源里搜关键词。"""
    async with open_app(ensure_paths=False) as application:
        entries = await application.sources.list_enabled()
        if source:
            wanted = set(source)
            entries = [e for e in entries if e.id in wanted]
            for source_id in sorted(wanted - {e.id for e in entries}):
                console.print(f"[yellow]跳过[/yellow] 书源不可用或未安装: {source_id}")

        searchable = [e for e in entries if e.spec.supports(SourceCapability.SEARCH)]
        if not searchable:
            console.print("[yellow]没有可用于搜索的书源[/yellow]")
            raise typer.Exit(code=1)

        async def one(entry):
            try:
                hits = await application.engine.search(entry.spec, keyword)
                return entry, hits[:limit], None
            except Exception as exc:
                return entry, [], exc

        gathered = await asyncio.gather(*(one(e) for e in searchable))

    items: list[dict] = []
    errors: list[dict] = []
    for entry, hits, error in gathered:
        if error is not None:
            errors.append(
                {"source_id": entry.id, "code": type(error).__name__, "message": str(error)}
            )
            continue
        for hit in hits:
            items.append(
                {
                    "source_id": hit.source_id,
                    "title": hit.title,
                    "author": hit.author,
                    "url": hit.url,
                }
            )

    emit(
        {"keyword": keyword, "total": len(items), "items": items, "errors": errors},
        json_output=json_output,
    )
    if json_output:
        return

    if not items:
        console.print(f"[yellow]没搜到「{keyword}」[/yellow]")
    else:
        from rich.table import Table

        table = Table(show_header=True, header_style="bold")
        table.add_column("来源")
        table.add_column("书名")
        table.add_column("作者")
        table.add_column("URL", overflow="fold")
        for item in items:
            table.add_row(item["source_id"], item["title"], item["author"] or "-", item["url"])
        console.print(table)
        console.print("[dim]用 `mog download --url <URL> --source <来源>` 下载[/dim]")

    for err in errors:
        console.print(f"[red]失败[/red] {err['source_id']}: {err['message']}")


__all__ = ["search"]
