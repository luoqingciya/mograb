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
from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from ..content.normalizer import split_paragraphs
from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import ExportFormat
from ..logging.setup import get_logger
from .base import ExportResult, book_variables, render_template

_logger = get_logger(__name__)

_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _isoformat(moment: datetime) -> str:
    """EPUB 元数据要的时间格式（``2026-01-01T00:00:00Z``）。"""
    if moment.tzinfo is None:
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    def __init__(
        self,
        *,
        css: str | None = None,
        include_cover: bool = True,
        covers_dir: Path | None = None,
        metadata_templates: Mapping[str, str] | None = None,
    ) -> None:
        self._css = css or DEFAULT_CSS
        self._include_cover = include_cover
        self._covers_dir = covers_dir
        self._metadata_templates = dict(metadata_templates or {})

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

            # 7) 封面。要排在章节之前 —— 阅读器打开先看到封面。
            cover = self._load_cover(book)
            if cover is not None:
                image_name, media_type, image_bytes = cover
                zf.writestr(f"OEBPS/{image_name}", image_bytes)
                zf.writestr("OEBPS/cover.xhtml", self._render_cover_xhtml(book, image_name))
                manifest_items.insert(
                    0,
                    f'    <item id="cover-image" href="{image_name}" '
                    f'media-type="{media_type}" properties="cover-image"/>',
                )
                manifest_items.insert(
                    1,
                    '    <item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>',
                )
                spine_items.insert(0, '    <itemref idref="cover"/>')

            # 8) OPF
            zf.writestr(
                "OEBPS/content.opf",
                self._render_opf(
                    book,
                    book_id,
                    manifest_items,
                    spine_items,
                    has_cover=cover is not None,
                ),
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

    def _load_cover(self, book: Book) -> tuple[str, str, bytes] | None:
        """读出封面文件。

        Returns:
            ``(文件名, media-type, 字节)``；没封面或文件不在就 ``None``。

        **拿不到就跳过** —— 封面是可选资产，不该让导出失败。
        """
        if not self._include_cover or self._covers_dir is None:
            return None
        if not book.cover_path:
            return None

        # `cover_path` 是相对**数据目录**的路径（见 covers 模块），
        # 而 covers_dir 就是 `<数据目录>/covers`，所以只取文件名。
        path = self._covers_dir / Path(book.cover_path).name
        if not path.is_file():
            _logger.warning("export.cover_missing", book_id=book.id, path=str(path))
            return None

        media_type = _IMAGE_MEDIA_TYPES.get(path.suffix.lower())
        if media_type is None:
            _logger.warning("export.cover_unknown_type", book_id=book.id, suffix=path.suffix)
            return None

        return f"cover{path.suffix.lower()}", media_type, path.read_bytes()

    @staticmethod
    def _render_cover_xhtml(book: Book, image_name: str) -> str:
        title = escape(book.title)
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="zh-CN" lang="zh-CN">\n'
            "  <head>\n"
            f"    <title>{title}</title>\n"
            '    <link rel="stylesheet" type="text/css" href="style.css"/>\n'
            "  </head>\n"
            '  <body class="cover">\n'
            f'    <img src="{image_name}" alt="{title}"/>\n'
            "  </body>\n"
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

    def _render_opf(
        self,
        book: Book,
        book_id: str,
        manifest_items: list[str],
        spine_items: list[str],
        *,
        has_cover: bool = False,
    ) -> str:
        # **`dcterms:modified` 是「修改时间」**，按 EPUB3 规范必须存在。
        # 这里原先填的是 `created_at` —— 语义错了，改过来，另加 created。
        modified = _isoformat(book.updated_at)
        created = _isoformat(book.created_at)
        manifest = "\n".join(manifest_items)
        spine = "\n".join(spine_items)

        # 先把书籍自带的数据铺开，再让配置覆盖 —— **配置优先**。
        # 反过来（书籍优先）的话，「我在配置里写了却没生效」会很难排查。
        fields: dict[str, str] = {
            "title": book.title,
            "creator": book.author or "Unknown",
            "language": book.language or DEFAULT_LANGUAGE,
            "source": book.source_id,
        }
        if book.intro:
            fields["description"] = book.intro
        # `publisher` 不是 Book 的一等字段 —— 按 Source Spec §5.5，书源里
        # 除约定字段外的键都进 `metadata`，所以从那儿取。
        publisher = book.metadata.get("publisher")
        if publisher:
            fields["publisher"] = str(publisher)

        variables = book_variables(book)
        for key, template in (self._metadata_templates or {}).items():
            rendered = render_template(template, variables)
            if rendered:
                fields[key] = rendered

        # 顺序固定，输出才稳定（否则每次导出 OPF 都不同，diff 噪音大）
        meta_extra = "".join(
            f"    <dc:{key}>{escape(value)}</dc:{key}>\n"
            for key, value in sorted(fields.items())
            if key not in {"title", "creator", "language"}
        )
        # 这三个顺序固定放前面，阅读器和人眼都习惯先看到它们
        head_meta = "".join(
            f"    <dc:{key}>{escape(fields[key])}</dc:{key}>\n"
            for key in ("title", "creator", "language")
        )

        cover_meta = '    <meta name="cover" content="cover-image"/>\n' if has_cover else ""

        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
            'unique-identifier="bookid">\n'
            '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:identifier id="bookid">{book_id}</dc:identifier>\n'
            f"{head_meta}"
            f"{meta_extra}"
            f'    <meta property="dcterms:modified">{modified}</meta>\n'
            f'    <meta property="dcterms:created">{created}</meta>\n'
            # EPUB2 的老阅读器靠这条找封面（EPUB3 用 manifest 里的
            # properties="cover-image"）。两条都写，兼容性最好。
            f"{cover_meta}"
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
