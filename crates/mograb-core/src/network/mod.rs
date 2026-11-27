// SPDX-License-Identifier: GPL-3.0-only
//! Network 模块入口。

pub mod cache;
pub mod client;
pub mod limiter;
pub mod retry;

pub use cache::{
    CacheEntry, CacheStats, HttpCache, TTL_CHAPTER_CONTENT, TTL_DEFAULT, build_cache_key,
    make_entry,
};
pub use client::{HttpClient, HttpClientConfig, detect_encoding};
pub use limiter::{GlobalLimiter, SourceLimiter, SourceLimiterRegistry};
pub use retry::RetryPolicy;
