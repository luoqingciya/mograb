// SPDX-License-Identifier: GPL-3.0-only
//! 封面下载与本地存储。

use crate::config::Paths;
use crate::domain::book::Book;
use crate::source::engine::{FetchOptions, Fetcher};
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::Arc;
use tracing::{info, warn};

pub const MAX_COVER_BYTES: usize = 8 * 1024 * 1024;

pub struct CoverStore {
    http: Arc<dyn Fetcher>,
    paths: Paths,
}

impl CoverStore {
    pub fn new(http: Arc<dyn Fetcher>, paths: Paths) -> Self {
        Self { http, paths }
    }

    pub async fn ensure(&self, book: &Book, allowed_domains: Option<&[String]>) -> Option<String> {
        if let Some(ref existing) = book.cover_path
            && !existing.is_empty()
        {
            return Some(existing.clone());
        }
        let cover_url = book.cover_url.as_deref()?;
        if cover_url.is_empty() {
            return None;
        }

        let headers = BTreeMap::new();
        let cookies = BTreeMap::new();
        let resp = match self
            .http
            .fetch(FetchOptions {
                method: "GET",
                url: cover_url,
                source_id: &book.source_id,
                headers: &headers,
                params: None,
                data: None,
                cookies: &cookies,
                encoding: None,
                timeout_ms: None,
                use_cache: true,
                ttl_seconds: None,
                allowed_domains,
                concurrency: None,
                min_interval_secs: None,
                max_retries: None,
            })
            .await
        {
            Ok(r) => r,
            Err(err) => {
                warn!(
                    book_id = %book.id,
                    url = cover_url,
                    error = err.message(),
                    hint = "如果封面在别的域名（CDN）上，把它加进书源的 permissions.network 就能下载",
                    "cover.fetch_failed"
                );
                return None;
            }
        };

        if resp.content.len() > MAX_COVER_BYTES {
            warn!(
                book_id = %book.id,
                url = cover_url,
                size = resp.content.len(),
                limit = MAX_COVER_BYTES,
                "cover.too_large"
            );
            return None;
        }

        let content_type = resp
            .headers
            .get("content-type")
            .map(String::as_str)
            .unwrap_or("");
        let Some(suffix) = guess_suffix(cover_url, content_type) else {
            warn!(
                book_id = %book.id,
                url = cover_url,
                content_type,
                "cover.unknown_format"
            );
            return None;
        };

        remove_stale(&self.paths.covers_dir, &book.id, suffix);

        let filename = format!("{}{suffix}", book.id);
        let target = self.paths.covers_dir.join(&filename);
        if fs::create_dir_all(&self.paths.covers_dir).is_err() {
            return None;
        }
        if fs::write(&target, &resp.content).is_err() {
            return None;
        }

        let relative = format!("covers/{filename}");
        info!(book_id = %book.id, path = %relative, size = resp.content.len(), "cover.saved");
        Some(relative)
    }
}

fn guess_suffix(url: &str, content_type: &str) -> Option<&'static str> {
    let ct = content_type
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_lowercase();
    match ct.as_str() {
        "image/jpeg" | "image/jpg" => return Some(".jpg"),
        "image/png" => return Some(".png"),
        "image/gif" => return Some(".gif"),
        "image/webp" => return Some(".webp"),
        _ => {}
    }
    let path_part = url.split('?').next().unwrap_or("");
    let ext = Path::new(path_part)
        .extension()
        .and_then(|e| e.to_str())
        .map(|s| s.to_lowercase())?;
    match ext.as_str() {
        "jpg" => Some(".jpg"),
        "jpeg" => Some(".jpeg"),
        "png" => Some(".png"),
        "gif" => Some(".gif"),
        "webp" => Some(".webp"),
        _ => None,
    }
}

fn remove_stale(covers_dir: &Path, book_id: &str, keep_suffix: &str) {
    let Ok(entries) = fs::read_dir(covers_dir) else {
        return;
    };
    let prefix = format!("{book_id}.");
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        if name_str.starts_with(&prefix) && !name_str.to_lowercase().ends_with(keep_suffix) {
            let _ = fs::remove_file(entry.path());
        }
    }
}
