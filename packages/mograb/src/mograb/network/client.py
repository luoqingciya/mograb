# SPDX-License-Identifier: GPL-3.0-only
"""HttpClient —— 统一网络出入口（规划书 §14）。

调用链::

    Source Engine
         ↓
    HttpClient（本模块）
         ↓  Cache 命中则直接返回
    SourceLimiter（按书源隔离）
         ↓
    RetryPolicy（指数退避 + 抖动）
         ↓
    httpx.AsyncClient
         ↓
    Network

安全约束（规划书 §40）：

- 日志中的 ``Cookie`` / ``Authorization`` / ``Set-Cookie`` 一律脱敏。
- 默认只允许访问书源 ``permissions.network`` 白名单内的域名。
- 编码自动探测（覆盖 GBK/GB18030 站点），书源可用 ``encoding`` 覆盖。
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from ..errors import HttpStatusError, NetworkError, RateLimitedError, TimeoutError_
from ..logging.setup import get_logger, redact_headers
from .cache import TTL_DEFAULT, HttpCache, build_cache_key, make_entry
from .limiter import SourceLimiterRegistry
from .retry import RetryPolicy

_logger = get_logger(__name__)

# 从 HTML meta 中探测编码
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)""", re.IGNORECASE
)
_META_HTTP_EQUIV_RE = re.compile(
    rb"""<meta[^>]+content\s*=\s*["'][^"']*charset\s*=\s*([a-zA-Z0-9_\-]+)""",
    re.IGNORECASE,
)

# 中文站点常见编码别名
_ENCODING_ALIASES = {
    "gb2312": "gb18030",  # gb2312 是 gb18030 的子集，用超集解码更安全
    "gbk": "gb18030",
}


@dataclass(slots=True)
class HttpResult:
    """网络层返回结果（实现 :class:`~mograb.source.engine.ResponseLike`）。"""

    content: bytes
    encoding: str | None
    status_code: int
    url: str
    from_cache: bool = False
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HttpClientConfig:
    """客户端配置。"""

    timeout_ms: int = 15_000
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    verify_ssl: bool = True
    proxy: str | None = None
    """显式代理地址，如 ``http://127.0.0.1:7890``。

    留 ``None`` 时 httpx 仍会读环境变量（``HTTP_PROXY`` / ``HTTPS_PROXY`` /
    ``ALL_PROXY``）—— ``trust_env`` 没关。两条路都能用，配置项优先级更高。
    """

    user_agent: str | None = None
    max_redirects: int = 5
    allow_domains: frozenset[str] = field(default_factory=frozenset)


