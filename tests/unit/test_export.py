# SPDX-License-Identifier: GPL-3.0-only
"""导出层测试（规划书 §26、§27、§28、§40）。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mograb.errors import UnsafePathError
from mograb.export import get_exporter, supported_formats
from mograb.export.base import render_filename, safe_path, sanitize_component
from mograb.export.epub import MIMETYPE, EpubExporter
from mograb.export.markdown import MarkdownExporter
from mograb.export.txt import TxtExporter


class TestFilenameTemplate:
    def test_default_template(self, sample_book) -> None:
        assert render_filename("{{author}} - {{title}}", book=sample_book) == "刘慈欣 - 三体"

    def test_missing_author_falls_back(self, sample_book) -> None:
        book = sample_book.model_copy(update={"author": None})
        assert render_filename("{{author}} - {{title}}", book=book) == "unknown - 三体"

    def test_chapter_variables(self, sample_book, sample_chapters) -> None:
        result = render_filename(
            "{{index}}. {{chapter_title}}", book=sample_book, chapter=sample_chapters[0]
        )
        assert result == "1. 第1章 测试章节"

    def test_illegal_chars_sanitized(self, sample_book) -> None:
        book = sample_book.model_copy(update={"title": 'a/b:c*d?e"f'})
        assert "/" not in render_filename("{{title}}", book=book)


class TestSanitize:
    def test_strips_path_separators(self) -> None:
        assert "/" not in sanitize_component("a/b")
        assert "\\" not in sanitize_component("a\\b")

    def test_handles_reserved_name(self) -> None:
        assert sanitize_component("CON") == "_CON"

    def test_empty_becomes_untitled(self) -> None:
        assert sanitize_component("   ") == "untitled"

    def test_length_capped(self) -> None:
        assert len(sanitize_component("x" * 500)) <= 150


class TestSafePath:
    def test_normal_join(self, tmp_path: Path) -> None:
        result = safe_path(tmp_path, "作者", "书名")
        assert result.parent.name == "作者"
        assert result.name == "书名"

    def test_rejects_traversal(self, tmp_path: Path) -> None:
        """路径穿越必须被拒绝（规划书 §40.6）。"""
        with pytest.raises(UnsafePathError):
            safe_path(tmp_path, "..", "..", "etc")

    def test_rejects_separator_in_component(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafePathError):
            safe_path(tmp_path, "../evil")

    def test_rejects_dot_components(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafePathError):
            safe_path(tmp_path, ".")

    def test_sanitize_then_join_is_lenient(self, tmp_path: Path) -> None:
        """宽容路径：先 sanitize 再拼接，得到安全结果。"""
        result = safe_path(tmp_path, sanitize_component("../evil"), "x")
        assert result.is_relative_to(tmp_path.resolve())


class TestTxtExporter:
    def test_render_contains_title_and_body(self, sample_book, sample_chapters) -> None:
        content = TxtExporter().render(sample_book, sample_chapters)
        assert "三体" in content
        assert "第1章 测试章节" in content
        assert sample_chapters[0].content in content

    @pytest.mark.asyncio
    async def test_export_writes_file(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        target = tmp_path / "out.txt"
        result = await TxtExporter().export(sample_book, sample_chapters, target)
        assert target.is_file()
        assert result.chapter_count == 3
        assert result.size_bytes > 0


class TestMarkdownExporter:
    def test_render_uses_headings(self, sample_book, sample_chapters) -> None:
        content = MarkdownExporter().render(sample_book, sample_chapters)
        assert content.startswith("# 三体")
        assert "## 第1章 测试章节" in content


class TestEpubExporter:
    def test_structure_is_valid(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        """EPUB 必须包含规范结构，且 mimetype 为第一个未压缩条目。"""
        target = tmp_path / "book.epub"
        EpubExporter()._write_epub(sample_book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            assert names[0] == "mimetype"
            assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
            assert zf.read("mimetype").decode() == MIMETYPE
            assert "META-INF/container.xml" in names
            assert "OEBPS/content.opf" in names
            assert "OEBPS/toc.xhtml" in names
            assert "OEBPS/toc.ncx" in names
            assert "OEBPS/chapter_0001.xhtml" in names

            opf = zf.read("OEBPS/content.opf").decode()
            assert "三体" in opf
            assert "刘慈欣" in opf
            assert "zh-CN" in opf

    @pytest.mark.asyncio
    async def test_export_async(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        target = tmp_path / "async.epub"
        result = await EpubExporter().export(sample_book, sample_chapters, target)
        assert target.is_file()
        assert result.chapter_count == 3


class TestExporterRegistry:
    @pytest.mark.parametrize("fmt", ["txt", "markdown", "md", "epub"])
    def test_get_exporter(self, fmt: str) -> None:
        assert get_exporter(fmt) is not None

    def test_unknown_format_raises(self) -> None:
        from mograb.errors import ExportError

        with pytest.raises(ExportError):
            get_exporter("pdf")

    def test_supported_formats(self) -> None:
        assert set(supported_formats()) == {"txt", "markdown", "epub"}
