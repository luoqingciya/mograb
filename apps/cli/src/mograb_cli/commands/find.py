# SPDX-License-Identifier: GPL-3.0-only
"""``mog find`` —— 在已下载的书里搜正文（纯本地）。

和 ``mog search`` 是两件事：

- ``mog search <关键词>``  —— 去**书源**上搜书，找的是「哪本书」
- ``mog find <关键词>``    —— 在**本地已下载的章节正文**里搜，找的是「哪一章」

后者完全不访问网络，也不受任何站点 robots.txt 约束。
"""

from __future__ import annotations

import typer

from ._common import command, console, emit, open_app


@command
async def find(
    keyword: str = typer.Argument(..., help="要搜的关键词（字面子串，不解析正则）"),
    book_id: str | None = typer.Option(None, "--book", "-b", help="只搜这本书（MoGrab 书籍 ID）"),
    limit: int = typer.Option(50, "--limit", "-n", help="最多返回多少条命中"),
    json_output: bool = typer.Option(False, "--json", help="以 JSON 输出"),
) -> None:
    """在已下载的章节正文里搜关键词。"""
    async with open_app(ensure_paths=False) as application:
        hits = await application.chapters.search_content(keyword, book_id=book_id, limit=limit)

    if json_output:
        emit(
            {
                "keyword": keyword,
                "count": len(hits),
                "hits": [
                    {
                        "book_id": h.book_id,
                        "book_title": h.book_title,
                        "chapter_id": h.chapter_id,
                        "chapter_title": h.chapter_title,
                        "chapter_index": h.chapter_index,
                        "snippet": h.snippet,
                    }
                    for h in hits
                ],
            },
            json_output=True,
        )
        return

    if not hits:
        scope = "这本书里" if book_id else "本地书库里"
        console.print(f"[yellow]{scope}没有匹配「{keyword}」的内容[/yellow]")
        console.print("[dim]只搜已下载的章节正文；没下过的书搜不到[/dim]")
        return

    console.print(f"命中 [bold]{len(hits)}[/bold] 处：\n")
    for hit in hits:
        # 高亮关键词，扫一眼就能定位
        snippet = hit.snippet.replace(keyword, f"[bold red]{keyword}[/bold red]")
        console.print(f"[cyan]《{hit.book_title}》[/cyan] {hit.chapter_title}")
        console.print(f"  {snippet}")
        console.print(f"  [dim]{hit.book_id} / {hit.chapter_id}[/dim]\n")


__all__ = ["find"]
