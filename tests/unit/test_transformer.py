# SPDX-License-Identifier: GPL-3.0-only
"""变换流水线测试（规划书 §8.3）。"""

from __future__ import annotations

import pytest

from mograb.domain.source import Transform
from mograb.errors import SourceExecutionError
from mograb.source.transformer import apply_transforms, apply_transforms_many


def _t(op: str, **kwargs: object) -> Transform:
    return Transform.model_validate({"op": op, **kwargs})


class TestSingleTransforms:
    def test_trim(self) -> None:
        assert apply_transforms("  x  ", [_t("trim")]) == "x"

    def test_normalize_whitespace(self) -> None:
        assert apply_transforms("a   b\n c", [_t("normalize_whitespace")]) == "a b c"

    def test_remove_html(self) -> None:
        assert apply_transforms("<b>粗</b>体", [_t("remove_html")]) == "粗体"

    def test_replace(self) -> None:
        result = apply_transforms("a-b", [_t("replace", pattern="-", replacement="_")])
        assert result == "a_b"

    def test_regex_replace(self) -> None:
        result = apply_transforms("a1b22c", [_t("regex_replace", pattern=r"\d+", replacement="#")])
        assert result == "a#b#c"

    def test_prepend_append(self) -> None:
        assert apply_transforms("x", [_t("prepend", value=">>")]) == ">>x"
        assert apply_transforms("x", [_t("append", value="<<")]) == "x<<"

    def test_default_fills_empty(self) -> None:
        assert apply_transforms(None, [_t("default", value="未知")]) == "未知"
        assert apply_transforms("", [_t("default", value="未知")]) == "未知"
        assert apply_transforms("有值", [_t("default", value="未知")]) == "有值"

    def test_url_join(self) -> None:
        result = apply_transforms(
            "/book/1", [_t("url_join")], base_url="https://example.com/search"
        )
        assert result == "https://example.com/book/1"

    def test_url_join_requires_base(self) -> None:
        with pytest.raises(SourceExecutionError):
            apply_transforms("/book/1", [_t("url_join")], base_url=None)

    def test_none_passes_through(self) -> None:
        assert apply_transforms(None, [_t("trim")]) is None


class TestPipelineOrder:
    def test_transforms_apply_in_declared_order(self) -> None:
        """声明顺序决定执行顺序：先去标签再折叠空白。"""
        result = apply_transforms(
            "<p>  a   b  </p>",
            [_t("remove_html"), _t("normalize_whitespace")],
        )
        assert result == "a b"

    def test_empty_pipeline_is_identity(self) -> None:
        assert apply_transforms("x", []) == "x"


class TestManyTransforms:
    def test_applies_to_every_field(self) -> None:
        rows = [{"title": "  三体  ", "author": " 刘慈欣 "}]
        out = apply_transforms_many(rows, [_t("trim")])
        assert out == [{"title": "三体", "author": "刘慈欣"}]

    def test_no_transforms_returns_same(self) -> None:
        rows = [{"title": "x"}]
        assert apply_transforms_many(rows, []) == rows
