# SPDX-License-Identifier: GPL-3.0-only
"""Markdown 导出（规划书 §26）。

产出结构::

    # 书名

    - 作者：...
    - 来源：...

    ## 1. 第一章标题

    段落一

    段落二
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..content.normalizer import split_paragraphs
from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import ExportFormat
from ..logging.setup import get_logger
from .base import ExportResult

_logger = get_logger(__name__)


class MarkdownExporter:
    """导出为 Markdown（单文件）。"""

    format = ExportFormat.MARKDOWN

    def __init__(self, *, heading_level: int = 2) -> None:
        self._heading_level = heading_level

    async def export(self, book: Book, chapters: list[Chapter], target: Path) -> ExportResult:
        content = self.render(book, chapters)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, "utf-8")

        size = target.stat().st_size
        _logger.info("export.markdown", book_id=book.id, path=str(target), size=size)
        return ExportResult(
            book_id=book.id,
            format=ExportFormat.MARKDOWN,
            path=target,
            size_bytes=size,
            chapter_count=len(chapters),
        )

    def render(self, book: Book, chapters: list[Chapter]) -> str:
        parts: list[str] = [self._render_header(book)]
        for chapter in chapters:
            parts.append(self._render_chapter(chapter))
        return "\n".join(parts).strip() + "\n"

    def _render_header(self, book: Book) -> str:
        lines = [f"# {book.title}", ""]
        if book.author:
            lines.append(f"- 作者：{book.author}")
        lines.append(f"- 来源：{book.source_id}")
        if book.intro:
            lines.extend(["", f"> {book.intro}"])
        return "\n".join(lines)

    def _render_chapter(self, chapter: Chapter) -> str:
        hashes = "#" * self._heading_level
        paragraphs = split_paragraphs(chapter.content or "")
        body = "\n\n".join(paragraphs) if paragraphs else "_（本章内容为空）_"
        return f"{hashes} {chapter.title}\n\n{body}"


__all__ = ["MarkdownExporter"]
