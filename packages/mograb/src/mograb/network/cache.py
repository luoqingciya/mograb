# SPDX-License-Identifier: GPL-3.0-only
"""HTTP 缓存（规划书 §16）。

规划书要求「必须提供失效策略」但未定义；本模块补齐如下：

**缓存键**（:func:`build_cache_key`）包含：

- ``source_id``（不同书源对同一 URL 的规则不同，不可共用）
- ``method``
- ``url`` + ``params``（合并后规范化：去 fragment、排序 query）
- ``body`` 的哈希
- **相关**请求头（仅 ``Accept`` / ``Accept-Language`` / ``Cookie`` 的有无标记）

> ``params`` 必须进键。书源把查询参数写在 ``request.query`` 里，渲染后是
> ``RenderedRequest.params``，与 ``url`` **分开**存放 —— ``url`` 里没有查询串。
> 只看 ``url`` 的话，「搜 A」和「搜 B」会撞到同一个键，30 分钟 TTL 内换任何
> 关键词拿到的都是上一次的结果。踩过一次。

**失效策略**（三层）：

1. **TTL**：条目级 ``expires_at``。默认：列表/详情页 30 分钟，正文页 7 天。
2. **显式失效**：``invalidate_url`` / ``invalidate_source``（对应
   ``mog cache clear`` / ``mog cache clear-source``）。
3. **容量淘汰**：超过 ``max_size`` 时按 LRU 淘汰（``evict``）。

缓存只存 HTML/JSON/文本响应，不缓存二进制 —— 封面走 ``data/covers/``
（``CoverStore``），不经过这里。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..domain.chapter import normalize_url

# 默认 TTL（秒）
TTL_DEFAULT = 30 * 60
TTL_CHAPTER_CONTENT = 7 * 24 * 3600

# 参与缓存键的「相关请求头」：只记录是否存在，不记录具体值（避免 Cookie 泄漏）
_RELEVANT_HEADERS = ("accept", "accept-language", "cookie")


@dataclass(slots=True)
class CacheEntry:
    """一条缓存记录。"""

    key: str
    source_id: str
    url: str
    status_code: int
    content: bytes
    encoding: str | None
    created_at: datetime
    expires_at: datetime

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) >= self.expires_at

    @property
    def size(self) -> int:
        return len(self.content)


@runtime_checkable
class HttpCache(Protocol):
    """缓存后端协议。"""

    async def get(self, key: str) -> CacheEntry | None: ...

    async def put(self, entry: CacheEntry) -> None: ...

    async def invalidate_url(self, source_id: str, url: str) -> int: ...

    async def invalidate_source(self, source_id: str) -> int: ...

    async def clear(self) -> int: ...

    async def stats(self) -> dict[str, int]: ...


def build_cache_key(
    *,
    source_id: str,
    method: str,
    url: str,
    params: dict[str, str] | None = None,
    body: bytes | str | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    """构造稳定的缓存键。

    规范化保证「同一逻辑请求」总是映射到同一键，而「不同逻辑请求」
    （例如不同关键词）不会误命中。

    ``params`` 会先并进 ``url`` 再一起规范化。**它必须进键** —— 书源把查询
    参数写在 ``request.query`` 里，渲染后是 :class:`RenderedRequest` 的独立
    字段，``url`` 里并没有查询串。只看 ``url`` 会让「同一路径、不同参数」
    撞到同一个键。
    """
    parts: list[str] = [
        source_id,
        method.upper(),
        normalize_url(_merge_params(url, params)),
    ]

    if body is not None:
        raw = body.encode("utf-8") if isinstance(body, str) else body
        parts.append(hashlib.blake2b(raw, digest_size=8).hexdigest())

    header_flags = []
    lowered = {k.lower(): v for k, v in (headers or {}).items()}
    for name in _RELEVANT_HEADERS:
        if name in lowered:
            header_flags.append(f"{name}=1")
    if header_flags:
        parts.append(",".join(header_flags))

    digest = hashlib.blake2b("\x1f".join(parts).encode("utf-8"), digest_size=16)
    return digest.hexdigest()


def _merge_params(url: str, params: dict[str, str] | None) -> str:
    """把查询参数并进 URL。

    顺序不用管 —— :func:`normalize_url` 会按 key 排序，并去掉追踪类参数。
    所以这里只负责「别把参数弄丢」。
    """
    if not params:
        return url
    parts = urlsplit(url)
    merged = [*parse_qsl(parts.query, keep_blank_values=True), *params.items()]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment))


def make_entry(
    *,
    key: str,
    source_id: str,
    url: str,
    status_code: int,
    content: bytes,
    encoding: str | None = None,
    ttl_seconds: int = TTL_DEFAULT,
) -> CacheEntry:
    """构造一条带过期时间的缓存记录。"""
    now = datetime.now(UTC)
    return CacheEntry(
        key=key,
        source_id=source_id,
        url=url,
        status_code=status_code,
        content=content,
        encoding=encoding,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )


__all__ = [
    "TTL_CHAPTER_CONTENT",
    "TTL_DEFAULT",
    "CacheEntry",
    "HttpCache",
    "build_cache_key",
    "make_entry",
]
