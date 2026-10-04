# SPDX-License-Identifier: GPL-3.0-only
"""列表分页与来源级网络策略。

分页是写第一个真实站点书源时补上的：站点目录每页 100 章、翻页靠
``?page=N``，而原先的 ``chapters`` 只发一次请求 —— 1453 章的书只能取到
前 100 章，而且**不报错**。静默截断是这里最要防的事。

``network.headers`` / ``network.retry`` 则是另一类问题：规范里写了、
``NetworkPolicy`` 里声明了，但引擎从来没读过 —— 死配置。
"""

from __future__ import annotations

from typing import Any

import pytest

from mograb.domain.source import PaginationSpec, SourceSpec
from mograb.errors import SourceSchemaError
from mograb.source import engine as engine_module
from mograb.source import load_source_dict
from mograb.source.engine import SourceEngine

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 假的网络层
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, content: bytes, url: str) -> None:
        self.content = content
        self.encoding = "utf-8"
        self.status_code = 200
        self.url = url


class PagedFetcher:
    """按 URL 返回预设 HTML，并记录所有请求。"""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.calls: list[str] = []
        self.kwargs: list[dict[str, Any]] = []

    async def fetch(self, method: str, url: str, **kwargs: Any) -> Any:
        self.calls.append(url)
        self.kwargs.append(kwargs)
        if url not in self._pages:
            raise AssertionError(f"未预设的 URL: {url}")
        return FakeResponse(self._pages[url].encode("utf-8"), url)


def _item(title: str, href: str) -> str:
    return f'<div class="item"><a href="{href}">{title}</a></div>'


def _page(items: list[tuple[str, str]], next_href: str | None) -> str:
    body = "".join(_item(t, h) for t, h in items)
    pager = f'<div class="pager"><a href="{next_href}">下一页</a></div>' if next_href else ""
    return f"<html><body>{body}{pager}</body></html>"


def _pagination_source(paginate: dict[str, Any]) -> SourceSpec:
    """只声明 paginate 的书源，用来测 schema 校验。"""
    return load_source_dict(
        {
            "spec_version": 1,
            "id": "demo",
            "name": "Demo",
            "version": "1.0.0",
            "capabilities": ["chapters"],
            "permissions": {"network": ["site.test"]},
            "chapters": {
                "request": {"url": "https://site.test/book/1"},
                "result": {
                    "list": ".item",
                    "fields": {"title": "a@text", "url": "a@href"},
                    "paginate": paginate,
                },
            },
        }
    )


def _source(**overrides: Any) -> SourceSpec:
    data: dict[str, Any] = {
        "spec_version": 1,
        "id": "demo",
        "name": "Demo",
        "version": "1.0.0",
        "capabilities": ["chapters"],
        "permissions": {"network": ["site.test"]},
        "chapters": {
            "request": {"url": "https://site.test/book/1"},
            "result": {
                "list": ".item",
                "fields": {"title": "a@text", "url": "a@href"},
                "paginate": {"next": ".pager a@href", "max_pages": 5},
            },
        },
    }
    data.update(overrides)
    return load_source_dict(data)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class TestPaginationSchema:
    def test_不声明时是_None(self) -> None:
        spec = load_source_dict(
            {
                "spec_version": 1,
                "id": "demo",
                "name": "Demo",
                "version": "1.0.0",
                "capabilities": ["chapters"],
                "chapters": {
                    "request": {"url": "https://site.test/b"},
                    "result": {"list": ".i", "fields": {"title": ".t", "url": "a@href"}},
                },
            }
        )
        assert spec.chapters is not None
        assert spec.chapters.result.paginate is None

    def test_next_是必需的(self) -> None:
        with pytest.raises(SourceSchemaError):
            _pagination_source({"max_pages": 3})

    def test_max_pages_有下限(self) -> None:
        """1 页等于没分页，没有意义；上限则防止规则写错时无限抓。"""
        with pytest.raises(SourceSchemaError):
            _pagination_source({"next": ".pager a@href", "max_pages": 1})

    def test_max_pages_有上限(self) -> None:
        with pytest.raises(SourceSchemaError):
            _pagination_source({"next": ".pager a@href", "max_pages": 9999})

    def test_默认_max_pages(self) -> None:
        assert PaginationSpec(next="a@href").max_pages == 20


