// SPDX-License-Identifier: GPL-3.0-only
//! Source Engine —— 按书源规则执行搜索 / 详情 / 目录 / 正文。

use super::extractor::{Document, extract_many, extract_one};
use super::request::{RenderedRequest, TemplateContext, build_request};
use super::transformer::{apply_transforms, apply_transforms_many, url_join};
use crate::domain::chapter::normalize_url;
use crate::domain::enums::{BookStatus, SourceCapability};
use crate::domain::source::{ResultSpec, SourceSpec};
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};
use std::sync::Arc;
use tracing::warn;

#[derive(Debug, Clone)]
pub struct SearchResult {
    pub source_id: String,
    pub title: String,
    pub url: String,
    pub author: Option<String>,
    pub cover_url: Option<String>,
    pub intro: Option<String>,
    pub extra: BTreeMap<String, Option<String>>,
}

#[derive(Debug, Clone)]
pub struct BookDraft {
    pub source_id: String,
    pub source_book_id: String,
    pub url: String,
    pub title: String,
    pub author: Option<String>,
    pub intro: Option<String>,
    pub cover_url: Option<String>,
    pub latest_chapter: Option<String>,
    pub status: BookStatus,
    pub extra: BTreeMap<String, Option<String>>,
}

#[derive(Debug, Clone)]
pub struct ChapterDraft {
    pub title: String,
    pub url: String,
    pub index: i64,
    pub source_chapter_id: Option<String>,
}

#[derive(Debug, Clone)]
pub struct FetchResponse {
    pub content: Vec<u8>,
    pub encoding: Option<String>,
    pub status_code: u16,
    pub url: String,
    pub from_cache: bool,
    pub headers: BTreeMap<String, String>,
}

#[derive(Debug, Clone)]
pub struct FetchOptions<'a> {
    pub method: &'a str,
    pub url: &'a str,
    pub source_id: &'a str,
    pub headers: &'a BTreeMap<String, String>,
    pub params: Option<&'a BTreeMap<String, String>>,
    pub data: Option<&'a Value>,
    pub cookies: &'a BTreeMap<String, String>,
    pub encoding: Option<&'a str>,
    pub timeout_ms: Option<u64>,
    pub use_cache: bool,
    pub ttl_seconds: Option<u64>,
    pub allowed_domains: Option<&'a [String]>,
    pub concurrency: Option<usize>,
    pub min_interval_secs: Option<f64>,
    pub max_retries: Option<usize>,
}

#[async_trait]
pub trait Fetcher: Send + Sync {
    async fn fetch(&self, opts: FetchOptions<'_>) -> MoGrabResult<FetchResponse>;
}

pub struct SourceEngine {
    fetcher: Arc<dyn Fetcher>,
}

impl SourceEngine {
    pub fn new(fetcher: Arc<dyn Fetcher>) -> Self {
        Self { fetcher }
    }

    fn require(source: &SourceSpec, capability: SourceCapability) -> MoGrabResult<()> {
        if !source.supports(capability) {
            return Err(MoGrabError::source_unsupported_with(
                format!("书源 {} 不支持能力 {}", source.id, capability.as_str()),
                json!({"source_id": source.id, "capability": capability.as_str()}),
            ));
        }
        Ok(())
    }

    pub async fn search(
        &self,
        source: &SourceSpec,
        keyword: &str,
        page: usize,
    ) -> MoGrabResult<Vec<SearchResult>> {
        Self::require(source, SourceCapability::Search)?;
        let search_spec = source
            .search
            .as_ref()
            .ok_or_else(|| MoGrabError::source_unsupported("缺少 search 规格"))?;

        let ctx = TemplateContext::from_pairs([
            ("keyword", keyword.to_string()),
            ("page", page.to_string()),
        ]);
        let req = build_request(&search_spec.request, &ctx, Some(&source.network.headers))?;
        let base_url = req.url.clone();

        let rows = self
            .collect_rows(
                source,
                req,
                &search_spec.result,
                search_spec.response.format.as_str(),
            )
            .await?;

        let mut transforms = source.transforms.clone();
        transforms.extend(search_spec.transform.iter().cloned());
        let rows = apply_transforms_many(rows, &transforms, Some(&base_url))?;

        let mut results = Vec::new();
        for mut row in rows {
            let title = row.remove("title").flatten();
            let url = row.remove("url").flatten();
            let (Some(title), Some(url)) = (title, url) else {
                continue;
            };
            if title.is_empty() || url.is_empty() {
                continue;
            }
            let author = row.remove("author").flatten();
            let cover_url = row.remove("cover").flatten();
            let intro = row.remove("intro").flatten();
            results.push(SearchResult {
                source_id: source.id.clone(),
                title,
                url,
                author,
                cover_url,
                intro,
                extra: row,
            });
        }
        Ok(results)
    }

