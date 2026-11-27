// SPDX-License-Identifier: GPL-3.0-only
//! HTTP 缓存协议与缓存键派生。

use crate::domain::chapter::normalize_url;
use crate::errors::MoGrabResult;
use async_trait::async_trait;
use blake2::digest::consts::{U8, U16};
use blake2::{Blake2b, Digest};
use chrono::{DateTime, Duration, Utc};
use serde_json::Value;
use std::collections::BTreeMap;
use url::{Url, form_urlencoded};

pub const TTL_DEFAULT: u64 = 30 * 60;
pub const TTL_CHAPTER_CONTENT: u64 = 7 * 24 * 3600;
const RELEVANT_HEADERS: &[&str] = &["accept", "accept-language", "cookie"];

#[derive(Debug, Clone)]
pub struct CacheEntry {
    pub key: String,
    pub source_id: String,
    pub url: String,
    pub status_code: u16,
    pub content: Vec<u8>,
    pub encoding: Option<String>,
    pub created_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
}

impl CacheEntry {
    pub fn is_expired(&self) -> bool {
        Utc::now() >= self.expires_at
    }

    pub fn size(&self) -> i64 {
        self.content.len() as i64
    }
}

#[derive(Debug, Clone)]
pub struct CacheStats {
    pub entries: i64,
    pub size_bytes: i64,
    pub max_size_bytes: u64,
}

#[async_trait]
pub trait HttpCache: Send + Sync {
    async fn get(&self, key: &str) -> MoGrabResult<Option<CacheEntry>>;
    async fn put(&self, entry: CacheEntry) -> MoGrabResult<()>;
    async fn invalidate_url(&self, source_id: &str, url: &str) -> MoGrabResult<u64>;
    async fn invalidate_source(&self, source_id: &str) -> MoGrabResult<u64>;
    async fn clear(&self) -> MoGrabResult<u64>;
    async fn purge_expired(&self) -> MoGrabResult<u64>;
    async fn stats(&self) -> MoGrabResult<CacheStats>;
}

pub fn merge_params(url: &str, params: Option<&BTreeMap<String, String>>) -> String {
    let Some(params) = params else {
        return url.to_string();
    };
    if params.is_empty() {
        return url.to_string();
    }
    let Ok(mut parsed) = Url::parse(url) else {
        return url.to_string();
    };
    let mut pairs: Vec<(String, String)> = parsed
        .query_pairs()
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();
    for (k, v) in params {
        pairs.push((k.clone(), v.clone()));
    }
    let mut ser = form_urlencoded::Serializer::new(String::new());
    for (k, v) in &pairs {
        ser.append_pair(k, v);
    }
    let query = ser.finish();
    parsed.set_query(Some(&query));
    parsed.to_string()
}

pub fn build_cache_key(
    source_id: &str,
    method: &str,
    url: &str,
    params: Option<&BTreeMap<String, String>>,
    body: Option<&Value>,
    headers: Option<&BTreeMap<String, String>>,
) -> String {
    let mut parts: Vec<String> = vec![
        source_id.to_string(),
        method.to_uppercase(),
        normalize_url(&merge_params(url, params)),
    ];

    if let Some(b) = body {
        let raw_bytes = match b {
            Value::String(s) => s.as_bytes().to_vec(),
            other => other.to_string().into_bytes(),
        };
        let mut h = Blake2b::<U8>::new();
        h.update(&raw_bytes);
        parts.push(hex::encode(h.finalize()));
    }

    if let Some(hdrs) = headers {
        let lowered: std::collections::HashSet<String> =
            hdrs.keys().map(|k| k.to_lowercase()).collect();
        let flags: Vec<String> = RELEVANT_HEADERS
            .iter()
            .filter(|h| lowered.contains(**h))
            .map(|h| format!("{h}=1"))
            .collect();
        if !flags.is_empty() {
            parts.push(flags.join(","));
        }
    }

    let joined = parts.join("\x1f");
    let mut hasher = Blake2b::<U16>::new();
    hasher.update(joined.as_bytes());
    hex::encode(hasher.finalize())
}

pub fn make_entry(
    key: String,
    source_id: String,
    url: String,
    status_code: u16,
    content: Vec<u8>,
    encoding: Option<String>,
    ttl_seconds: u64,
) -> CacheEntry {
    let now = Utc::now();
    CacheEntry {
        key,
        source_id,
        url,
        status_code,
        content,
        encoding,
        created_at: now,
        expires_at: now + Duration::seconds(ttl_seconds as i64),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_key_distinguishes_query_params() {
        let mut p1 = BTreeMap::new();
        p1.insert("q".into(), "三体".into());
        let mut p2 = BTreeMap::new();
        p2.insert("q".into(), "球状闪电".into());

        let k1 = build_cache_key(
            "ex",
            "GET",
            "https://example.com/search",
            Some(&p1),
            None,
            None,
        );
        let k2 = build_cache_key(
            "ex",
            "GET",
            "https://example.com/search",
            Some(&p2),
            None,
            None,
        );
        assert_ne!(k1, k2);
    }
}
