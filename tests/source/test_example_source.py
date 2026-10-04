# SPDX-License-Identifier: GPL-3.0-only
"""书源 Fixture 测试（规划书 §12、§47）。

完全离线：用本地 HTML 快照替代真实网络，验证书源规则是否仍能正确提取。
网站改版后，可先用 fixture 复现问题，再修改规则。

运行::

    uv run pytest tests/source -v
    # 等价于 CLI 的： mog source test example --fixture
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mograb.domain.enums import SourceCapability
from mograb.source.engine import SourceEngine
from mograb.source.loader import load_source_file
from mograb.source.validator import lint

pytestmark = pytest.mark.source


class FixtureFetcher:
    """把 fixture 文件当作 HTTP 响应返回的假 Fetcher。

    匹配规则：取「URL 以某 key 结尾」中最长的 key，
    保证 ``/book/1001`` 与 ``/book/1001/chapter/1`` 不会混淆。
    """

    def __init__(self, mapping: dict[str, Path]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    async def fetch(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        matches = [(key, path) for key, path in self._mapping.items() if url.endswith(key)]
        if not matches:
            raise AssertionError(f"未为 URL 配置 fixture: {url}")
        _key, path = max(matches, key=lambda kv: len(kv[0]))
        return _Response(path.read_bytes(), url)


class _Response:
    def __init__(self, content: bytes, url: str) -> None:
        self.content = content
        self.encoding = "utf-8"
        self.status_code = 200
        self.url = url


@pytest.fixture
def example_spec(example_source_dir: Path):
    return load_source_file(example_source_dir / "source.yaml")


@pytest.fixture
def fetcher(example_fixtures_dir: Path) -> FixtureFetcher:
    return FixtureFetcher(
        {
            "search": example_fixtures_dir / "search.html",
            "book/1001": example_fixtures_dir / "book.html",
            "chapter/1": example_fixtures_dir / "chapter.html",
        }
    )


def test_source_declares_expected_capabilities(example_spec) -> None:
    for capability in (
        SourceCapability.SEARCH,
        SourceCapability.BOOK,
        SourceCapability.CHAPTERS,
        SourceCapability.CONTENT,
    ):
        assert example_spec.supports(capability)


def test_source_passes_lint(example_spec) -> None:
    report = lint(example_spec)
    assert report.is_ready, [d.format() for d in report.errors]


@pytest.mark.asyncio
async def test_search_fixture(example_spec, fetcher: FixtureFetcher) -> None:
    """Search: PASS —— 应解析出 3 条结果，且 URL 已补全为绝对地址。"""
    engine = SourceEngine(fetcher)
    results = await engine.search(example_spec, "三体")

    assert len(results) == 3
    assert results[0].title == "三体"
    assert results[0].author == "刘慈欣"
    assert results[0].url.startswith("https://example.com/")


@pytest.mark.asyncio
async def test_book_fixture(example_spec, fetcher: FixtureFetcher) -> None:
    """Book: PASS —— 应解析出标题、作者、简介与封面。"""
    engine = SourceEngine(fetcher)
    draft = await engine.fetch_book(example_spec, "https://example.com/book/1001")

    assert draft.title == "三体"
    assert draft.author == "刘慈欣"
    assert draft.source_book_id == "1001"
    assert draft.cover_url is not None


@pytest.mark.asyncio
async def test_chapters_fixture(example_spec, fetcher: FixtureFetcher) -> None:
    """Chapters: PASS —— 应解析出 3 章并保持顺序。"""
    engine = SourceEngine(fetcher)
    chapters = await engine.fetch_chapters(example_spec, "https://example.com/book/1001")

    assert len(chapters) == 3
    assert [c.index for c in chapters] == [0, 1, 2]
    assert chapters[0].title == "第一章 科学边界"
    assert chapters[0].source_chapter_id == "c1"
    assert chapters[0].url.startswith("https://example.com/")


@pytest.mark.asyncio
async def test_content_fixture(example_spec, fetcher: FixtureFetcher) -> None:
    """Content: PASS —— 正文应排除 script 与广告节点。"""
    engine = SourceEngine(fetcher)
    content = await engine.fetch_content(example_spec, "https://example.com/book/1001/chapter/1")

    assert "汪淼" in content
    assert "史强" in content
    assert "console.log" not in content  # script 已被移除
    assert "请记住本站" not in content  # 广告已被移除


@pytest.mark.asyncio
async def test_unsupported_capability_raises(example_spec) -> None:
    """能力守卫：未声明的能力必须立即失败（规划书 §9）。"""
    from mograb.errors import SourceUnsupportedError

    spec = example_spec.model_copy(update={"capabilities": [SourceCapability.SEARCH]})
    engine = SourceEngine(FixtureFetcher({}))
    with pytest.raises(SourceUnsupportedError):
        await engine.fetch_content(spec, "https://example.com/x")