    async fn collect_rows(
        &self,
        source: &SourceSpec,
        initial: RenderedRequest,
        result_spec: &ResultSpec,
        fmt: &str,
    ) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
        let mut rows = Vec::new();
        let mut visited = HashSet::new();
        visited.insert(initial.url.clone());

        let mut current = initial;
        let mut page_no: usize = 0;

        loop {
            page_no += 1;
            let mut doc = self.fetch_document(source, &current, fmt).await?;
            rows.extend(extract_many(
                &mut doc,
                &result_spec.list,
                &result_spec.fields,
            )?);

            let Some(ref pagination) = result_spec.paginate else {
                break;
            };

            if page_no >= pagination.max_pages {
                warn!(
                    source_id = %source.id,
                    max_pages = pagination.max_pages,
                    url = %current.url,
                    rows = rows.len(),
                    "source.pagination_limit_reached"
                );
                break;
            }

            let Some(next_href) = extract_one(&mut doc, &pagination.next)? else {
                break;
            };
            if next_href.trim().is_empty() {
                break;
            }

            let next_url = url_join(&current.url, &next_href)?;
            if visited.contains(&next_url) {
                warn!(
                    source_id = %source.id,
                    url = %next_url,
                    page = page_no,
                    "source.pagination_loop_detected"
                );
                break;
            }
            visited.insert(next_url.clone());

            // 下一页地址按站点原样使用，清空首页 query params，避免污染 ?page=2
            current.url = next_url;
            current.params = None;
        }

        Ok(rows)
    }

    pub async fn fetch_book(&self, source: &SourceSpec, book_url: &str) -> MoGrabResult<BookDraft> {
        Self::require(source, SourceCapability::Book)?;
        let book_spec = source
            .book
            .as_ref()
            .ok_or_else(|| MoGrabError::source_unsupported("缺少 book 规格"))?;

        let ctx = TemplateContext::from_pairs([("book.url", book_url.to_string())]);
        let req = build_request(&book_spec.request, &ctx, Some(&source.network.headers))?;
        let base_url = req.url.clone();

        let mut doc = self
            .fetch_document(source, &req, book_spec.response.format.as_str())
            .await?;

        let mut transforms = source.transforms.clone();
        transforms.extend(book_spec.transform.iter().cloned());

        let mut fields: BTreeMap<String, Option<String>> = BTreeMap::new();
        for (name, rule) in &book_spec.fields {
            let val = extract_one(&mut doc, rule)?;
            let transformed = apply_transforms(val.as_deref(), &transforms, Some(&base_url))?;
            fields.insert(name.clone(), transformed);
        }

        let title = fields.remove("title").flatten().filter(|s| !s.is_empty());
        let Some(title) = title else {
            return Err(MoGrabError::source_execution_with(
                "未能提取书籍标题",
                json!({"source_id": source.id, "url": book_url}),
            ));
        };

        let source_book_id = fields
            .remove("id")
            .flatten()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| normalize_url(book_url));

        let author = fields.remove("author").flatten();
        let intro = fields.remove("intro").flatten();
        let cover_url = fields.remove("cover").flatten();
        let latest_chapter = fields.remove("latest_chapter").flatten();
        let status_raw = fields.remove("status").flatten();

