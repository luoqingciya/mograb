# SPDX-License-Identifier: GPL-3.0-only
"""网络子系统：HTTP 客户端、缓存、限流、重试。

所有对外网络访问必须经过本层（规划书 §14）。
"""

from .cache import (
    TTL_CHAPTER_CONTENT,
    TTL_DEFAULT,
    CacheEntry,
    HttpCache,
    build_cache_key,
    make_entry,
)
from .client import HttpClient, HttpClientConfig, HttpResult
from .limiter import GlobalLimiter, SourceLimiter, SourceLimiterRegistry
from .retry import RetryPolicy

__all__ = [
    "TTL_CHAPTER_CONTENT",
    "TTL_DEFAULT",
    "CacheEntry",
    "GlobalLimiter",
    "HttpCache",
    "HttpClient",
    "HttpClientConfig",
    "HttpResult",
    "RetryPolicy",
    "SourceLimiter",
    "SourceLimiterRegistry",
    "build_cache_key",
    "make_entry",
]