class HttpClient:
    """异步 HTTP 客户端，集成缓存 / 限流 / 重试。

    使用方式::

        async with HttpClient(config, cache=cache, limiters=registry) as client:
            resp = await client.fetch("GET", url, source_id="example")
    """

    def __init__(
        self,
        config: HttpClientConfig | None = None,
        *,
        cache: HttpCache | None = None,
        limiters: SourceLimiterRegistry | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or HttpClientConfig()
        self._cache = cache
        self._limiters = limiters or SourceLimiterRegistry()
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> HttpClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=self._config.max_redirects,
                verify=self._config.verify_ssl,
                proxy=self._config.proxy,
                timeout=self._config.timeout_ms / 1000,
            )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """关闭底层连接池。"""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def fetch(
        self,
        method: str,
        url: str,
        *,
        source_id: str = "unknown",
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        data: Any = None,
        cookies: dict[str, str] | None = None,
        encoding: str | None = None,
        timeout_ms: int | None = None,
        use_cache: bool = True,
        ttl_seconds: int | None = None,
        allowed_domains: Collection[str] | None = None,
        concurrency: int | None = None,
        min_interval: float | None = None,
        max_retries: int | None = None,
    ) -> HttpResult:
        """执行请求，自动应用缓存 / 限流 / 重试。

        Args:
            allowed_domains: 本次请求允许访问的域名。书源执行时会传自己的
                ``permissions.network``，这样「书源声明了什么就只能访问什么」
                在运行时真的成立，而不只是靠 linter 静态检查。
            concurrency: 该来源的并发上限。首次为该来源建限流器时生效，
                之后沿用。不传则用注册表的默认值。
            min_interval: 该来源两次请求之间的最小间隔（秒）。
            max_retries: 覆盖全局重试次数。书源用 ``network.retry`` 声明，
                不传则用 :class:`HttpClientConfig` 里的策略。

        Raises:
            NetworkError: 网络层失败（可重试子类由 RetryPolicy 处理）。
            HttpStatusError: 非 2xx。
        """
        self._assert_domain_allowed(url, source_id, allowed_domains)

        cache_key: str | None = None
        if use_cache and self._cache is not None:
            cache_key = build_cache_key(
                source_id=source_id, method=method, url=url, body=data, headers=headers
            )
            entry = await self._cache.get(cache_key)
            if entry is not None:
                return HttpResult(
                    content=entry.content,
                    encoding=entry.encoding,
                    status_code=entry.status_code,
                    url=url,
                    from_cache=True,
                )

        result = await self._fetch_with_retry(
            method,
            url,
            source_id=source_id,
            headers=headers,
            params=params,
            data=data,
            cookies=cookies,
            encoding=encoding,
            timeout_ms=timeout_ms,
            concurrency=concurrency,
            min_interval=min_interval,
            max_retries=max_retries,
        )

        if cache_key is not None and self._cache is not None and result.status_code == 200:
            await self._cache.put(
                make_entry(
                    key=cache_key,
                    source_id=source_id,
                    url=url,
                    status_code=result.status_code,
                    content=result.content,
                    encoding=result.encoding,
                    ttl_seconds=ttl_seconds if ttl_seconds is not None else TTL_DEFAULT,
                )
            )

        return result

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    async def _fetch_with_retry(self, method: str, url: str, **kwargs: Any) -> HttpResult:
        """带重试的请求执行。"""
        source_id = kwargs.get("source_id", "unknown")
        policy: RetryPolicy = self._config.retry
        # 书源可以用 network.retry 覆盖重试次数；只换 max_retries，
        # 退避曲线仍用全局配置 —— 书源不该管退避算法。
        override = kwargs.get("max_retries")
        if override is not None:
            policy = replace(policy, max_retries=override)
        # 限流器按来源缓存，所以第一次请求带过来的策略会被沿用
        limiter = await self._limiters.get(
            source_id,
            concurrency=kwargs.get("concurrency"),
            min_interval=kwargs.get("min_interval"),
        )

        attempt = 0
        while True:
            try:
                async with self._limiters.global_limiter.slot(), limiter.slot():
                    return await self._do_request(method, url, **kwargs)
            except Exception as exc:
                error = self._classify(exc)
                if not policy.should_retry(error, attempt):
                    raise error from exc
                delay = policy.delay_for(attempt, retry_after=policy.retry_after_of(error))
                _logger.warning(
                    "http.retry",
                    source_id=source_id,
                    url=url,
                    attempt=attempt + 1,
                    delay=round(delay, 2),
                    error=error.code,
                )
                import asyncio

                await asyncio.sleep(delay)
                attempt += 1

    async def _do_request(self, method: str, url: str, **kwargs: Any) -> HttpResult:
        """执行单次请求。"""
        if self._client is None:
            raise NetworkError("HttpClient 未初始化，请使用 async with")

        headers = dict(kwargs.get("headers") or {})
        if self._config.user_agent and "User-Agent" not in headers:
            headers["User-Agent"] = self._config.user_agent

        _logger.debug(
            "http.request",
            method=method,
            url=url,
            source_id=kwargs.get("source_id"),
            headers=redact_headers(headers),
        )

        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                params=kwargs.get("params"),
                data=kwargs.get("data"),
                cookies=kwargs.get("cookies"),
                timeout=(kwargs.get("timeout_ms") or self._config.timeout_ms) / 1000,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError_(f"请求超时: {url}", details={"url": url}) from exc
        except httpx.HTTPError as exc:
            raise NetworkError(f"网络错误: {url} ({exc})", details={"url": url}) from exc

        if response.status_code == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            raise RateLimitedError(
                f"被限流 (429): {url}", retry_after=retry_after, details={"url": url}
            )
        if response.status_code >= 400:
            raise HttpStatusError(
                f"HTTP {response.status_code}: {url}",
                status_code=response.status_code,
                details={"url": url},
            )

        encoding = kwargs.get("encoding") or self._detect_encoding(response)
        return HttpResult(
            content=response.content,
            encoding=encoding,
            status_code=response.status_code,
            url=str(response.url),
            headers=dict(response.headers),
        )

    @staticmethod
    def _detect_encoding(response: httpx.Response) -> str:
        """探测响应编码，优先顺序：响应头 > meta charset > 默认 utf-8。

        对 gb2312/gbk 统一提升为 gb18030，避免生僻字解码失败。
        """
        candidates: list[str] = []
        content_type = response.headers.get("Content-Type", "")
        if "charset=" in content_type:
            candidates.append(content_type.split("charset=")[-1].split(";")[0].strip())

        head = response.content[:4096]
        for pattern in (_META_CHARSET_RE, _META_HTTP_EQUIV_RE):
            match = pattern.search(head)
            if match:
                candidates.append(match.group(1).decode("ascii", errors="ignore"))

        for candidate in candidates:
            normalized = candidate.strip().lower().strip("\"'")
            if normalized:
                return _ENCODING_ALIASES.get(normalized, normalized)

        return "utf-8"

    @staticmethod
    def _classify(exc: BaseException) -> NetworkError:
        """把底层异常归类为 MoGrabError。"""
        from ..errors import MoGrabError

        if isinstance(exc, MoGrabError):
            return exc  # type: ignore[return-value]
        return NetworkError(str(exc))

    def _assert_domain_allowed(
        self,
        url: str,
        source_id: str,
        allowed_domains: Collection[str] | None = None,
    ) -> None:
        """校验目标域名。

        两道白名单都要过：

        - ``config.allow_domains``：部署方设的全局限制（可留空）
        - ``allowed_domains``：本次请求所属书源声明的 ``permissions.network``

        第二道是关键 —— 书源写了「只访问 example.com」，运行时就得真的只能
        访问 example.com，否则那份声明只是摆设。
        """
        from urllib.parse import urlsplit

        host = urlsplit(url).hostname or ""

        for allowed in (self._config.allow_domains, frozenset(allowed_domains or ())):
            if not allowed:
                continue
            if any(host == domain or host.endswith(f".{domain}") for domain in allowed):
                continue

            from ..errors import SourceExecutionError

            raise SourceExecutionError(
                f"域名 {host} 不在允许列表内（source={source_id}）",
                details={"host": host, "source_id": source_id, "allowed": sorted(allowed)},
            )


def _parse_retry_after(value: str | None) -> float | None:
    """解析 ``Retry-After`` 头（仅支持秒数形式）。"""
    if not value:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


__all__ = ["HttpClient", "HttpClientConfig", "HttpResult"]
