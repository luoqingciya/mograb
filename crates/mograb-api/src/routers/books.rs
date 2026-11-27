// SPDX-License-Identifier: GPL-3.0-only
//! `/api/v1/books` —— 书籍与章节。

use crate::AppState;
use crate::errors::ApiError;
use axum::Json;
use axum::extract::{Path, Query, State};
use chrono::{DateTime, Utc};
use mograb_core::domain::book::Book;
use mograb_core::domain::chapter::ChapterSummary as DomainChapterSummary;
use mograb_core::domain::enums::TaskType;
use mograb_core::errors::MoGrabError;
use serde::{Deserialize, Serialize};
use serde_json::{Map, json};
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct BookOut {
    pub id: String,
    pub source_id: String,
    pub source_book_id: String,
    pub url: String,
    pub title: String,
    pub author: Option<String>,
    pub intro: Option<String>,
    pub language: Option<String>,
    pub cover_url: Option<String>,
    pub status: String,
    pub latest_chapter: Option<String>,
    pub chapter_count: i64,
    pub word_count: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ChapterSummaryOut {
    pub id: String,
    pub title: String,
    pub index: i64,
    pub word_count: i64,
    pub has_content: bool,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ChapterDetailOut {
    pub id: String,
    pub title: String,
    pub index: i64,
    pub word_count: i64,
    pub has_content: bool,
    pub url: String,
    pub content: Option<String>,
    pub content_hash: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct UpdateResult {
    pub book_id: String,
    pub total: usize,
    pub to_download: usize,
    pub skipped: usize,
    pub missing: Vec<String>,
    pub latest_chapter: Option<String>,
    pub dry_run: bool,
}

#[derive(Debug, Deserialize)]
pub struct ListBooksQuery {
    #[serde(default = "default_limit")]
    pub limit: i64,
    #[serde(default)]
    pub offset: i64,
}

fn default_limit() -> i64 {
    50
}

#[derive(Debug, Deserialize)]
pub struct UpdateBookQuery {
    #[serde(default = "default_true")]
    pub dry_run: bool,
}

fn default_true() -> bool {
    true
}

fn to_book(b: Book) -> BookOut {
    BookOut {
        id: b.id,
        source_id: b.source_id,
        source_book_id: b.source_book_id,
        url: b.url,
        title: b.title,
        author: b.author,
        intro: b.intro,
        language: b.language,
        cover_url: b.cover_url,
        status: b.status.as_str().to_string(),
        latest_chapter: b.latest_chapter,
        chapter_count: b.chapter_count,
        word_count: b.word_count,
        created_at: b.created_at,
        updated_at: b.updated_at,
    }
}

fn to_summary(s: DomainChapterSummary) -> ChapterSummaryOut {
    ChapterSummaryOut {
        id: s.id,
        title: s.title,
        index: s.index,
        word_count: s.word_count,
        has_content: s.has_content,
    }
}

#[utoipa::path(
    get,
    path = "/api/v1/books",
    tag = "books",
    summary = "列出书架",
    params(
        ("limit" = Option<i64>, Query, description = "返回上限 (1..=200)"),
        ("offset" = Option<i64>, Query, description = "偏移")
    ),
    responses((status = 200, body = Vec<BookOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn list_books(
    Query(query): Query<ListBooksQuery>,
    State(state): State<AppState>,
) -> Result<Json<Vec<BookOut>>, ApiError> {
    let limit = query.limit.clamp(1, 200);
    let offset = query.offset.max(0);
    let books = state.app.books.list_all(limit, offset).await?;
    Ok(Json(books.into_iter().map(to_book).collect()))
}

#[utoipa::path(
    get,
    path = "/api/v1/books/{book_id}",
    tag = "books",
    summary = "书籍详情",
    params(("book_id" = String, Path, description = "书籍 ID")),
    responses((status = 200, body = BookOut)),
    security(("MoGrabToken" = []))
)]
pub async fn get_book(
    Path(book_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<BookOut>, ApiError> {
    let book = state.app.books.get(&book_id).await?.ok_or_else(|| {
        ApiError(MoGrabError::entity_not_found(
            format!("书籍不存在: {book_id}"),
            json!({"book_id": book_id}),
        ))
    })?;
    Ok(Json(to_book(book)))
}

#[utoipa::path(
    get,
    path = "/api/v1/books/{book_id}/chapters",
    tag = "books",
    summary = "章节列表",
    params(("book_id" = String, Path, description = "书籍 ID")),
    responses((status = 200, body = Vec<ChapterSummaryOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn list_chapters(
    Path(book_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<Vec<ChapterSummaryOut>>, ApiError> {
    if state.app.books.get(&book_id).await?.is_none() {
        return Err(ApiError(MoGrabError::entity_not_found(
            format!("书籍不存在: {book_id}"),
            json!({"book_id": book_id}),
        )));
    }
    let summaries = state.app.chapters.list_summaries(&book_id).await?;
    Ok(Json(summaries.into_iter().map(to_summary).collect()))
}

#[utoipa::path(
    get,
    path = "/api/v1/books/{book_id}/chapters/{chapter_id}",
    tag = "books",
    summary = "章节正文",
    params(
        ("book_id" = String, Path, description = "书籍 ID"),
        ("chapter_id" = String, Path, description = "章节 ID")
    ),
    responses((status = 200, body = ChapterDetailOut)),
    security(("MoGrabToken" = []))
)]
pub async fn get_chapter(
    Path((book_id, chapter_id)): Path<(String, String)>,
    State(state): State<AppState>,
) -> Result<Json<ChapterDetailOut>, ApiError> {
    let ch = state.app.chapters.get(&chapter_id).await?;
    let Some(ch) = ch.filter(|c| c.book_id == book_id) else {
        return Err(ApiError(MoGrabError::entity_not_found(
            format!("章节不存在: {chapter_id}"),
            json!({"book_id": book_id, "chapter_id": chapter_id}),
        )));
    };
    let has_content = ch.content.as_ref().is_some_and(|s| !s.is_empty());
    Ok(Json(ChapterDetailOut {
        id: ch.id,
        title: ch.title,
        index: ch.index,
        word_count: ch.word_count,
        has_content,
        url: ch.url,
        content: ch.content,
        content_hash: ch.content_hash,
    }))
}

#[utoipa::path(
    post,
    path = "/api/v1/books/{book_id}/update",
    tag = "books",
    summary = "增量更新",
    params(
        ("book_id" = String, Path, description = "书籍 ID"),
        ("dry_run" = Option<bool>, Query, description = "只算差异，不下载")
    ),
    responses((status = 200, body = UpdateResult)),
    security(("MoGrabToken" = []))
)]
pub async fn update_book(
    Path(book_id): Path<String>,
    Query(query): Query<UpdateBookQuery>,
    State(state): State<AppState>,
) -> Result<Json<UpdateResult>, ApiError> {
    let mut plan = state.app.scheduler.plan_update(&book_id).await?;
    if !query.dry_run && !plan.is_noop() {
        let task = state
            .app
            .run_task(
                TaskType::UpdateBook,
                Some(book_id.clone()),
                None,
                Map::new(),
                None,
            )
            .await?;
        if task.completed > 0 || task.failed > 0 {
            plan = state.app.scheduler.plan_update(&book_id).await?;
        }
    }

    Ok(Json(UpdateResult {
        book_id: plan.book_id,
        total: plan.total,
        to_download: plan.to_download.len(),
        skipped: plan.skipped,
        missing: plan.missing,
        latest_chapter: plan.latest_chapter,
        dry_run: query.dry_run,
    }))
}
