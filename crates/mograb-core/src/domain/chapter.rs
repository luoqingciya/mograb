// SPDX-License-Identifier: GPL-3.0-only
//! Chapter 领域模型、URL 规范化与内容哈希。

use blake2::digest::consts::U16;
use blake2::{Blake2b, Digest};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::LazyLock;
use url::{Url, form_urlencoded};

const TRACKING_QUERY_PREFIXES: &[&str] = &["utm_", "spm", "from", "ref", "share", "_t"];
const TRACKING_QUERY_KEYS: &[&str] = &["sid", "t", "timestamp", "rand"];

static WHITESPACE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s+").expect("valid whitespace regex"));

pub fn normalize_url(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return String::new();
    }

    let Ok(mut parsed) = Url::parse(trimmed) else {
        return trimmed.to_string();
    };

    parsed.set_fragment(None);

    let mut kept: Vec<(String, String)> = parsed
        .query_pairs()
        .filter(|(k, _)| {
            let lowered = k.to_lowercase();
            if TRACKING_QUERY_KEYS.contains(&lowered.as_str()) {
                return false;
            }
            !TRACKING_QUERY_PREFIXES
                .iter()
                .any(|p| lowered.starts_with(p))
        })
        .map(|(k, v)| (k.into_owned(), v.into_owned()))
        .collect();

    kept.sort();

    if kept.is_empty() {
        parsed.set_query(None);
    } else {
        let mut ser = form_urlencoded::Serializer::new(String::new());
        for (k, v) in &kept {
            ser.append_pair(k, v);
        }
        let encoded = ser.finish();
        parsed.set_query(Some(&encoded));
    }

    let path = parsed.path().to_string();
    if path.len() > 1 && path.ends_with('/') {
        let trimmed_path = path.trim_end_matches('/');
        let new_path = if trimmed_path.is_empty() {
            "/"
        } else {
            trimmed_path
        };
        parsed.set_path(new_path);
    }

    // url::Url serializes host without default port (:80 / :443) and lowercases scheme+host.
    parsed.to_string()
}

pub fn compute_content_hash(content: &str) -> String {
    let normalized = WHITESPACE_RE.replace_all(content, " ");
    let trimmed = normalized.trim();
    let mut hasher = Blake2b::<U16>::new();
    hasher.update(trimmed.as_bytes());
    hex::encode(hasher.finalize())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chapter {
    pub id: String,
    pub book_id: String,
    pub source_chapter_id: Option<String>,
    pub title: String,
    pub url: String,
    pub index: i64,
    pub content: Option<String>,
    pub content_hash: Option<String>,
    pub word_count: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl Chapter {
    pub fn normalized_url(&self) -> String {
        normalize_url(&self.url)
    }

    pub fn identity_key(&self) -> String {
        if let Some(ref sid) = self.source_chapter_id
            && !sid.is_empty()
        {
            return format!("sid:{sid}");
        }
        if !self.url.is_empty() {
            return format!("url:{}", self.normalized_url());
        }
        format!("idx:{}:{}", self.index, self.title)
    }

    pub fn refresh_content(&mut self, content: String) -> bool {
        let new_hash = compute_content_hash(&content);
        let changed = self.content_hash.as_deref() != Some(new_hash.as_str());
        self.word_count = content.chars().count() as i64;
        self.content = Some(content);
        self.content_hash = Some(new_hash);
        changed
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterSummary {
    pub id: String,
    pub index: i64,
    pub title: String,
    pub word_count: i64,
    pub has_content: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterSearchHit {
    pub book_id: String,
    pub book_title: String,
    pub chapter_id: String,
    pub chapter_title: String,
    pub chapter_index: i64,
    pub snippet: String,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_url() {
        assert_eq!(
            normalize_url("https://A.com:443/Book/12/?utm_source=x&b=2&a=1#frag"),
            "https://a.com/Book/12?a=1&b=2"
        );
        assert_eq!(normalize_url("http://A.com:80/"), "http://a.com/");
    }

    #[test]
    fn test_compute_content_hash_stable() {
        let h1 = compute_content_hash("第一段\n\n  第二段");
        let h2 = compute_content_hash("第一段 第二段");
        assert_eq!(h1, h2);
        assert_eq!(h1.len(), 32);
    }

    #[test]
    fn test_chapter_identity_priority() {
        let now = Utc::now();
        let mut ch = Chapter {
            id: "chap_1".into(),
            book_id: "book_1".into(),
            source_chapter_id: Some("c1".into()),
            title: "第一章".into(),
            url: "https://example.com/1.html".into(),
            index: 0,
            content: None,
            content_hash: None,
            word_count: 0,
            created_at: now,
            updated_at: now,
        };
        assert_eq!(ch.identity_key(), "sid:c1");
        ch.source_chapter_id = None;
        assert_eq!(ch.identity_key(), "url:https://example.com/1.html");
        ch.url.clear();
        assert_eq!(ch.identity_key(), "idx:0:第一章");
    }
}