# ---------------------------------------------------------------------------
# 翻页循环
# ---------------------------------------------------------------------------
class TestPaginationLoop:
    async def test_单页时不翻(self) -> None:
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert [c.title for c in chapters] == ["甲"]
        assert len(fetcher.calls) == 1

    async def test_跟着下一页走并合并(self) -> None:
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], "/book/1?p=3"),
                "https://site.test/book/1?p=3": _page([("丙", "/3")], None),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert [c.title for c in chapters] == ["甲", "乙", "丙"]
        assert len(fetcher.calls) == 3

    async def test_序号跨页连续(self) -> None:
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1"), ("乙", "/2")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("丙", "/3")], None),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert [c.index for c in chapters] == [0, 1, 2]

    async def test_reverse_在全部页面之后才做(self) -> None:
        """逐页反转会把页序也翻掉。"""
        spec = _source(
            chapters={
                "request": {"url": "https://site.test/book/1"},
                "result": {
                    "list": ".item",
                    "fields": {"title": "a@text", "url": "a@href"},
                    "reverse": True,
                    "paginate": {"next": ".pager a@href", "max_pages": 5},
                },
            }
        )
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], None),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert [c.title for c in chapters] == ["乙", "甲"]

    async def test_下一页地址不再叠加首页参数(self) -> None:
        """站点给的链接就是该页的完整表述，再叠一次会出现 page=1&page=2。

        **必须是 None 而不是空 dict。** httpx 遇到 `params={}` 会先清掉 URL
        自带的查询串再赋空参数 —— 等于把 `?page=2` 抹掉、又抓回第一页。
        这个坑在真实站点上踩过，离线快照测不出来（假 fetcher 不看 params）。
        """
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], None),
            }
        )

        await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert fetcher.kwargs[1]["params"] is None

    async def test_首页参数原样保留(self) -> None:
        """第一页是书源自己拼的，params 该怎么传还怎么传。"""
        spec = _source(
            chapters={
                "request": {"url": "https://site.test/book/1", "query": {"sort": "0"}},
                "result": {
                    "list": ".item",
                    "fields": {"title": "a@text", "url": "a@href"},
                },
            }
        )
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert fetcher.kwargs[0]["params"] == {"sort": "0"}

    async def test_相对链接会补全(self) -> None:
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], None),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert len(chapters) == 2


class TestPaginationStops:
    async def test_没有下一页就停(self) -> None:
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert len(fetcher.calls) == 1

    async def test_下一页指向自己时停(self) -> None:
        """站点把「下一页」永远指回本页时会死循环，必须自己刹车。"""
        fetcher = PagedFetcher(
            {"https://site.test/book/1": _page([("甲", "/1")], "https://site.test/book/1")}
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert len(chapters) == 1
        assert len(fetcher.calls) == 1

    async def test_两页互相指向时停(self) -> None:
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], "/book/1"),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert len(chapters) == 2
        assert len(fetcher.calls) == 2

    async def test_到达_max_pages_就停并告警(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """**不能静默截断** —— 用户会以为整本书下完了。

        直接盯 ``engine._logger`` 而不是抓 stdout：structlog 是进程级配置，
        整套测试跑下来可能已经被别处改过渲染目标，抓输出会时灵时不灵。
        """
        warnings: list[tuple[str, dict[str, Any]]] = []

        class FakeLogger:
            def warning(self, event: str, **kw: Any) -> None:
                warnings.append((event, kw))

        monkeypatch.setattr(engine_module, "_logger", FakeLogger())

        spec = _source(
            chapters={
                "request": {"url": "https://site.test/book/1"},
                "result": {
                    "list": ".item",
                    "fields": {"title": "a@text", "url": "a@href"},
                    "paginate": {"next": ".pager a@href", "max_pages": 2},
                },
            }
        )
        # 每页都指向下一页，永远不会自然结束
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], "/book/1?p=3"),
            }
        )

        chapters = await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert len(chapters) == 2
        assert len(fetcher.calls) == 2
        assert [w[0] for w in warnings] == ["source.pagination_limit_reached"]
        assert warnings[0][1]["max_pages"] == 2

    async def test_死循环时告警(self, monkeypatch: pytest.MonkeyPatch) -> None:
        warnings: list[str] = []

        class FakeLogger:
            def warning(self, event: str, **kw: Any) -> None:
                warnings.append(event)

        monkeypatch.setattr(engine_module, "_logger", FakeLogger())
        fetcher = PagedFetcher(
            {
                "https://site.test/book/1": _page([("甲", "/1")], "/book/1?p=2"),
                "https://site.test/book/1?p=2": _page([("乙", "/2")], "/book/1"),
            }
        )

        await SourceEngine(fetcher).fetch_chapters(_source(), "https://site.test/book/1")

        assert warnings == ["source.pagination_loop_detected"]


