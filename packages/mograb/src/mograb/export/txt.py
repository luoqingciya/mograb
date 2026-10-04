# SPDX-License-Identifier: GPL-3.0-only
"""TXT 导出（规划书 §26）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import ExportFormat
from ..logging.setup import get_logger
from .base import ExportResult

_logger = get_logger(__name__)

CHAPTER_SEPARATOR = "\n\n" + "=" * 40 + "\n\n"


class TxtExporter:
    """导出为单个 UTF-8 文本文件。"""

    format = ExportFormat.TXT

    def __init__(self, *, include_header: bool = True) -> None:
        self._include_header = include_header

    async def export(self, book: Book, chapters: list[Chapter], target: Path) -> ExportResult:
        """写出 TXT。"""
        content = self.render(book, chapters)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, "utf-8")

        size = target.stat().st_size
        _logger.info("export.txt", book_id=book.id, path=str(target), size=size)
        return ExportResult(
            book_id=book.id,
            format=ExportFormat.TXT,
            path=target,
            size_bytes=size,
            chapter_count=len(chapters),
        )

    def render(self, book: Book, chapters: list[Chapter]) -> str:
        """渲染 TXT 内容（纯函数，便于测试）。"""
        parts: list[str] = []

        if self._include_header:
            parts.append(self._render_header(book))

        for chapter in chapters:
            parts.append(self._render_chapter(chapter))

        return "".join(parts).strip() + "\n"

    @staticmethod
    def _render_header(book: Book) -> str:
        lines = [book.title]
        if book.author:
            lines.append(f"作者：{book.author}")
        if book.intro:
            lines.append("")
            lines.append(book.intro)
        return "\n".join(lines) + "\n\n" + "=" * 40 + "\n\n"

    @staticmethod
    def _render_chapter(chapter: Chapter) -> str:
        body = chapter.content or ""
        return f"{chapter.title}\n\n{body}{CHAPTER_SEPARATOR}"


__all__ = ["CHAPTER_SEPARATOR", "TxtExporter"]
