# SPDX-License-Identifier: GPL-3.0-only
"""Fixture 测试运行器（``mog source test`` 的实现）。

这个工具解决的是 lint 查不出来的那类问题：规则能编译，但页面改版后
提取到空值。所以测试重点是「**提取为空要判失败**」，
而不是「代码跑没跑完」。

注意：所有会改文件的测试都在 ``tmp_source`` 这份**副本**上做。
一开始直接往共享的示例书源目录里写，一条用例把 ``cases.yaml`` 覆盖了，
后续测试全崩 —— 共享夹具只能读，不能写。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from mograb.domain.enums import SourceCapability
from mograb.domain.source import ExtractRule
from mograb.source import load_cases, load_source_file, run_cases
from mograb.source.fixture import FixtureCase, FixtureError, cases_path

pytestmark = pytest.mark.unit


@pytest.fixture
def tmp_source(example_source_dir: Path, tmp_path: Path) -> Path:
    """示例书源的**可写副本**。共享夹具一律只读。"""
    target = tmp_path / "example-source"
    shutil.copytree(example_source_dir, target)
    return target


def _write_cases(source_dir: Path, text: str) -> None:
    cases_path(source_dir).write_text(text, encoding="utf-8")


def _make_paged_source(source_dir: Path, pages: list[str]) -> None:
    """造一个会翻页的书源 + 对应快照，用来验「快照按请求顺序喂」。"""
    items = "".join(
        f'<div class="i"><a href="/b/{i}">第{i}章</a></div>' for i in range(1, len(pages) + 1)
    )
    pager = '<div class="pager"><a href="?p=next">下一页</a></div>'
    for index, name in enumerate(pages):
        body = items if index == 0 else ""
        next_link = pager if index < len(pages) - 1 else ""
        (source_dir / "fixtures" / name).write_text(
            f"<html><body>{body}{next_link}</body></html>", encoding="utf-8"
        )
    (source_dir / "source.yaml").write_text(
        "spec_version: 1\n"
        "id: paged\n"
        "name: Paged\n"
        "version: 1.0.0\n"
        "capabilities: [chapters]\n"
        "permissions: {network: [example.com]}\n"
        "chapters:\n"
        "  request: {url: '{{book.url}}'}\n"
        "  result:\n"
        "    list: '.i'\n"
        "    fields: {title: 'a@text', url: 'a@href'}\n"
        "    paginate: {next: '.pager a@href', max_pages: 5}\n",
        encoding="utf-8",
    )
    _write_cases(
        source_dir,
        "- capability: chapters\n"
        "  url: https://example.com/book/1\n"
        f"  files: [{', '.join(pages)}]\n",
    )


# ---------------------------------------------------------------------------
# 读取用例
# ---------------------------------------------------------------------------
class TestLoadCases:
    def test_读取示例书源的用例(self, example_source_dir: Path) -> None:
        cases = load_cases(example_source_dir)

        assert [c.capability for c in cases] == [
            SourceCapability.SEARCH,
            SourceCapability.BOOK,
            SourceCapability.CHAPTERS,
            SourceCapability.CONTENT,
        ]
        assert cases[0].keyword == "三体"
        assert cases[1].files == ["book.html"]

    def test_用例放在_fixtures_下(self, example_source_dir: Path) -> None:
        assert cases_path(example_source_dir).parent.name == "fixtures"

    def test_缺用例文件时报错并给出模板(self, tmp_path: Path) -> None:
        with pytest.raises(FixtureError) as exc:
            load_cases(tmp_path)

        assert "cases.yaml" in str(exc.value)
        assert "capability: book" in str(exc.value)  # 附了可照抄的模板

    def test_能力名非法(self, tmp_source: Path) -> None:
        _write_cases(tmp_source, "- capability: nope\n  url: https://x/\n  files: [book.html]\n")

        with pytest.raises(FixtureError, match="能力名非法"):
            load_cases(tmp_source)

    def test_缺_url(self, tmp_source: Path) -> None:
        _write_cases(tmp_source, "- capability: book\n  files: [book.html]\n")

        with pytest.raises(FixtureError, match="缺少 url"):
            load_cases(tmp_source)

    def test_缺_files(self, tmp_source: Path) -> None:
        _write_cases(tmp_source, "- capability: book\n  url: https://x/\n")

        with pytest.raises(FixtureError, match="没有声明 files"):
            load_cases(tmp_source)

    def test_引用了不存在的快照(self, tmp_source: Path) -> None:
        """早报比晚报好 —— 别等到跑起来才发现文件不在。"""
        _write_cases(tmp_source, "- capability: book\n  url: https://x/\n  files: [nope.html]\n")

        with pytest.raises(FixtureError, match="快照不存在"):
            load_cases(tmp_source)

    def test_files_可以写成单个字符串(self, tmp_source: Path) -> None:
        _write_cases(tmp_source, "- capability: book\n  url: https://x/\n  files: book.html\n")

        assert load_cases(tmp_source)[0].files == ["book.html"]

    def test_顶层不是列表(self, tmp_source: Path) -> None:
        _write_cases(tmp_source, "capability: book\n")

        with pytest.raises(FixtureError, match="应该是用例列表"):
            load_cases(tmp_source)


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
class TestRunCases:
    async def test_示例书源全通过(self, example_source_dir: Path) -> None:
        spec = load_source_file(example_source_dir / "source.yaml")

        results = await run_cases(spec, load_cases(example_source_dir), example_source_dir)

        assert [r.ok for r in results] == [True, True, True, True]
        assert "三体" in results[1].summary
        assert "3 章" in results[2].summary

    async def test_提取为空判失败(self, example_source_dir: Path) -> None:
        """**这是这个工具存在的理由。**

        选择器写错了 lint 是看不出来的 —— 它照样能编译，只是匹配不到东西。
        只有真跑一遍提取才知道。
        """
        spec = load_source_file(example_source_dir / "source.yaml")
        assert spec.book is not None
        # model_copy 不做校验，所以这里要自己给出 ExtractRule 而不是字符串
        broken = spec.model_copy(
            update={
                "book": spec.book.model_copy(
                    update={"fields": {"title": ExtractRule.parse(".不存在")}}
                )
            }
        )
        cases = [c for c in load_cases(example_source_dir) if c.capability is SourceCapability.BOOK]

        results = await run_cases(broken, cases, example_source_dir)

        assert results[0].ok is False
        assert "标题" in results[0].summary

    async def test_单条失败不影响其余(self, example_source_dir: Path) -> None:
        spec = load_source_file(example_source_dir / "source.yaml")
        cases = [
            case
            if case.capability is not SourceCapability.CONTENT
            # content 的规则套在搜索页快照上，必然提不出正文
            else FixtureCase(case.capability, case.url, ["search.html"])
            for case in load_cases(example_source_dir)
        ]

        results = await run_cases(spec, cases, example_source_dir)

        assert [r.ok for r in results] == [True, True, True, False]

    async def test_快照不够时报清楚(self, example_source_dir: Path) -> None:
        """分页书源会连着发请求，快照给少了要说清是第几个页面。"""
        spec = load_source_file(example_source_dir / "source.yaml")
        cases = [FixtureCase(SourceCapability.BOOK, "https://example.com/book/1001", [])]

        results = await run_cases(spec, cases, example_source_dir)

        assert results[0].ok is False
        assert "快照" in results[0].summary

    async def test_分页按请求顺序喂快照(self, tmp_source: Path) -> None:
        _make_paged_source(tmp_source, ["p1.html", "p2.html", "p3.html"])
        spec = load_source_file(tmp_source / "source.yaml")

        results = await run_cases(spec, load_cases(tmp_source), tmp_source)

        assert results[0].ok is True, results[0].summary
        assert "3 章" in results[0].summary

    async def test_快照多给不会出错(self, tmp_source: Path) -> None:
        """最后一页没有「下一页」时引擎会停，多余快照用不上也不该报错。"""
        _make_paged_source(tmp_source, ["p1.html", "p2.html"])
        spec = load_source_file(tmp_source / "source.yaml")

        results = await run_cases(spec, load_cases(tmp_source), tmp_source)

        assert results[0].ok is True
