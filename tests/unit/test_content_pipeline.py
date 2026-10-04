# SPDX-License-Identifier: GPL-3.0-only
"""内容清洗、规范化与校验测试（规划书 §21、§22）。"""

from __future__ import annotations

import pytest

from mograb.content.cleaner import clean_text
from mograb.content.normalizer import count_words, normalize_text, split_paragraphs
from mograb.content.pipeline import ContentPipeline, ContentPolicy
from mograb.errors import ContentValidationError

SAMPLE = (
    "汪淼觉得自己像一条被拎出水的鱼。\n"
    "他坐在办公桌前，面前摊着一份《三体》的游戏光盘。\n"
    "电话铃响了。\n"
    "他拿起听筒，听见史强的声音。"
)


class TestCleaner:
    def test_removes_residual_html(self) -> None:
        assert "<" not in clean_text("<p>正文</p>")

    def test_removes_zero_width_chars(self) -> None:
        assert clean_text("正\u200b文") == "正文"

    def test_removes_watermark_lines(self) -> None:
        text = "正文内容\n请记住本站：www.example.com\n更多正文"
        cleaned = clean_text(text)
        assert "请记住本站" not in cleaned
        assert "正文内容" in cleaned and "更多正文" in cleaned

    def test_removes_bare_domain_line(self) -> None:
        assert clean_text("正文\nwww.example.com\n正文2").count("正文") == 2

    def test_collapses_excess_blank_lines(self) -> None:
        assert "\n\n\n" not in clean_text("a\n\n\n\nb")


class TestNormalizer:
    def test_unifies_crlf(self) -> None:
        assert "\r" not in normalize_text("a\r\nb")

    def test_ideographic_space(self) -> None:
        assert normalize_text("a\u3000b") == "a b"

    def test_idempotent(self) -> None:
        once = normalize_text(SAMPLE)
        assert normalize_text(once) == once

    def test_split_paragraphs_by_blank_line(self) -> None:
        assert split_paragraphs("a\n\nb") == ["a", "b"]

    def test_split_paragraphs_by_newline_when_no_blank(self) -> None:
        assert split_paragraphs("a\nb") == ["a", "b"]

    def test_empty_input(self) -> None:
        assert split_paragraphs("") == []
        assert normalize_text("") == ""

    def test_count_words_counts_cjk(self) -> None:
        assert count_words("你好世界") == 4

    def test_count_words_mixed(self) -> None:
        assert count_words("你好 hello") == 3  # 2 CJK + 1 英文词


class TestPipelineValidation:
    def test_accepts_normal_content(self) -> None:
        pipeline = ContentPipeline()
        result = pipeline.process(SAMPLE)
        assert result.word_count > 0
        assert result.content_hash

    def test_rejects_empty(self) -> None:
        with pytest.raises(ContentValidationError) as exc:
            ContentPipeline().process("")
        assert exc.value.details["reason"] == "empty"

    def test_rejects_too_short(self) -> None:
        with pytest.raises(ContentValidationError) as exc:
            ContentPipeline(ContentPolicy(min_length=100)).process("太短了")
        assert exc.value.details["reason"] == "too_short"

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ContentValidationError) as exc:
            ContentPipeline(ContentPolicy(max_length=10)).process(SAMPLE)
        assert exc.value.details["reason"] == "too_long"

    def test_rejects_low_chinese_ratio(self) -> None:
        """纯英文页面（如导航/错误页）应被拒绝。"""
        english = (
            "Not Found The requested page does not exist on this server. "
            "Please check the address and try again later."
        )
        with pytest.raises(ContentValidationError) as exc:
            ContentPipeline().process(english)
        assert exc.value.details["reason"] == "low_chinese_ratio"

    def test_rejects_template_page(self) -> None:
        """重复行过多的模板页应被拒绝。"""
        text = "\n".join(["本页内容"] * 20)
        with pytest.raises(ContentValidationError) as exc:
            ContentPipeline().process(text)
        assert exc.value.details["reason"] == "high_repeat_ratio"

    def test_thresholds_are_configurable(self) -> None:
        """阈值可配置，而非硬编码（规划书 §22）。"""
        permissive = ContentPolicy(min_length=1, min_chinese_ratio=0.0)
        assert ContentPipeline(permissive).process("ok").text == "ok"
