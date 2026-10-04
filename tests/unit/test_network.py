# SPDX-License-Identifier: GPL-3.0-only
"""网络层测试：缓存键、重试策略、限流器、HTTP 客户端。

客户端部分用 httpx.MockTransport，不产生真实网络请求。
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from mograb.errors import (
    HttpStatusError,
    NetworkError,
    RateLimitedError,
    SourceExecutionError,
    TimeoutError_,
)
from mograb.network.cache import (
    TTL_DEFAULT,
    CacheEntry,
    build_cache_key,
    make_entry,
)
from mograb.network.client import HttpClient, HttpClientConfig
from mograb.network.limiter import GlobalLimiter, SourceLimiter, SourceLimiterRegistry
from mograb.network.retry import RetryPolicy

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 缓存键
# ---------------------------------------------------------------------------
class TestCacheKey:
    def test_same_input_same_key(self) -> None:
        kw = {"source_id": "s", "method": "GET", "url": "https://a.com/x"}
        assert build_cache_key(**kw) == build_cache_key(**kw)

    def test_different_source_different_key(self) -> None:
        """不同书源不能共用缓存 —— 规则不同，结果可能不同。"""
        a = build_cache_key(source_id="a", method="GET", url="https://x.com/1")
        b = build_cache_key(source_id="b", method="GET", url="https://x.com/1")
        assert a != b

    def test_different_method_different_key(self) -> None:
        a = build_cache_key(source_id="s", method="GET", url="https://x.com/1")
        b = build_cache_key(source_id="s", method="POST", url="https://x.com/1")
        assert a != b

    def test_body_affects_key(self) -> None:
        a = build_cache_key(source_id="s", method="POST", url="https://x.com", body="a")
        b = build_cache_key(source_id="s", method="POST", url="https://x.com", body="b")
        assert a != b

    def test_tracking_params_do_not_affect_key(self) -> None:
        """追踪参数被规范化掉，不应产生不同缓存键。"""
        a = build_cache_key(source_id="s", method="GET", url="https://x.com/1?utm_source=q")
        b = build_cache_key(source_id="s", method="GET", url="https://x.com/1")
        assert a == b

    def test_relevant_header_flag_affects_key(self) -> None:
        a = build_cache_key(source_id="s", method="GET", url="https://x.com", headers={})
        b = build_cache_key(
            source_id="s", method="GET", url="https://x.com", headers={"Cookie": "x=1"}
        )
        assert a != b

    def test_key_is_hex(self) -> None:
        key = build_cache_key(source_id="s", method="GET", url="https://x.com")
        assert len(key) == 32
        int(key, 16)  # 不是合法十六进制会抛错


class TestCacheEntry:
    def test_make_entry_sets_ttl(self) -> None:
        entry = make_entry(
            key="k",
            source_id="s",
            url="u",
            status_code=200,
            content=b"x",
            encoding="utf-8",
            ttl_seconds=60,
        )
        assert entry.expires_at > entry.created_at
        assert not entry.is_expired

    def test_size(self) -> None:
        entry = make_entry(
            key="k", source_id="s", url="u", status_code=200, content=b"12345", encoding=None
        )
        assert entry.size == 5

    def test_default_ttl_is_positive(self) -> None:
        assert TTL_DEFAULT > 0


class MemoryCache:
    """测试用的内存缓存，实现 HttpCache 协议。"""

    def __init__(self) -> None:
        self.store: dict[str, CacheEntry] = {}
        self.puts = 0

    async def get(self, key: str) -> CacheEntry | None:
        entry = self.store.get(key)
        if entry is None or entry.is_expired:
            return None
        return entry

    async def put(self, entry: CacheEntry) -> None:
        self.puts += 1
        self.store[entry.key] = entry

    async def invalidate_url(self, source_id: str, url: str) -> int:
        keys = [k for k, v in self.store.items() if v.source_id == source_id and v.url == url]
        for k in keys:
            del self.store[k]
        return len(keys)

    async def invalidate_source(self, source_id: str) -> int:
        keys = [k for k, v in self.store.items() if v.source_id == source_id]
        for k in keys:
            del self.store[k]
        return len(keys)

    async def clear(self) -> int:
        n = len(self.store)
        self.store.clear()
        return n

    async def stats(self) -> dict[str, int]:
        return {"entries": len(self.store)}


# ---------------------------------------------------------------------------
# 重试策略
# ---------------------------------------------------------------------------
class TestRetryPolicy:
    def test_exponential_backoff(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter=0.0, max_delay=100.0)
        assert policy.delay_for(0) == 1.0
        assert policy.delay_for(1) == 2.0
        assert policy.delay_for(2) == 4.0
        assert policy.delay_for(3) == 8.0

    def test_respects_max_delay(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter=0.0, max_delay=5.0)
        assert policy.delay_for(10) == 5.0

    def test_jitter_stays_in_range(self) -> None:
        policy = RetryPolicy(base_delay=10.0, jitter=0.25, max_delay=100.0)
        for _ in range(50):
            delay = policy.delay_for(0)
            assert 7.5 <= delay <= 12.5

    def test_retry_after_takes_priority(self) -> None:
        policy = RetryPolicy(base_delay=1.0, jitter=0.0)
        assert policy.delay_for(0, retry_after=30.0) == 30.0

    def test_retry_after_capped_by_max_delay(self) -> None:
        policy = RetryPolicy(max_delay=10.0)
        assert policy.delay_for(0, retry_after=300.0) == 10.0

    def test_should_retry_respects_max_retries(self) -> None:
        policy = RetryPolicy(max_retries=2)
        error = NetworkError("x")
        assert policy.should_retry(error, 0) is True
        assert policy.should_retry(error, 1) is True
        assert policy.should_retry(error, 2) is False

    def test_should_retry_follows_retryable_flag(self) -> None:
        policy = RetryPolicy(max_retries=3)
        from mograb.errors import ParseError, SourceSchemaError

        assert policy.should_retry(NetworkError("x"), 0) is True
        assert policy.should_retry(ParseError("x"), 0) is False
        assert policy.should_retry(SourceSchemaError("x"), 0) is False

    def test_5xx_retryable_4xx_not(self) -> None:
        assert HttpStatusError("x", status_code=503).retryable is True
        assert HttpStatusError("x", status_code=429).retryable is True
        assert HttpStatusError("x", status_code=404).retryable is False

    def test_non_mograb_error_not_retried(self) -> None:
        policy = RetryPolicy(max_retries=3)
        assert policy.should_retry(ValueError("x"), 0) is False

    def test_retry_after_extraction(self) -> None:
        policy = RetryPolicy()
        assert policy.retry_after_of(RateLimitedError("x", retry_after=12.0)) == 12.0
        assert policy.retry_after_of(NetworkError("x")) is None


# ---------------------------------------------------------------------------
# 限流
# ---------------------------------------------------------------------------
class TestSourceLimiter:
    async def test_limits_concurrency(self) -> None:
        limiter = SourceLimiter(concurrency=2, min_interval=0.0)
        active = 0
        peak = 0

        async def worker() -> None:
            nonlocal active, peak
            async with limiter.slot():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[worker() for _ in range(8)])
        assert peak <= 2

    async def test_min_interval_enforced(self) -> None:
        """两次请求之间要满足最小间隔。

        Windows 的定时器精度约 15ms，asyncio.sleep 可能提前返回，所以断言
        留了余量：3 次调用之间有 2 个 0.1s 间隔，期望 0.2s，只要求 >= 0.12s。
        """
        limiter = SourceLimiter(concurrency=1, min_interval=0.1)
        start = time.monotonic()
        for _ in range(3):
            async with limiter.slot():
                pass
        assert time.monotonic() - start >= 0.12

    async def test_releases_on_exception(self) -> None:
        limiter = SourceLimiter(concurrency=1, min_interval=0.0)
        with pytest.raises(RuntimeError):
            async with limiter.slot():
                raise RuntimeError("boom")
        # 槽位应已释放，否则这里会卡住
        async with limiter.slot():
            pass


class TestGlobalLimiter:
    async def test_limits_concurrency(self) -> None:
        limiter = GlobalLimiter(concurrency=2)
        active = 0
        peak = 0

        async def worker() -> None:
            nonlocal active, peak
            async with limiter.slot():
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*[worker() for _ in range(6)])
        assert peak <= 2


class TestSourceLimiterRegistry:
    async def test_same_source_returns_same_limiter(self) -> None:
        registry = SourceLimiterRegistry()
        a = await registry.get("s1", concurrency=2)
        b = await registry.get("s1", concurrency=2)
        assert a is b

    async def test_different_sources_isolated(self) -> None:
        """规划书 §15 的核心要求：不同来源不能共用限流器。"""
        registry = SourceLimiterRegistry()
        a = await registry.get("s1", concurrency=2)
        b = await registry.get("s2", concurrency=5)
        assert a is not b
        assert a.concurrency == 2
        assert b.concurrency == 5

    async def test_global_limiter_shared(self) -> None:
        registry = SourceLimiterRegistry()
        assert registry.global_limiter is registry.global_limiter


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------
def make_client(handler, **config_kwargs) -> HttpClient:
    transport = httpx.MockTransport(handler)
    raw = httpx.AsyncClient(transport=transport)
    return HttpClient(HttpClientConfig(**config_kwargs), client=raw)


class TestHttpClientFetch:
    async def test_successful_get(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"<p>ok</p>")

        async with make_client(handler) as client:
            result = await client.fetch("GET", "https://example.com/a")
        assert result.status_code == 200
        assert result.content == b"<p>ok</p>"
        assert result.from_cache is False

    async def test_cache_hit_skips_transport(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url)
            return httpx.Response(200, content=b"cached")

        cache = MemoryCache()
        async with make_client(handler) as client:
            client._cache = cache  # 测试注入
            await client.fetch("GET", "https://example.com/a", source_id="s")
            second = await client.fetch("GET", "https://example.com/a", source_id="s")

        assert len(calls) == 1
        assert second.from_cache is True

    async def test_cache_disabled(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(200, content=b"x")

        cache = MemoryCache()
        async with make_client(handler) as client:
            client._cache = cache
            await client.fetch("GET", "https://e.com/a", use_cache=False)
            await client.fetch("GET", "https://e.com/a", use_cache=False)
        assert len(calls) == 2

    async def test_429_raises_rate_limited(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "7"})

        async with make_client(handler, retry=RetryPolicy(max_retries=0)) as client:
            with pytest.raises(RateLimitedError) as exc:
                await client.fetch("GET", "https://example.com/a")
        assert exc.value.retry_after == 7.0

    async def test_404_raises_http_status_not_retryable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        async with make_client(handler, retry=RetryPolicy(max_retries=0)) as client:
            with pytest.raises(HttpStatusError) as exc:
                await client.fetch("GET", "https://example.com/a")
        assert exc.value.status_code == 404
        assert exc.value.retryable is False

    async def test_5xx_is_retried(self) -> None:
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            if len(attempts) < 3:
                return httpx.Response(503)
            return httpx.Response(200, content=b"recovered")

        policy = RetryPolicy(max_retries=3, base_delay=0.0, jitter=0.0)
        async with make_client(handler, retry=policy) as client:
            result = await client.fetch("GET", "https://example.com/a")
        assert len(attempts) == 3
        assert result.content == b"recovered"

    async def test_timeout_maps_to_timeout_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout")

        async with make_client(handler, retry=RetryPolicy(max_retries=0)) as client:
            with pytest.raises(TimeoutError_):
                await client.fetch("GET", "https://example.com/a")

    async def test_connection_error_maps_to_network_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with make_client(handler, retry=RetryPolicy(max_retries=0)) as client:
            with pytest.raises(NetworkError):
                await client.fetch("GET", "https://example.com/a")

    async def test_domain_allowlist_blocks_other_hosts(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x")

        async with make_client(handler, allow_domains=frozenset({"example.com"})) as client:
            with pytest.raises(SourceExecutionError):
                await client.fetch("GET", "https://evil.com/a", source_id="s")

    async def test_domain_allowlist_permits_subdomain(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x")

        async with make_client(handler, allow_domains=frozenset({"example.com"})) as client:
            result = await client.fetch("GET", "https://m.example.com/a", source_id="s")
        assert result.status_code == 200

    async def test_empty_allowlist_permits_all(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x")

        async with make_client(handler) as client:
            result = await client.fetch("GET", "https://anything.com/a")
        assert result.status_code == 200


class TestMaxRetriesOverride:
    """书源用 ``network.retry`` 声明的重试次数要真的生效。

    这个字段以前是死的：``NetworkPolicy`` 里声明了、规范里写了、
    官方参考书源也配了，但引擎从来没把它传下去 —— 静默无效。
    """

    async def test_默认用全局策略(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503)

        policy = RetryPolicy(max_retries=2, base_delay=0.0, jitter=0.0)
        async with make_client(handler, retry=policy) as client:
            with pytest.raises(HttpStatusError):
                await client.fetch("GET", "https://example.com/a")

        assert len(calls) == 3  # 首次 + 2 次重试

    async def test_覆盖全局策略(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503)

        policy = RetryPolicy(max_retries=5, base_delay=0.0, jitter=0.0)
        async with make_client(handler, retry=policy) as client:
            with pytest.raises(HttpStatusError):
                await client.fetch("GET", "https://example.com/a", max_retries=1)

        assert len(calls) == 2  # 首次 + 1 次重试

    async def test_零次重试(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(503)

        policy = RetryPolicy(max_retries=5, base_delay=0.0, jitter=0.0)
        async with make_client(handler, retry=policy) as client:
            with pytest.raises(HttpStatusError):
                await client.fetch("GET", "https://example.com/a", max_retries=0)

        assert len(calls) == 1

    async def test_只改次数不改退避曲线(self) -> None:
        """书源不该管退避算法，所以 base_delay 仍用全局配置。"""
        policy = RetryPolicy(max_retries=5, base_delay=0.0, jitter=0.0)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async with make_client(handler, retry=policy) as client:
            with pytest.raises(HttpStatusError):
                await client.fetch("GET", "https://example.com/a", max_retries=1)

        assert client._config.retry.max_retries == 5  # 全局配置没被改


class TestEncodingDetection:
    def _response(self, content: bytes, headers: dict[str, str] | None = None) -> httpx.Response:
        return httpx.Response(200, content=content, headers=headers or {})

    def test_from_content_type_header(self) -> None:
        resp = self._response(b"x", {"Content-Type": "text/html; charset=gbk"})
        assert HttpClient._detect_encoding(resp) == "gb18030"

    def test_from_meta_charset(self) -> None:
        html = b'<html><head><meta charset="gb2312"></head></html>'
        assert HttpClient._detect_encoding(self._response(html)) == "gb18030"

    def test_from_meta_http_equiv(self) -> None:
        html = b'<meta http-equiv="Content-Type" content="text/html; charset=big5">'
        assert HttpClient._detect_encoding(self._response(html)) == "big5"

    def test_defaults_to_utf8(self) -> None:
        assert HttpClient._detect_encoding(self._response(b"<html></html>")) == "utf-8"

    def test_header_wins_over_meta(self) -> None:
        html = b'<meta charset="gbk">'
        resp = self._response(html, {"Content-Type": "text/html; charset=utf-8"})
        assert HttpClient._detect_encoding(resp) == "utf-8"


class TestHttpClientLifecycle:
    async def test_close_is_idempotent(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        client = make_client(handler)
        async with client:
            pass
        await client.aclose()

    async def test_fetch_without_context_raises(self) -> None:
        client = HttpClient(HttpClientConfig(retry=RetryPolicy(max_retries=0)))
        with pytest.raises(NetworkError):
            await client.fetch("GET", "https://example.com")

    async def test_external_client_not_closed(self) -> None:
        """外部传入的 client 不该被我们关掉。"""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200)

        raw = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = HttpClient(HttpClientConfig(), client=raw)
        async with client:
            pass
        assert raw.is_closed is False
        await raw.aclose()
