# SPDX-License-Identifier: GPL-3.0-only
"""提取器测试（规划书 §8.2）。"""

from __future__ import annotations

import pytest

from mograb.domain.source import ExtractRule
from mograb.source.extractor import Document, extract_many, extract_one

HTML = """
<html><body>
  <div class="book-item">
    <a href="/book/1"><span class="title">三体</span></a>
    <span class="author">刘慈欣</span>
  </div>
  <div class="book-item">
    <a href="/book/2"><span class="title">球状闪电</span></a>
    <span class="author">刘慈欣</span>
  </div>
</body></html>
"""


@pytest.fixture
def doc() -> Document:
    return Document(raw=HTML.encode("utf-8"), encoding="utf-8", kind="html")


class TestCssExtraction:
    def test_text_extraction(self, doc: Document) -> None:
        assert extract_one(doc, ExtractRule.parse(".book-item .title")) == "三体"

    def test_attribute_extraction(self, doc: Document) -> None:
        assert extract_one(doc, ExtractRule.parse(".book-item a@href")) == "/book/1"

    def test_missing_selector_returns_none(self, doc: Document) -> None:
        assert extract_one(doc, ExtractRule.parse(".nope")) is None

    def test_whitespace_normalized(self) -> None:
        doc = Document(raw=b"<p class='x'>  a \n  b  </p>")
        assert extract_one(doc, ExtractRule.parse(".x")) == "a b"


class TestListExtraction:
    def test_extract_many_rows(self, doc: Document) -> None:
        rows = extract_many(
            doc,
            ExtractRule.parse(".book-item"),
            {
                "title": ExtractRule.parse(".title"),
                "author": ExtractRule.parse(".author"),
                "url": ExtractRule.parse("a@href"),
            },
        )
        assert len(rows) == 2
        assert rows[0]["title"] == "三体"
        assert rows[0]["url"] == "/book/1"
        assert rows[1]["title"] == "球状闪电"

    def test_relative_rule_applies_to_item(self, doc: Document) -> None:
        """``a@href`` 必须作用于列表项内部，而非整个文档。"""
        rows = extract_many(
            doc,
            ExtractRule.parse(".book-item"),
            {"url": ExtractRule.parse("a@href")},
        )
        assert [r["url"] for r in rows] == ["/book/1", "/book/2"]

    def test_missing_field_yields_none(self, doc: Document) -> None:
        rows = extract_many(
            doc,
            ExtractRule.parse(".book-item"),
            {"nope": ExtractRule.parse(".not-exist")},
        )
        assert all(r["nope"] is None for r in rows)


class TestOtherRuleTypes:
    def test_jsonpath(self) -> None:
        doc = Document(raw=b'{"data":[{"t":"a"},{"t":"b"}]}', kind="json")
        rule = ExtractRule.parse("jsonpath:$.data[*].t")
        assert extract_one(doc, rule) == "a"

    def test_regex(self) -> None:
        doc = Document(raw="第1章 开始\n第2章 继续".encode())
        rule = ExtractRule.parse(r"regex:第(\d+)章")
        assert extract_one(doc, rule) == "1"

    def test_xpath(self, doc: Document) -> None:
        rule = ExtractRule.parse("xpath://span[@class='author']")
        assert extract_one(doc, rule) == "刘慈欣"


class TestEncoding:
    def test_gb18030_content(self) -> None:
        raw = "<p class='x'>中文测试</p>".encode("gb18030")
        doc = Document(raw=raw, encoding="gb18030")
        assert extract_one(doc, ExtractRule.parse(".x")) == "中文测试"
