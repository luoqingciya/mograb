# SPDX-License-Identifier: GPL-3.0-only
"""引擎把 ``book.fields`` 映射到 :class:`BookDraft` 的规则。

盯两件事：

1. ``status`` 字段要经 :meth:`BookStatus.parse` 转成枚举，
   而不是被当成自定义字段塞进 ``extra``；
2. 规范之外的字段进 ``extra``，不会丢掉。

这两条以前都是断的：``BookDraft`` 里根本没有 ``status``，
而 ``extra`` 引擎收集了却没人消费。
"""

from __future__ import annotations

from typing import Any

import pytest

from mograb.domain.enums import BookStatus
from mograb.source import load_source_dict
from mograb.source.engine import SourceEngine

pytestmark = pytest.mark.unit

BOOK_URL = "https://site.test/book/1"


class _Response:
    def __init__(self, html: str) -> None:
        self.content = html.encode("utf-8")
        self.encoding = "utf-8"
        self.status_code = 200


class StubFetcher:
    def __init__(self, html: str) -> None:
        self._html = html

    async def fetch(self, method: str, url: str, **kwargs: Any) -> _Response:
        return _Response(self._html)


def make_source(fields: dict[str, Any]) -> Any:
    return load_source_dict(
        {
            "spec_version": 1,
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "capabilities": ["book"],
            "permissions": {"network": ["site.test"]},
            "book": {
                "request": {"url": "{{book.url}}"},
                "fields": fields,
            },
        }
    )


HTML = """
<html><body>
  <h1>测试书</h1>
  <span class="state">已完结</span>
  <span class="cat">玄幻奇幻</span>
</body></html>
"""


async def fetch(fields: dict[str, Any]) -> Any:
    spec = make_source(fields)
    return await SourceEngine(StubFetcher(HTML)).fetch_book(spec, BOOK_URL)


class TestStatusField:
    async def test_已完结映射成枚举(self) -> None:
        draft = await fetch({"title": "h1", "status": ".state"})

        assert draft.status is BookStatus.COMPLETED

    async def test_连载映射成枚举(self) -> None:
        spec = make_source({"title": "h1", "status": ".state"})
        engine = SourceEngine(
            StubFetcher('<html><body><h1>书</h1><span class="state">连载中</span></body></html>')
        )

        draft = await engine.fetch_book(spec, BOOK_URL)

        assert draft.status is BookStatus.ONGOING

    async def test_没声明就是_UNKNOWN(self) -> None:
        draft = await fetch({"title": "h1"})

        assert draft.status is BookStatus.UNKNOWN

    async def test_认不出来的值不影响登记(self) -> None:
        """状态解析失败不该让整本书抓不下来。"""
        spec = make_source({"title": "h1", "status": ".state"})
        engine = SourceEngine(
            StubFetcher('<html><body><h1>书</h1><span class="state">???</span></body></html>')
        )

        draft = await engine.fetch_book(spec, BOOK_URL)

        assert draft.title == "书"
        assert draft.status is BookStatus.UNKNOWN

    async def test_status_不进_extra(self) -> None:
        """它是已知字段，不该重复出现在自定义字段里。"""
        draft = await fetch({"title": "h1", "status": ".state"})

        assert "status" not in draft.extra


class TestExtraFields:
    async def test_规范外的字段进_extra(self) -> None:
        draft = await fetch({"title": "h1", "category": ".cat"})

        assert draft.extra == {"category": "玄幻奇幻"}

    async def test_已知字段不进_extra(self) -> None:
        draft = await fetch({"title": "h1", "author": ".cat", "intro": ".cat", "cover": ".cat"})

        assert draft.extra == {}
