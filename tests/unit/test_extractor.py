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

# JSON API 的典型信封：{code, msg, data:{page, size, list, count}}
JSON_PAYLOAD = {
    "code": 200,
    "msg": "成功",
    "data": {
        "page": 1,
        "count": 32245,
        "list": [
            {"id": 52027, "title": "苍蓝星", "author": "Dr莫比乌斯", "imgUrl": "https://cdn/x.jpg"},
            {"id": 49972, "title": "剑来", "author": "烽火戏诸侯", "imgUrl": "https://cdn/y.jpg"},
        ],
    },
}

JSON_FIELDS = {
    "title": "jsonpath:$.title",
    "author": "jsonpath:$.author",
    "url": "jsonpath:$.imgUrl",
}


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


class TestJsonListExtraction:
    """JSON 响应的列表提取。

    以前这里是坏的：``extract_many`` 写死了 ``tree.cssselect``，JSONPath 传进去
    直接抛 ``SelectorSyntaxError``。于是 ``format: json`` 只有单值能用
    （``extract_one`` 走 JSONPath 提取器是好的），**列表型能力
    （``search`` / ``chapters``）完全做不了** —— 任何 JSON API 书源都卡在这。
    """

    @pytest.fixture
    def json_doc(self) -> Document:
        import json

        return Document(
            raw=json.dumps(JSON_PAYLOAD, ensure_ascii=False).encode("utf-8"),
            encoding="utf-8",
            kind="json",
        )

    def _rows(self, doc: Document, list_expr: str) -> list[dict[str, str | None]]:
        return extract_many(
            doc,
            ExtractRule.parse(list_expr),
            {k: ExtractRule.parse(v) for k, v in JSON_FIELDS.items()},
        )

    def test_星号写法(self, json_doc: Document) -> None:
        rows = self._rows(json_doc, "jsonpath:$.data.list[*]")

        assert [r["title"] for r in rows] == ["苍蓝星", "剑来"]
        assert rows[0]["author"] == "Dr莫比乌斯"
        assert rows[0]["url"] == "https://cdn/x.jpg"

    def test_不带星号也能取列表(self, json_doc: Document) -> None:
        """匹配到数组时按元素展开 —— `$.data.list` 更贴近「取列表」的直觉。"""
        rows = self._rows(json_doc, "jsonpath:$.data.list")

        assert [r["title"] for r in rows] == ["苍蓝星", "剑来"]

    def test_字段规则作用于列表项内部(self, json_doc: Document) -> None:
        """下钻语义：``$.title`` 取的是「该项的 title」，不是整份文档的。"""
        rows = self._rows(json_doc, "jsonpath:$.data.list[*]")

        assert rows[1]["title"] == "剑来"

    def test_未命中的字段是_None(self, json_doc: Document) -> None:
        rows = extract_many(
            json_doc,
            ExtractRule.parse("jsonpath:$.data.list[*]"),
            {"nope": ExtractRule.parse("jsonpath:$.not_there")},
        )
        assert [r["nope"] for r in rows] == [None, None]

    def test_空列表返回空(self) -> None:
        import json

        doc = Document(
            raw=json.dumps({"data": {"list": []}}).encode("utf-8"),
            encoding="utf-8",
            kind="json",
        )
        assert self._rows(doc, "jsonpath:$.data.list[*]") == []

    def test_中文不被转义(self, json_doc: Document) -> None:
        """下钻时重新序列化要保证中文可读，否则字段值会变成 \\uXXXX。"""
        rows = self._rows(json_doc, "jsonpath:$.data.list[*]")

        assert "\\u" not in str(rows[0]["title"])


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
