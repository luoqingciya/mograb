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


class TestEpubCover:
    """EPUB 要嵌入封面。

    这条链路以前整段是断的：书源解析了 `cover`、`Book` 有字段、表有列、
    `data/covers/` 目录也建了，但 `include_cover` 参数赋值后再没被读过，
    也没有任何代码去下载封面 —— 导出的 EPUB 从来没有封面。
    """

    def _with_cover(self, covers_dir: Path, book, *, suffix: str = ".jpg"):
        covers_dir.mkdir(parents=True, exist_ok=True)
        (covers_dir / f"{book.id}{suffix}").write_bytes(b"\xff\xd8\xff\xe0cover")
        return book.model_copy(update={"cover_path": f"covers/{book.id}{suffix}"})

    def test_封面进包且在首位(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        covers = tmp_path / "covers"
        book = self._with_cover(covers, sample_book)
        target = tmp_path / "book.epub"

        EpubExporter(covers_dir=covers)._write_epub(book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            names = zf.namelist()
            assert "OEBPS/cover.jpg" in names
            assert "OEBPS/cover.xhtml" in names

            opf = zf.read("OEBPS/content.opf").decode()
            # EPUB3 靠 manifest 的 properties 找封面
            assert 'properties="cover-image"' in opf
            # EPUB2 的老阅读器靠这条
            assert '<meta name="cover" content="cover-image"/>' in opf
            # 封面页要排在章节前面 —— 打开先看到封面
            assert opf.index('idref="cover"') < opf.index('idref="ch1"')

    def test_没有封面也能导出(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        """**封面是可选资产** —— 站点没给就不该让导出失败。"""
        target = tmp_path / "book.epub"

        EpubExporter(covers_dir=tmp_path / "covers")._write_epub(
            sample_book, sample_chapters, target
        )

        with zipfile.ZipFile(target) as zf:
            assert "OEBPS/cover.xhtml" not in zf.namelist()
            opf = zf.read("OEBPS/content.opf").decode()
            assert "cover-image" not in opf
            assert 'idref="ch1"' in opf

    def test_文件不在时静默跳过(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        """`cover_path` 有值但文件被删了 —— 数据目录被手工动过。"""
        covers = tmp_path / "covers"
        covers.mkdir()
        book = sample_book.model_copy(update={"cover_path": "covers/不存在.jpg"})
        target = tmp_path / "book.epub"

        EpubExporter(covers_dir=covers)._write_epub(book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            assert "OEBPS/cover.xhtml" not in zf.namelist()

    def test_include_cover_False_时跳过(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        covers = tmp_path / "covers"
        book = self._with_cover(covers, sample_book)
        target = tmp_path / "book.epub"

        EpubExporter(covers_dir=covers, include_cover=False)._write_epub(
            book, sample_chapters, target
        )

        with zipfile.ZipFile(target) as zf:
            assert "OEBPS/cover.xhtml" not in zf.namelist()

    def test_png_封面用对的_media_type(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        covers = tmp_path / "covers"
        book = self._with_cover(covers, sample_book, suffix=".png")
        target = tmp_path / "book.epub"

        EpubExporter(covers_dir=covers)._write_epub(book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            opf = zf.read("OEBPS/content.opf").decode()
            assert 'href="cover.png" media-type="image/png"' in opf


class TestEpubMetadata:
    """OPF 里的元数据语义要对。"""

    def test_modified_用_updated_at(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        """**这条原先写错了。**

        `dcterms:modified` 按 EPUB3 是「修改时间」，而实现填的是
        `created_at`。两个时间不一样时才能验出来，所以这里特意错开。
        """
        from datetime import UTC, datetime, timedelta

        created = datetime(2026, 1, 1, tzinfo=UTC)
        updated = created + timedelta(days=7)
        book = sample_book.model_copy(update={"created_at": created, "updated_at": updated})
        target = tmp_path / "book.epub"

        EpubExporter()._write_epub(book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            opf = zf.read("OEBPS/content.opf").decode()
            assert '<meta property="dcterms:modified">2026-01-08' in opf
            assert '<meta property="dcterms:created">2026-01-01' in opf

    def test_publisher_从_metadata_取(self, tmp_path: Path, sample_book, sample_chapters) -> None:
        """`publisher` 不是 Book 的一等字段 —— 按 Source Spec §5.5 进 metadata。"""
        book = sample_book.model_copy(update={"metadata": {"publisher": "某某出版社"}})
        target = tmp_path / "book.epub"

        EpubExporter()._write_epub(book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            assert (
                "<dc:publisher>某某出版社</dc:publisher>" in zf.read("OEBPS/content.opf").decode()
            )

    def test_没有_publisher_就不写那一行(
        self, tmp_path: Path, sample_book, sample_chapters
    ) -> None:
        target = tmp_path / "book.epub"

        EpubExporter()._write_epub(sample_book, sample_chapters, target)

        with zipfile.ZipFile(target) as zf:
            assert "dc:publisher" not in zf.read("OEBPS/content.opf").decode()


class TestMetadataTemplates:
    """`[output.metadata]` —— 规范 §27 说的「允许用户通过模板配置」。"""

    def _opf(self, tmp_path: Path, book, chapters, templates) -> str:
        target = tmp_path / "book.epub"
        EpubExporter(metadata_templates=templates)._write_epub(book, chapters, target)
        with zipfile.ZipFile(target) as zf:
            return zf.read("OEBPS/content.opf").decode()

    def test_补充新字段(self, tmp_path, sample_book, sample_chapters) -> None:
        opf = self._opf(
            tmp_path,
            sample_book,
            sample_chapters,
            {"rights": "仅供个人阅读"},
        )

        assert "<dc:rights>仅供个人阅读</dc:rights>" in opf

    def test_值支持模板变量(self, tmp_path, sample_book, sample_chapters) -> None:
        opf = self._opf(
            tmp_path,
            sample_book,
            sample_chapters,
            {"subject": "{{author}} 作品"},
        )

        assert "<dc:subject>刘慈欣 作品</dc:subject>" in opf

    def test_配置覆盖书籍自带的数据(self, tmp_path, sample_book, sample_chapters) -> None:
        """**配置优先。** 反过来（书籍优先）的话「写了却没生效」很难排查。"""
        book = sample_book.model_copy(update={"metadata": {"publisher": "书籍自带的"}})

        opf = self._opf(tmp_path, book, sample_chapters, {"publisher": "配置里的"})

        assert "<dc:publisher>配置里的</dc:publisher>" in opf
        assert "书籍自带的" not in opf

    def test_认不出的变量渲染成空(self, tmp_path, sample_book, sample_chapters) -> None:
        """和文件名模板一致：认不出的变量换成空串，然后整行被省略。

        （空值不写进 OPF —— 留个 `<dc:subject></dc:subject>` 没有意义，
        见 `test_空值不写那一行`。）
        """
        opf = self._opf(tmp_path, sample_book, sample_chapters, {"subject": "{{没有这个}}"})

        assert "dc:subject" not in opf

    def test_变量混在文本里(self, tmp_path, sample_book, sample_chapters) -> None:
        opf = self._opf(tmp_path, sample_book, sample_chapters, {"subject": "{{author}}/{{title}}"})

        assert "<dc:subject>刘慈欣/三体</dc:subject>" in opf

    def test_空值不写那一行(self, tmp_path, sample_book, sample_chapters) -> None:
        """模板渲染成空串说明用户没打算写它，不该留个空标签。"""
        opf = self._opf(tmp_path, sample_book, sample_chapters, {"subject": ""})

        assert "dc:subject" not in opf

    def test_转义_XML(self, tmp_path, sample_book, sample_chapters) -> None:
        """值里有 `&` `<` 会生成非法 XML。"""
        opf = self._opf(tmp_path, sample_book, sample_chapters, {"rights": "A & B <C>"})

        assert "<dc:rights>A &amp; B &lt;C&gt;</dc:rights>" in opf

    def test_不配置时不写额外字段(self, tmp_path, sample_book, sample_chapters) -> None:
        opf = self._opf(tmp_path, sample_book, sample_chapters, {})

        assert "dc:rights" not in opf
        assert "dc:subject" not in opf


class TestMetadataConfigValidation:
    """键名要在**配置阶段**就拦下来。

    不拦的话，一个手滑的键名会生成非法 XML，而报错出现在
    「导出之后阅读器打不开」那里，离真正的原因很远。
    """

    def test_合法键(self) -> None:
        from mograb.config.settings import OutputSettings

        settings = OutputSettings(metadata={"publisher": "x", "subject-2": "y"})

        assert settings.metadata == {"publisher": "x", "subject-2": "y"}

    @pytest.mark.parametrize("bad", ["Publisher", "有中文", "has space", "2start", ""])
    def test_非法键被拒(self, bad: str) -> None:
        from mograb.config.settings import OutputSettings

        with pytest.raises(ValueError, match="不合法"):
            OutputSettings(metadata={bad: "x"})

    def test_identifier_被拒(self) -> None:
        """它决定「阅读器认为这是不是同一本书」，不能随便覆盖。"""
        from mograb.config.settings import OutputSettings

        with pytest.raises(ValueError, match="identifier 不可配置"):
            OutputSettings(metadata={"identifier": "x"})