        Ok(BookDraft {
            source_id: source.id.clone(),
            source_book_id,
            url: book_url.to_string(),
            title,
            author,
            intro,
            cover_url,
            latest_chapter,
            status: BookStatus::parse(status_raw.as_deref()),
            extra: fields,
        })
    }

    pub async fn fetch_chapters(
        &self,
        source: &SourceSpec,
        book_url: &str,
    ) -> MoGrabResult<Vec<ChapterDraft>> {
        Self::require(source, SourceCapability::Chapters)?;
        let chap_spec = source
            .chapters
            .as_ref()
            .ok_or_else(|| MoGrabError::source_unsupported("缺少 chapters 规格"))?;

        let ctx = TemplateContext::from_pairs([("book.url", book_url.to_string())]);
        let req = build_request(&chap_spec.request, &ctx, Some(&source.network.headers))?;
        let base_url = req.url.clone();

        let mut rows = self
            .collect_rows(
                source,
                req,
                &chap_spec.result,
                chap_spec.response.format.as_str(),
            )
            .await?;

        let mut transforms = source.transforms.clone();
        transforms.extend(chap_spec.transform.iter().cloned());
        rows = apply_transforms_many(rows, &transforms, Some(&base_url))?;

        if chap_spec.result.reverse {
            rows.reverse();
        }

        let mut drafts = Vec::new();
        let mut idx: i64 = 0;
        for mut row in rows {
            let title = row.remove("title").flatten().filter(|s| !s.is_empty());
            let url = row.remove("url").flatten().filter(|s| !s.is_empty());
            let (Some(title), Some(url)) = (title, url) else {
                continue;
            };
            let source_chapter_id = row.remove("id").flatten().filter(|s| !s.is_empty());
            drafts.push(ChapterDraft {
                title,
                url,
                index: idx,
                source_chapter_id,
            });
            idx += 1;
        }
        Ok(drafts)
    }

    pub async fn fetch_content(
        &self,
        source: &SourceSpec,
        chapter_url: &str,
        chapter_index: Option<i64>,
    ) -> MoGrabResult<String> {
        Self::require(source, SourceCapability::Content)?;
        let content_spec = source
            .content
            .as_ref()
            .ok_or_else(|| MoGrabError::source_unsupported("缺少 content 规格"))?;

        let ctx = TemplateContext::from_pairs([
            ("chapter.url", chapter_url.to_string()),
            ("chapter.index", chapter_index.unwrap_or(0).to_string()),
        ]);
        let req = build_request(&content_spec.request, &ctx, Some(&source.network.headers))?;
        let base_url = req.url.clone();

        let mut doc = self
            .fetch_document(source, &req, content_spec.response.format.as_str())
            .await?;

        doc.clean_remove(&content_spec.clean.remove);

        let raw_content = extract_one(&mut doc, &content_spec.body)?;
        let Some(raw_content) = raw_content else {
            return Err(MoGrabError::source_execution_with(
                "未匹配到正文节点",
                json!({"source_id": source.id, "url": chapter_url}),
            ));
        };

        let mut transforms = source.transforms.clone();
        transforms.extend(content_spec.transform.iter().cloned());
        let result = apply_transforms(Some(&raw_content), &transforms, Some(&base_url))?;
        Ok(result.unwrap_or_default())
    }

    async fn fetch_document(
        &self,
        source: &SourceSpec,
        req: &RenderedRequest,
        fmt: &str,
    ) -> MoGrabResult<Document> {
        let resp = self
            .fetcher
            .fetch(FetchOptions {
                method: &req.method,
                url: &req.url,
                source_id: &source.id,
                headers: &req.headers,
                params: req.params.as_ref(),
                data: req.data.as_ref(),
                cookies: &req.cookies,
                encoding: req.encoding.as_deref(),
                timeout_ms: Some(req.timeout_ms.unwrap_or(source.network.timeout_ms)),
                use_cache: true,
                ttl_seconds: None,
                allowed_domains: Some(&source.permissions.network),
                concurrency: Some(source.network.concurrency),
                min_interval_secs: Some(source.network.request_interval_ms as f64 / 1000.0),
                max_retries: Some(source.network.retry),
            })
            .await?;

        let encoding = resp
            .encoding
            .or_else(|| req.encoding.clone())
            .unwrap_or_else(|| "utf-8".to_string());

        Ok(Document::new(resp.content, encoding, fmt))
    }
}
