# SPDX-License-Identifier: GPL-3.0-only
"""章节身份与 URL 规范化测试（规划书 §6.3）。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from mograb.domain.chapter import Chapter, compute_content_hash, normalize_url

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class TestNormalizeUrl:
    def test_lowercases_scheme_and_host(self) -> None:
        assert normalize_url("HTTPS://Example.COM/Path") == "https://example.com/Path"

    def test_removes_default_port(self) -> None:
        assert normalize_url("https://example.com:443/a") == "https://example.com/a"
        assert normalize_url("http://example.com:80/a") == "http://example.com/a"

    def test_removes_fragment(self) -> None:
        assert normalize_url("https://example.com/a#sec1") == "https://example.com/a"

    def test_strips_tracking_params(self) -> None:
        url = "https://example.com/a?utm_source=x&from=share&id=7"
        assert normalize_url(url) == "https://example.com/a?id=7"

    def test_sorts_query_params(self) -> None:
        assert normalize_url("https://example.com/a?b=2&a=1") == "https://example.com/a?a=1&b=2"

    def test_strips_trailing_slash(self) -> None:
        assert normalize_url("https://example.com/a/") == "https://example.com/a"

    def test_keeps_root_slash(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_empty_input(self) -> None:
        assert normalize_url("") == ""

    def test_equivalent_urls_normalize_equal(self) -> None:
        """同一逻辑页面的不同写法必须归一为同一身份。"""
        a = normalize_url("https://Example.com/Book/12/?utm_source=q&b=2&a=1#x")
        b = normalize_url("https://example.com/Book/12?a=1&b=2")
        assert a == b


class TestContentHash:
    def test_stable_for_same_content(self) -> None:
        assert compute_content_hash("abc") == compute_content_hash("abc")

    def test_whitespace_insensitive(self) -> None:
        """仅空白差异不应被判定为内容变化。"""
        assert compute_content_hash("a  b\n\nc") == compute_content_hash("a b c")

    def test_detects_real_change(self) -> None:
        assert compute_content_hash("abc") != compute_content_hash("abd")


class TestChapterIdentity:
    def _make(self, **kwargs: object) -> Chapter:
        base = {
            "id": "c1",
            "book_id": "b1",
            "title": "第一章",
            "url": "https://example.com/1",
            "index": 0,
            "created_at": NOW,
            "updated_at": NOW,
        }
        base.update(kwargs)
        return Chapter(**base)  # type: ignore[arg-type]

    def test_prefers_source_chapter_id(self) -> None:
        chapter = self._make(source_chapter_id="sid-9")
        assert chapter.identity_key == "sid:sid-9"

    def test_falls_back_to_normalized_url(self) -> None:
        chapter = self._make(source_chapter_id=None)
        assert chapter.identity_key == "url:https://example.com/1"

    def test_falls_back_to_index_and_title(self) -> None:
        chapter = self._make(source_chapter_id=None, url="")
        assert chapter.identity_key == "idx:0:第一章"

    def test_url_variants_share_identity(self) -> None:
        a = self._make(source_chapter_id=None, url="https://example.com/1?utm_source=x")
        b = self._make(source_chapter_id=None, url="https://example.com/1")
        assert a.identity_key == b.identity_key

    def test_refresh_content_reports_change(self) -> None:
        chapter = self._make()
        assert chapter.refresh_content("正文") is True  # 首次写入视为变化
        assert chapter.refresh_content("正文") is False  # 内容未变
        assert chapter.refresh_content("新正文") is True  # 内容变化
        assert chapter.word_count == len("新正文")


@pytest.mark.unit
def test_identity_is_stable_across_instances() -> None:
    """相同输入的两个实例身份必须一致（去重的前提）。"""
    kwargs = {
        "id": "c1",
        "book_id": "b1",
        "title": "第一章",
        "url": "https://example.com/1",
        "index": 0,
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert Chapter(**kwargs).identity_key == Chapter(**kwargs).identity_key
