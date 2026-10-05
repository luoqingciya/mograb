# SPDX-License-Identifier: GPL-3.0-only
"""封面下载与存储的测试。

封面是**可选资产**：站点没给、CDN 挂了、书源没把 CDN 域名写进白名单 ——
都会发生。所以这里覆盖的重点不是「怎么下成功」，而是
**每种拿不到的情况下都不该炸，也不该让下载任务失败**。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mograb.config.paths import get_paths
from mograb.covers import MAX_COVER_BYTES, CoverStore
from mograb.domain.book import Book
from mograb.errors import NetworkError
from mograb.network import HttpResult

pytestmark = pytest.mark.unit

NOW = datetime(2026, 1, 1, tzinfo=UTC)
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def make_book(*, cover_url: str | None = "https://cdn.example.com/c.jpg", **overrides) -> Book:
    data = {
        "id": "book_1",
        "source_id": "demo",
        "source_book_id": "1",
        "url": "https://example.com/book/1",
        "title": "测试书",
        "cover_url": cover_url,
        "created_at": NOW,
        "updated_at": NOW,
    }
    data.update(overrides)
    return Book(**data)


class FakeHttp:
    """只实现 CoverStore 用到的那一小块。"""

    def __init__(
        self,
        *,
        content: bytes = JPEG,
        headers: dict[str, str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.content = content
        self.headers = headers if headers is not None else {"content-type": "image/jpeg"}
        self.error = error
        self.calls: list[dict] = []

    async def fetch(self, method: str, url: str, **kwargs: object) -> HttpResult:
        self.calls.append({"method": method, "url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return HttpResult(
            content=self.content, encoding=None, status_code=200, url=url, headers=self.headers
        )


@pytest.fixture
def paths(tmp_path: Path):
    result = get_paths(tmp_path)
    result.ensure()
    return result


def make_store(http: FakeHttp, paths) -> CoverStore:
    return CoverStore(http=http, paths=paths)  # type: ignore[arg-type]


class TestFetchSuccess:
    async def test_下载并返回相对路径(self, paths) -> None:
        http = FakeHttp()
        store = make_store(http, paths)

        relative = await store.ensure(make_book())

        assert relative == "covers/book_1.jpg"
        assert (paths.covers_dir / "book_1.jpg").read_bytes() == JPEG

    async def test_相对路径能拼回真实文件(self, paths) -> None:
        """`cover_path` 记的是**相对数据目录**的路径 —— 数据目录整个拷走还能对上。"""
        store = make_store(FakeHttp(), paths)

        relative = await store.ensure(make_book())

        assert relative is not None
        assert (paths.root / relative).is_file()

    async def test_域名白名单透传(self, paths) -> None:
        """封面请求同样受 `permissions.network` 约束 —— 不能给它开后门。"""
        http = FakeHttp()
        store = make_store(http, paths)

        await store.ensure(make_book(), allowed_domains=["example.com", "cdn.example.com"])

        assert http.calls[0]["allowed_domains"] == ["example.com", "cdn.example.com"]
        assert http.calls[0]["source_id"] == "demo"

    async def test_没有后缀的_URL_看_ContentType(self, paths) -> None:
        """站点常用 `/img?id=123` 这种没有后缀的地址。"""
        http = FakeHttp(headers={"content-type": "image/png; charset=binary"})
        store = make_store(http, paths)

        relative = await store.ensure(make_book(cover_url="https://cdn.example.com/img?id=1"))

        assert relative == "covers/book_1.png"

    async def test_换后缀时清掉旧文件(self, paths) -> None:
        """站点把 jpg 换成 png 之后不该同时留着两份。"""
        (paths.covers_dir / "book_1.jpg").write_bytes(b"old")
        http = FakeHttp(headers={"content-type": "image/png"})
        store = make_store(http, paths)

        relative = await store.ensure(make_book())

        assert relative == "covers/book_1.png"
        assert not (paths.covers_dir / "book_1.jpg").exists()


class TestFetchSkipped:
    async def test_已有封面就不重复下载(self, paths) -> None:
        http = FakeHttp()
        store = make_store(http, paths)

        relative = await store.ensure(make_book(cover_path="covers/book_1.jpg"))

        assert relative == "covers/book_1.jpg"
        assert http.calls == []

    async def test_没有_cover_url_时什么都不做(self, paths) -> None:
        """站点没给封面 —— 这是正常情况，不是错误。"""
        http = FakeHttp()
        store = make_store(http, paths)

        assert await store.ensure(make_book(cover_url=None)) is None
        assert http.calls == []


class TestFetchFailure:
    """**每一条都不该抛异常。** 封面拿不到不该让整本书下载失败。"""

    async def test_域名被白名单拦下(self, paths) -> None:
        """最常见的一种：封面在 CDN 上，书源只声明了主站域名。"""
        http = FakeHttp(error=NetworkError("域名 cdn.example.com 不在允许列表内"))
        store = make_store(http, paths)

        assert await store.ensure(make_book()) is None

    async def test_网络错误(self, paths) -> None:
        store = make_store(FakeHttp(error=NetworkError("连接超时")), paths)

        assert await store.ensure(make_book()) is None

    async def test_太大就不存(self, paths) -> None:
        """防止它变成一个「往任意 URL 下载大文件」的口子。"""
        http = FakeHttp(content=b"x" * (MAX_COVER_BYTES + 1))
        store = make_store(http, paths)

        assert await store.ensure(make_book()) is None
        assert not list(paths.covers_dir.iterdir())

    async def test_认不出格式(self, paths) -> None:
        http = FakeHttp(headers={"content-type": "text/html"})
        store = make_store(http, paths)

        assert await store.ensure(make_book(cover_url="https://cdn.example.com/x")) is None

    async def test_失败时不留下半截文件(self, paths) -> None:
        store = make_store(FakeHttp(error=NetworkError("挂了")), paths)

        await store.ensure(make_book())

        assert not list(paths.covers_dir.iterdir())
