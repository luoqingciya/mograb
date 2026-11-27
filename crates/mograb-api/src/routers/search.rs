// SPDX-License-Identifier: GPL-3.0-only
//! `/api/v1/search` 与 `/api/v1/search/local`。

use crate::AppState;
use crate::errors::ApiError;
use axum::Json;
use axum::extract::{Query, RawQuery, State};
use mograb_core::domain::enums::SourceCapability;
use mograb_core::errors::MoGrabError;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::Arc;
use tokio::task::JoinSet;
use url::form_urlencoded;
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct SearchItem {
    pub source_id: String,
    pub title: String,
    pub url: String,
    pub author: Option<String>,
    pub cover_url: Option<String>,
    pub intro: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SearchError {
    pub source_id: String,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SearchResponse {
    pub keyword: String,
    pub total: usize,
    pub items: Vec<SearchItem>,
    pub errors: Vec<SearchError>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct LocalHit {
    pub book_id: String,
    pub book_title: String,
    pub chapter_id: String,
    pub chapter_title: String,
    pub chapter_index: i64,
    pub snippet: String,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct LocalSearchResponse {
    pub keyword: String,
    pub total: usize,
    pub items: Vec<LocalHit>,
}

#[derive(Debug, Deserialize)]
pub struct LocalSearchQuery {
    pub q: String,
    #[serde(default)]
    pub book_id: Option<String>,
    #[serde(default = "default_local_limit")]
    pub limit: i64,
}

fn default_local_limit() -> i64 {
    50
}

#[utoipa::path(
    get,
    path = "/api/v1/search",
    tag = "search",
    summary = "搜索小说",
    params(
        ("q" = String, Query, description = "搜索关键词"),
        ("source" = Option<Vec<String>>, Query, description = "限定书源 ID（可重复）"),
        ("limit" = Option<usize>, Query, description = "每源返回上限")
    ),
    responses((status = 200, body = SearchResponse)),
    security(("MoGrabToken" = []))
)]
pub async fn search(
    RawQuery(raw_query): RawQuery,
    State(state): State<AppState>,
) -> Result<Json<SearchResponse>, ApiError> {
    let mut keyword = String::new();
    let mut sources_filter: Vec<String> = Vec::new();
    let mut limit: usize = 20;

    if let Some(qstr) = raw_query {
        for (k, v) in form_urlencoded::parse(qstr.as_bytes()) {
            match k.as_ref() {
                "q" => keyword = v.into_owned(),
                "source" => {
                    if !v.is_empty() {
                        sources_filter.push(v.into_owned());
                    }
                }
                "limit" => {
                    if let Ok(parsed) = v.parse::<usize>() {
                        limit = parsed.clamp(1, 100);
                    }
                }
                _ => {}
            }
        }
    }

    if keyword.is_empty() {
        return Err(ApiError(MoGrabError::task_parameter("缺少查询参数 q")));
    }

    let mut entries = state.app.sources.list_enabled().await?;
    if !sources_filter.is_empty() {
        let wanted: HashSet<String> = sources_filter.into_iter().collect();
        entries.retain(|e| wanted.contains(&e.spec.id));
    }

    let searchable: Vec<_> = entries
        .into_iter()
        .filter(|e| e.spec.supports(SourceCapability::Search))
        .collect();

    if searchable.is_empty() {
        return Ok(Json(SearchResponse {
            keyword,
            total: 0,
            items: Vec::new(),
            errors: Vec::new(),
        }));
    }

    let mut set = JoinSet::new();
    for entry in searchable {
        let engine = Arc::clone(&state.app.engine);
        let kw = keyword.clone();
        set.spawn(async move {
            let sid = entry.spec.id.clone();
            let res = engine.search(&entry.spec, &kw, 1).await;
            (sid, res)
        });
    }

    let mut items = Vec::new();
    let mut errors = Vec::new();
    while let Some(joined) = set.join_next().await {
        let Ok((sid, res)) = joined else { continue };
        match res {
            Ok(hits) => {
                for hit in hits.into_iter().take(limit) {
                    items.push(SearchItem {
                        source_id: hit.source_id,
                        title: hit.title,
                        url: hit.url,
                        author: hit.author,
                        cover_url: hit.cover_url,
                        intro: hit.intro,
                    });
                }
            }
            Err(err) => {
                errors.push(SearchError {
                    source_id: sid,
                    code: err.code().to_string(),
                    message: err.message().to_string(),
                });
            }
        }
    }

    Ok(Json(SearchResponse {
        keyword,
        total: items.len(),
        items,
        errors,
    }))
}

#[utoipa::path(
    get,
    path = "/api/v1/search/local",
    tag = "search",
    summary = "在已下载的正文里搜索",
    params(
        ("q" = String, Query, description = "搜索关键词（字面子串，不解析正则）"),
        ("book_id" = Option<String>, Query, description = "限定某一本书"),
        ("limit" = Option<i64>, Query, description = "返回条数上限")
    ),
    responses((status = 200, body = LocalSearchResponse)),
    security(("MoGrabToken" = []))
)]
pub async fn search_local(
    Query(query): Query<LocalSearchQuery>,
    State(state): State<AppState>,
) -> Result<Json<LocalSearchResponse>, ApiError> {
    if query.q.is_empty() {
        return Err(ApiError(MoGrabError::task_parameter("缺少查询参数 q")));
    }
    let limit = query.limit.clamp(1, 200);
    let hits = state
        .app
        .chapters
        .search_content(&query.q, query.book_id.as_deref(), limit)
        .await?;

    let items: Vec<LocalHit> = hits
        .into_iter()
        .map(|h| LocalHit {
            book_id: h.book_id,
            book_title: h.book_title,
            chapter_id: h.chapter_id,
            chapter_title: h.chapter_title,
            chapter_index: h.chapter_index,
            snippet: h.snippet,
        })
        .collect();

    Ok(Json(LocalSearchResponse {
        keyword: query.q,
        total: items.len(),
        items,
    }))
}
