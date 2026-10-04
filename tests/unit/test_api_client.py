# SPDX-License-Identifier: GPL-3.0-only
"""CLI 的本地 API 客户端。

这些分支要「server 返回了某个状态码」才能走到，起真 server 太重，
所以把 httpx 换成一个假的。测的是客户端自己的判断，不是 httpx 的行为。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from mograb.config import ensure_token, get_paths, load_settings
from mograb_cli.commands import _api
from mograb_cli.commands._api import (
    ApiUnauthorized,
    ApiUnavailable,
    auth_headers,
    is_running,
    request,
)

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", text: str = "") -> None:
        self.status_code = status_code
        self.content = content
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://127.0.0.1/x"),
                response=httpx.Response(self.status_code),
            )

    def json(self) -> Any:
        return json.loads(self.content)


class FakeClient:
    """顶替 httpx.AsyncClient。"""

    def __init__(self, outcome: FakeResponse | Exception) -> None:
        self._outcome = outcome

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def _result(self) -> FakeResponse:
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome

    async def request(self, *args: object, **kwargs: object) -> FakeResponse:
        return await self._result()

    async def get(self, *args: object, **kwargs: object) -> FakeResponse:
        return await self._result()


def install(monkeypatch: pytest.MonkeyPatch, outcome: FakeResponse | Exception) -> None:
    client = FakeClient(outcome)
    monkeypatch.setattr(
        _api,
        "httpx",
        SimpleNamespace(HTTPError=httpx.HTTPError, AsyncClient=lambda **kwargs: client),
    )


class TestAuthHeaders:
    def test_carries_bearer_token(self) -> None:
        headers = auth_headers()

        assert headers["Authorization"] == f"Bearer {ensure_token(get_paths())}"

    def test_token_is_ascii(self) -> None:
        """请求头必须是 ASCII —— httpx 对非 ASCII 会直接抛错。"""
        auth_headers()["Authorization"].encode("ascii")


class TestRequest:
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeResponse(200, content=b'{"a": 1}'))

        assert await request(load_settings(), "GET", "/tasks") == {"a": 1}

    async def test_empty_body_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeResponse(204))

        assert await request(load_settings(), "DELETE", "/sources/x") is None

    async def test_401_becomes_api_unauthorized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """令牌不对要单独报，不能混进「连不上」里。"""
        install(monkeypatch, FakeResponse(401, text="unauthorized"))

        with pytest.raises(ApiUnauthorized):
            await request(load_settings(), "GET", "/tasks")

    async def test_other_errors_propagate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeResponse(404, content=b"{}"))

        with pytest.raises(httpx.HTTPStatusError):
            await request(load_settings(), "GET", "/tasks/nope")

    async def test_connection_failure_becomes_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        install(monkeypatch, httpx.ConnectError("连不上"))

        with pytest.raises(ApiUnavailable):
            await request(load_settings(), "GET", "/tasks")


class TestIsRunning:
    async def test_true_on_200(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeResponse(200))

        assert await is_running(load_settings()) is True

    async def test_false_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, FakeResponse(500))

        assert await is_running(load_settings()) is False

    async def test_false_when_unreachable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        install(monkeypatch, httpx.ConnectError("连不上"))

        assert await is_running(load_settings()) is False