class TestSearchPagination:
    async def test_搜索也能翻页(self) -> None:
        spec = load_source_dict(
            {
                "spec_version": 1,
                "id": "demo",
                "name": "Demo",
                "version": "1.0.0",
                "capabilities": ["search"],
                "permissions": {"network": ["site.test"]},
                "search": {
                    "request": {"url": "https://site.test/s", "query": {"q": "{{keyword}}"}},
                    "result": {
                        "list": ".item",
                        "fields": {"title": "a@text", "url": "a@href"},
                        "paginate": {"next": ".pager a@href", "max_pages": 5},
                    },
                },
            }
        )
        fetcher = PagedFetcher(
            {
                "https://site.test/s": _page([("甲", "/1")], "/s?p=2"),
                "https://site.test/s?p=2": _page([("乙", "/2")], None),
            }
        )

        results = await SourceEngine(fetcher).search(spec, "关键词")

        assert [r.title for r in results] == ["甲", "乙"]


# ---------------------------------------------------------------------------
# 来源级网络策略
# ---------------------------------------------------------------------------
class TestNetworkPolicyWiring:
    async def test_network_headers_会带上(self) -> None:
        spec = _source(network={"headers": {"Referer": "https://site.test/"}})
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert fetcher.kwargs[0]["headers"]["Referer"] == "https://site.test/"

    async def test_请求级_headers_覆盖来源级(self) -> None:
        """越具体的声明优先级越高。"""
        spec = _source(
            network={"headers": {"X-Trace": "network", "Referer": "https://site.test/"}},
            chapters={
                "request": {
                    "url": "https://site.test/book/1",
                    "headers": {"X-Trace": "request"},
                },
                "result": {
                    "list": ".item",
                    "fields": {"title": "a@text", "url": "a@href"},
                },
            },
        )
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        headers = fetcher.kwargs[0]["headers"]
        assert headers["X-Trace"] == "request"  # 被覆盖
        assert headers["Referer"] == "https://site.test/"  # 保留

    async def test_network_headers_支持模板变量(self) -> None:
        spec = _source(network={"headers": {"User-Agent": "{{user_agent}}"}})
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert "MoGrab" in fetcher.kwargs[0]["headers"]["User-Agent"]

    async def test_network_retry_会传下去(self) -> None:
        spec = _source(network={"retry": 7})
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert fetcher.kwargs[0]["max_retries"] == 7

    async def test_限速与并发也照书源的来(self) -> None:
        spec = _source(network={"concurrency": 3, "request_interval_ms": 1200})
        fetcher = PagedFetcher({"https://site.test/book/1": _page([("甲", "/1")], None)})

        await SourceEngine(fetcher).fetch_chapters(spec, "https://site.test/book/1")

        assert fetcher.kwargs[0]["concurrency"] == 3
        assert fetcher.kwargs[0]["min_interval"] == pytest.approx(1.2)
