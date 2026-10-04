# SPDX-License-Identifier: GPL-3.0-only
"""EPUB 导出（规划书 §27）。

**EPUB 不是把 TXT 改后缀**，必须生成规范结构::

    EPUB
    ├── mimetype              （必须第一个写入，且不压缩）
    ├── META-INF/container.xml
    └── OEBPS/
        ├── content.opf       （元数据 + manifest + spine）
        ├── toc.xhtml         （EPUB3 导航文档）
        ├── toc.ncx           （EPUB2 兼容，供老阅读器）
        ├── style.css
        ├── cover.xhtml       （可选）
        └── chapter_001.xhtml ...

元数据字段（§27）：title / author / language / description / cover /
publisher / created_at。语言缺省为 ``zh-CN``（由 Book.language 覆盖）。

**依赖决策**：不引入 ``ebooklib``（其许可证为 AGPL-3.0，会给 GPL-3.0-only
项目带来额外分发义务）。EPUB 本质是 ZIP + XHTML + OPF，自研实现成本可控。
"""

from __future__ import annotations

import asyncio
import uuid
import zipfile
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from ..content.normalizer import split_paragraphs
from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import ExportFormat
from ..logging.setup import get_logger
from .base import ExportResult

_logger = get_logger(__name__)

MIMETYPE = "application/epub+zip"
DEFAULT_LANGUAGE = "zh-CN"
DEFAULT_CSS = """\
body { font-family: serif; line-height: 1.6; margin: 1em; }
h1 { font-size: 1.4em; margin: 1.2em 0 0.8em; }
p { text-indent: 2em; margin: 0.5em 0; }
.cover { text-align: center; }
"""

_CONTAINER_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


class EpubExporter:
    """导出为 EPUB 3（兼容 EPUB 2 阅读器）。"""

    format = ExportFormat.EPUB

    def __init__(self, *, css: str | None = None, include_cover: bool = True) -> None:
        self._css = css or DEFAULT_CSS
        self._include_cover = include_cover

    async def export(self, book: Book, chapters: list[Chapter], target: Path) -> ExportResult:
        """写出 EPUB 文件。"""
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._write_epub, book, chapters, target)

        size = target.stat().st_size
        _logger.info("export.epub", book_id=book.id, path=str(target), size=size)
        return ExportResult(
            book_id=book.id,
            format=ExportFormat.EPUB,
            path=target,
            size_bytes=size,
            chapter_count=len(chapters),
        )

    # ------------------------------------------------------------------
    def _write_epub(self, book: Book, chapters: list[Chapter], target: Path) -> None:
        book_id = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'mograb:{book.id}')}"

        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1) mimetype 必须第一个写入且不压缩
            zf.writestr(
                zipfile.ZipInfo("mimetype"),
                MIMETYPE,
                compress_type=zipfile.ZIP_STORED,
            )

            # 2) 容器描述
            zf.writestr("META-INF/container.xml", _CONTAINER_XML)

            # 3) 样式
            zf.writestr("OEBPS/style.css", self._css)

            # 4) 章节
            manifest_items: list[str] = []
            spine_items: list[str] = []
            nav_points: list[str] = []

            for i, chapter in enumerate(chapters, start=1):
                name = f"chapter_{i:04d}.xhtml"
                zf.writestr(f"OEBPS/{name}", self._render_chapter_xhtml(chapter))
                manifest_items.append(
                    f'    <item id="ch{i}" href="{name}" media-type="application/xhtml+xml"/>'
                )
                spine_items.append(f'    <itemref idref="ch{i}"/>')
                nav_points.append(f'      <li><a href="{name}">{escape(chapter.title)}</a></li>')

            # 5) 导航文档
            zf.writestr(
                "OEBPS/toc.xhtml",
                self._render_nav(book, chapters, nav_points),
            )
            manifest_items.append(
                '    <item id="toc" href="toc.xhtml" '
                'media-type="application/xhtml+xml" properties="nav"/>'
            )

            # 6) NCX（EPUB2 兼容）
            zf.writestr("OEBPS/toc.ncx", self._render_ncx(book, chapters, book_id))
            manifest_items.append(
                '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            )

            manifest_items.append('    <item id="css" href="style.css" media-type="text/css"/>')

            # 7) OPF
            zf.writestr(
                "OEBPS/content.opf",
                self._render_opf(book, book_id, manifest_items, spine_items),
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _render_chapter_xhtml(chapter: Chapter) -> str:
        paragraphs = split_paragraphs(chapter.content or "")
        if paragraphs:
            body = "\n".join(f"    <p>{escape(p)}</p>" for p in paragraphs)
        else:
            body = "    <p><em>（本章内容为空）</em></p>"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">\n'
            "<head>\n"
            f"  <title>{escape(chapter.title)}</title>\n"
            '  <link rel="stylesheet" type="text/css" href="style.css"/>\n'
            "</head>\n"
            "<body>\n"
            f"  <h1>{escape(chapter.title)}</h1>\n"
            f"{body}\n"
            "</body>\n"
            "</html>\n"
        )

    @staticmethod
    def _render_nav(book: Book, chapters: list[Chapter], nav_points: list[str]) -> str:
        items = "\n".join(nav_points) if nav_points else "      <li><span>（无章节）</span></li>"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN">\n'
            "<head>\n"
            f"  <title>{escape(book.title)}</title>\n"
            "</head>\n"
            "<body>\n"
            '  <nav epub:type="toc" id="toc">\n'
            "    <h1>目录</h1>\n"
            "    <ol>\n"
            f"{items}\n"
            "    </ol>\n"
            "  </nav>\n"
            "</body>\n"
            "</html>\n"
        )

    @staticmethod
    def _render_ncx(book: Book, chapters: list[Chapter], book_id: str) -> str:
        points = "\n".join(
            f'    <navPoint id="nav{i}" playOrder="{i}">\n'
            f"      <navLabel><text>{escape(c.title)}</text></navLabel>\n"
            f'      <content src="chapter_{i:04d}.xhtml"/>\n'
            "    </navPoint>"
            for i, c in enumerate(chapters, start=1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            "  <head>\n"
            f'    <meta name="dtb:uid" content="{book_id}"/>\n'
            '    <meta name="dtb:depth" content="1"/>\n'
            "  </head>\n"
            f"  <docTitle><text>{escape(book.title)}</text></docTitle>\n"
            "  <navMap>\n"
            f"{points}\n"
            "  </navMap>\n"
            "</ncx>\n"
        )

    @staticmethod
    def _render_opf(
        book: Book,
        book_id: str,
        manifest_items: list[str],
        spine_items: list[str],
    ) -> str:
        created = (
            book.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            if book.created_at.tzinfo
            else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        language = book.language or DEFAULT_LANGUAGE
        manifest = "\n".join(manifest_items)
        spine = "\n".join(spine_items)

        meta_extra = ""
        if book.intro:
            meta_extra += f"    <dc:description>{escape(book.intro)}</dc:description>\n"

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="bookid">{book_id}</dc:identifier>\n'
            f"    <dc:title>{escape(book.title)}</dc:title>\n"
            f"    <dc:creator>{escape(book.author or 'Unknown')}</dc:creator>\n"
            f"    <dc:language>{language}</dc:language>\n"
            f"    <dc:source>{escape(book.source_id)}</dc:source>\n"
            f"{meta_extra}"
            f'    <meta property="dcterms:modified">{created}</meta>\n'
            "  </metadata>\n"
            "  <manifest>\n"
            f"{manifest}\n"
            "  </manifest>\n"
            '  <spine toc="ncx">\n'
            f"{spine}\n"
            "  </spine>\n"
            "</package>\n"
        )


__all__ = ["DEFAULT_CSS", "DEFAULT_LANGUAGE", "MIMETYPE", "EpubExporter"]
