// SPDX-License-Identifier: GPL-3.0-only
//! SQLite 仓储实现与 HTTP 缓存后端。

use super::database::Database;
use super::repository::{
    BookRepository, ChapterRepository, ExportRepository, SettingsRepository, SourceRepository,
    TaskRepository,
};
use crate::domain::book::Book;
use crate::domain::chapter::{Chapter, ChapterSearchHit, ChapterSummary};
use crate::domain::enums::{
    BookStatus, ExportFormat, ExportStatus, HealthStatus, TaskItemStatus, TaskStatus, TaskType,
};
use crate::domain::export::ExportRecord;
use crate::domain::source::{InstalledSource, SOURCE_ID_RE, SourceSpec};
use crate::domain::task::{Task, TaskItem};
use crate::errors::{MoGrabError, MoGrabResult};
use crate::network::cache::{CacheEntry, CacheStats, HttpCache};
use crate::source::loader::{load_source_file, write_source_file};
use async_trait::async_trait;
use chrono::{DateTime, Duration, Utc};
use serde_json::{Map, Value, json};
use sqlx::{Row, sqlite::SqliteRow};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use tracing::{info, warn};

fn db_err(err: sqlx::Error) -> MoGrabError {
    MoGrabError::storage(format!("数据库操作失败: {err}"))
}

fn utc_now_iso() -> String {
    Utc::now().to_rfc3339()
}

fn parse_dt(raw: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(raw)
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or_else(|_| Utc::now())
}

// ---------------------------------------------------------------------------
// SqliteBookRepository
// ---------------------------------------------------------------------------
pub struct SqliteBookRepository {
    db: Database,
}

impl SqliteBookRepository {
    pub fn new(db: Database) -> Self {
        Self { db }
    }

    fn row_to_book(row: &SqliteRow) -> MoGrabResult<Book> {
        let meta_str: String = row.try_get("metadata").map_err(db_err)?;
        let metadata: Map<String, Value> = serde_json::from_str(&meta_str).unwrap_or_default();
        let status_str: String = row.try_get("status").map_err(db_err)?;
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        let updated_str: String = row.try_get("updated_at").map_err(db_err)?;

        Ok(Book {
            id: row.try_get("id").map_err(db_err)?,
            source_id: row.try_get("source_id").map_err(db_err)?,
            source_book_id: row.try_get("source_book_id").map_err(db_err)?,
            url: row.try_get("url").map_err(db_err)?,
            title: row.try_get("title").map_err(db_err)?,
            author: row.try_get("author").map_err(db_err)?,
            intro: row.try_get("intro").map_err(db_err)?,
            language: row.try_get("language").map_err(db_err)?,
            cover_url: row.try_get("cover_url").map_err(db_err)?,
            cover_path: row.try_get("cover_path").map_err(db_err)?,
            status: BookStatus::from_db_str(&status_str),
            latest_chapter: row.try_get("latest_chapter").map_err(db_err)?,
            word_count: row.try_get("word_count").map_err(db_err)?,
            chapter_count: row.try_get("chapter_count").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            updated_at: parse_dt(&updated_str),
            metadata,
        })
    }
}

#[async_trait]
impl BookRepository for SqliteBookRepository {
    async fn get(&self, book_id: &str) -> MoGrabResult<Option<Book>> {
        let row = sqlx::query("SELECT * FROM books WHERE id = ?")
            .bind(book_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.as_ref().map(Self::row_to_book).transpose()
    }

    async fn get_by_identity(
        &self,
        source_id: &str,
        source_book_id: &str,
    ) -> MoGrabResult<Option<Book>> {
        let row = sqlx::query("SELECT * FROM books WHERE source_id = ? AND source_book_id = ?")
            .bind(source_id)
            .bind(source_book_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.as_ref().map(Self::row_to_book).transpose()
    }

    async fn save(&self, book: &Book) -> MoGrabResult<()> {
        let meta_json = serde_json::to_string(&book.metadata).unwrap_or_else(|_| "{}".to_string());
        let created = book.created_at.to_rfc3339();
        let updated = book.updated_at.to_rfc3339();

        sqlx::query(
            r#"
            INSERT INTO books (
                id, source_id, source_book_id, url, title, author, intro, language,
                cover_url, cover_path, status, latest_chapter, word_count, chapter_count,
                created_at, updated_at, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source_id = excluded.source_id,
                source_book_id = excluded.source_book_id,
                url = excluded.url,
                title = excluded.title,
                author = excluded.author,
                intro = excluded.intro,
                language = excluded.language,
                cover_url = excluded.cover_url,
                cover_path = excluded.cover_path,
                status = excluded.status,
                latest_chapter = excluded.latest_chapter,
                word_count = excluded.word_count,
                chapter_count = excluded.chapter_count,
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            "#,
        )
        .bind(&book.id)
        .bind(&book.source_id)
        .bind(&book.source_book_id)
        .bind(&book.url)
        .bind(&book.title)
        .bind(&book.author)
        .bind(&book.intro)
        .bind(&book.language)
        .bind(&book.cover_url)
        .bind(&book.cover_path)
        .bind(book.status.as_str())
        .bind(&book.latest_chapter)
        .bind(book.word_count)
        .bind(book.chapter_count)
        .bind(&created)
        .bind(&updated)
        .bind(&meta_json)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(())
    }

    async fn list_all(&self, limit: i64, offset: i64) -> MoGrabResult<Vec<Book>> {
        let rows = sqlx::query("SELECT * FROM books ORDER BY updated_at DESC LIMIT ? OFFSET ?")
            .bind(limit)
            .bind(offset)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        rows.iter().map(Self::row_to_book).collect()
    }

    async fn delete(&self, book_id: &str) -> MoGrabResult<bool> {
        let res = sqlx::query("DELETE FROM books WHERE id = ?")
            .bind(book_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected() > 0)
    }

    async fn count(&self) -> MoGrabResult<i64> {
        let row = sqlx::query("SELECT COUNT(*) AS cnt FROM books")
            .fetch_one(self.db.pool())
            .await
            .map_err(db_err)?;
        row.try_get("cnt").map_err(db_err)
    }
}

// ---------------------------------------------------------------------------
// SqliteChapterRepository
// ---------------------------------------------------------------------------
pub struct SqliteChapterRepository {
    db: Database,
}

impl SqliteChapterRepository {
    pub fn new(db: Database) -> Self {
        Self { db }
    }

    fn row_to_chapter(row: &SqliteRow) -> MoGrabResult<Chapter> {
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        let updated_str: String = row.try_get("updated_at").map_err(db_err)?;
        Ok(Chapter {
            id: row.try_get("id").map_err(db_err)?,
            book_id: row.try_get("book_id").map_err(db_err)?,
            source_chapter_id: row.try_get("source_chapter_id").map_err(db_err)?,
            title: row.try_get("title").map_err(db_err)?,
            url: row.try_get("url").map_err(db_err)?,
            index: row.try_get("index").map_err(db_err)?,
            content: row.try_get("content").map_err(db_err)?,
            content_hash: row.try_get("content_hash").map_err(db_err)?,
            word_count: row.try_get("word_count").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            updated_at: parse_dt(&updated_str),
        })
    }
}

#[async_trait]
impl ChapterRepository for SqliteChapterRepository {
    async fn get(&self, chapter_id: &str) -> MoGrabResult<Option<Chapter>> {
        let row = sqlx::query("SELECT * FROM chapters WHERE id = ?")
            .bind(chapter_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.as_ref().map(Self::row_to_chapter).transpose()
    }

    async fn list_by_book(&self, book_id: &str) -> MoGrabResult<Vec<Chapter>> {
        let rows = sqlx::query(r#"SELECT * FROM chapters WHERE book_id = ? ORDER BY "index" ASC"#)
            .bind(book_id)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        rows.iter().map(Self::row_to_chapter).collect()
    }

    async fn list_summaries(&self, book_id: &str) -> MoGrabResult<Vec<ChapterSummary>> {
        let rows = sqlx::query(
            r#"
            SELECT
                id,
                "index" AS chapter_index,
                title,
                word_count,
                (LENGTH(content) > 0) AS has_content
            FROM chapters
            WHERE book_id = ?
            ORDER BY "index" ASC
            "#,
        )
        .bind(book_id)
        .fetch_all(self.db.pool())
        .await
        .map_err(db_err)?;

        let mut out = Vec::with_capacity(rows.len());
        for r in rows {
            let has_content_val: Option<i64> = r.try_get("has_content").map_err(db_err)?;
            out.push(ChapterSummary {
                id: r.try_get("id").map_err(db_err)?,
                index: r.try_get("chapter_index").map_err(db_err)?,
                title: r.try_get("title").map_err(db_err)?,
                word_count: r.try_get("word_count").map_err(db_err)?,
                has_content: has_content_val.unwrap_or(0) != 0,
            });
        }
        Ok(out)
    }

    async fn get_by_index(&self, book_id: &str, index: i64) -> MoGrabResult<Option<Chapter>> {
        let row =
            sqlx::query(r#"SELECT * FROM chapters WHERE book_id = ? AND "index" = ? LIMIT 1"#)
                .bind(book_id)
                .bind(index)
                .fetch_optional(self.db.pool())
                .await
                .map_err(db_err)?;
        row.as_ref().map(Self::row_to_chapter).transpose()
    }

    async fn list_identities(&self, book_id: &str) -> MoGrabResult<Vec<(String, String)>> {
        let rows = sqlx::query(
            "SELECT identity_key, COALESCE(content_hash, '') AS content_hash FROM chapters WHERE book_id = ?",
        )
        .bind(book_id)
        .fetch_all(self.db.pool())
        .await
        .map_err(db_err)?;

        let mut out = Vec::with_capacity(rows.len());
        for r in rows {
            out.push((
                r.try_get("identity_key").map_err(db_err)?,
                r.try_get("content_hash").map_err(db_err)?,
            ));
        }
        Ok(out)
    }

    async fn stats_by_book(&self, book_id: &str) -> MoGrabResult<(i64, i64)> {
        let row = sqlx::query(
            "SELECT COUNT(id) AS cnt, COALESCE(SUM(word_count), 0) AS words FROM chapters WHERE book_id = ?",
        )
        .bind(book_id)
        .fetch_one(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok((
            row.try_get("cnt").map_err(db_err)?,
            row.try_get("words").map_err(db_err)?,
        ))
    }

    async fn save(&self, chapter: &Chapter) -> MoGrabResult<()> {
        self.save_many(std::slice::from_ref(chapter)).await
    }

    async fn save_many(&self, chapters: &[Chapter]) -> MoGrabResult<()> {
        if chapters.is_empty() {
            return Ok(());
        }
        let mut tx = self.db.pool().begin().await.map_err(db_err)?;
        for ch in chapters {
            let identity_key = ch.identity_key();
            let norm_url = ch.normalized_url();
            let created = ch.created_at.to_rfc3339();
            let updated = ch.updated_at.to_rfc3339();
            sqlx::query(
                r#"
                INSERT INTO chapters (
                    id, book_id, source_chapter_id, identity_key, title, url, normalized_url,
                    "index", content, content_hash, word_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id, identity_key) DO UPDATE SET
                    source_chapter_id = excluded.source_chapter_id,
                    title = excluded.title,
                    url = excluded.url,
                    normalized_url = excluded.normalized_url,
                    "index" = excluded."index",
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    word_count = excluded.word_count,
                    updated_at = excluded.updated_at
                "#,
            )
            .bind(&ch.id)
            .bind(&ch.book_id)
            .bind(&ch.source_chapter_id)
            .bind(&identity_key)
            .bind(&ch.title)
            .bind(&ch.url)
            .bind(&norm_url)
            .bind(ch.index)
            .bind(&ch.content)
            .bind(&ch.content_hash)
            .bind(ch.word_count)
            .bind(&created)
            .bind(&updated)
            .execute(&mut *tx)
            .await
            .map_err(db_err)?;
        }
        tx.commit().await.map_err(db_err)?;
        Ok(())
    }

    async fn delete_by_book(&self, book_id: &str) -> MoGrabResult<u64> {
        let res = sqlx::query("DELETE FROM chapters WHERE book_id = ?")
            .bind(book_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected())
    }

    async fn search_content(
        &self,
        keyword: &str,
        book_id: Option<&str>,
        limit: i64,
    ) -> MoGrabResult<Vec<ChapterSearchHit>> {
        if keyword.is_empty() {
            return Ok(Vec::new());
        }
        let pattern = format!("%{}%", escape_like(keyword));

        let rows = if let Some(bid) = book_id {
            sqlx::query(
                r#"
                SELECT c.book_id, b.title AS book_title, c.id AS chapter_id,
                       c.title AS chapter_title, c."index" AS chapter_index, c.content
                FROM chapters c
                JOIN books b ON b.id = c.book_id
                WHERE c.content LIKE ? ESCAPE '\' AND c.book_id = ?
                ORDER BY c.book_id ASC, c."index" ASC
                LIMIT ?
                "#,
            )
            .bind(&pattern)
            .bind(bid)
            .bind(limit)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?
        } else {
            sqlx::query(
                r#"
                SELECT c.book_id, b.title AS book_title, c.id AS chapter_id,
                       c.title AS chapter_title, c."index" AS chapter_index, c.content
                FROM chapters c
                JOIN books b ON b.id = c.book_id
                WHERE c.content LIKE ? ESCAPE '\'
                ORDER BY c.book_id ASC, c."index" ASC
                LIMIT ?
                "#,
            )
            .bind(&pattern)
            .bind(limit)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?
        };

        let mut hits = Vec::with_capacity(rows.len());
        for r in rows {
            let content: Option<String> = r.try_get("content").map_err(db_err)?;
            hits.push(ChapterSearchHit {
                book_id: r.try_get("book_id").map_err(db_err)?,
                book_title: r.try_get("book_title").map_err(db_err)?,
                chapter_id: r.try_get("chapter_id").map_err(db_err)?,
                chapter_title: r.try_get("chapter_title").map_err(db_err)?,
                chapter_index: r.try_get("chapter_index").map_err(db_err)?,
                snippet: make_snippet(content.as_deref().unwrap_or(""), keyword, 30),
            });
        }
        Ok(hits)
    }
}

pub fn escape_like(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for ch in value.chars() {
        match ch {
            '\\' | '%' | '_' => {
                out.push('\\');
                out.push(ch);
            }
            _ => out.push(ch),
        }
    }
    out
}

pub fn make_snippet(content: &str, keyword: &str, context_chars: usize) -> String {
    let lower_content = content.to_lowercase();
    let lower_kw = keyword.to_lowercase();

    let byte_idx = content
        .find(keyword)
        .or_else(|| lower_content.find(&lower_kw));

    let Some(match_byte) = byte_idx else {
        return content
            .chars()
            .take(context_chars * 2)
            .collect::<String>()
            .trim()
            .to_string();
    };

    let char_pos = content[..match_byte].chars().count();
    let kw_chars = keyword.chars().count();
    let total_chars = content.chars().count();

    let start_char = char_pos.saturating_sub(context_chars);
    let end_char = (char_pos + kw_chars + context_chars).min(total_chars);

    let slice: String = content
        .chars()
        .skip(start_char)
        .take(end_char - start_char)
        .collect();

    let prefix = if start_char > 0 { "…" } else { "" };
    let suffix = if end_char < total_chars { "…" } else { "" };
    format!("{prefix}{}{suffix}", slice.trim())
}

// ---------------------------------------------------------------------------
// SqliteTaskRepository
// ---------------------------------------------------------------------------
pub struct SqliteTaskRepository {
    db: Database,
}

impl SqliteTaskRepository {
    pub fn new(db: Database) -> Self {
        Self { db }
    }

    fn row_to_task(row: &SqliteRow) -> MoGrabResult<Task> {
        let type_str: String = row.try_get("type").map_err(db_err)?;
        let status_str: String = row.try_get("status").map_err(db_err)?;
        let params_str: String = row.try_get("params").map_err(db_err)?;
        let params: Map<String, Value> = serde_json::from_str(&params_str).unwrap_or_default();
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        let started_str: Option<String> = row.try_get("started_at").map_err(db_err)?;
        let finished_str: Option<String> = row.try_get("finished_at").map_err(db_err)?;

        Ok(Task {
            id: row.try_get("id").map_err(db_err)?,
            task_type: TaskType::from_str_opt(&type_str)
                .ok_or_else(|| MoGrabError::storage(format!("未知任务类型: {type_str}")))?,
            status: TaskStatus::from_str_opt(&status_str)
                .ok_or_else(|| MoGrabError::storage(format!("未知任务状态: {status_str}")))?,
            priority: row.try_get("priority").map_err(db_err)?,
            source_id: row.try_get("source_id").map_err(db_err)?,
            book_id: row.try_get("book_id").map_err(db_err)?,
            total: row.try_get("total").map_err(db_err)?,
            completed: row.try_get("completed").map_err(db_err)?,
            failed: row.try_get("failed").map_err(db_err)?,
            retry_count: row.try_get("retry_count").map_err(db_err)?,
            max_retries: row.try_get("max_retries").map_err(db_err)?,
            resume_cursor: row.try_get("resume_cursor").map_err(db_err)?,
            params,
            error_code: row.try_get("error_code").map_err(db_err)?,
            error_message: row.try_get("error_message").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            started_at: started_str.as_deref().map(parse_dt),
            finished_at: finished_str.as_deref().map(parse_dt),
        })
    }

    fn row_to_item(row: &SqliteRow) -> MoGrabResult<TaskItem> {
        let status_str: String = row.try_get("status").map_err(db_err)?;
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        let updated_str: String = row.try_get("updated_at").map_err(db_err)?;
        Ok(TaskItem {
            id: row.try_get("id").map_err(db_err)?,
            task_id: row.try_get("task_id").map_err(db_err)?,
            chapter_id: row.try_get("chapter_id").map_err(db_err)?,
            chapter_index: row.try_get("chapter_index").map_err(db_err)?,
            title: row.try_get("title").map_err(db_err)?,
            status: TaskItemStatus::from_str_opt(&status_str).unwrap_or(TaskItemStatus::Pending),
            attempts: row.try_get("attempts").map_err(db_err)?,
            error_code: row.try_get("error_code").map_err(db_err)?,
            error_message: row.try_get("error_message").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            updated_at: parse_dt(&updated_str),
        })
    }
}

#[async_trait]
impl TaskRepository for SqliteTaskRepository {
    async fn get(&self, task_id: &str) -> MoGrabResult<Option<Task>> {
        let row = sqlx::query("SELECT * FROM tasks WHERE id = ?")
            .bind(task_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.as_ref().map(Self::row_to_task).transpose()
    }

    async fn save(&self, task: &Task) -> MoGrabResult<()> {
        let params_json = serde_json::to_string(&task.params).unwrap_or_else(|_| "{}".to_string());
        let created = task.created_at.to_rfc3339();
        let started = task.started_at.map(|d| d.to_rfc3339());
        let finished = task.finished_at.map(|d| d.to_rfc3339());

        sqlx::query(
            r#"
            INSERT INTO tasks (
                id, type, status, priority, source_id, book_id,
                total, completed, failed, retry_count, max_retries, resume_cursor,
                params, error_code, error_message, created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type = excluded.type,
                status = excluded.status,
                priority = excluded.priority,
                source_id = excluded.source_id,
                book_id = excluded.book_id,
                total = excluded.total,
                completed = excluded.completed,
                failed = excluded.failed,
                retry_count = excluded.retry_count,
                max_retries = excluded.max_retries,
                resume_cursor = excluded.resume_cursor,
                params = excluded.params,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at
            "#,
        )
        .bind(&task.id)
        .bind(task.task_type.as_str())
        .bind(task.status.as_str())
        .bind(task.priority)
        .bind(&task.source_id)
        .bind(&task.book_id)
        .bind(task.total)
        .bind(task.completed)
        .bind(task.failed)
        .bind(task.retry_count)
        .bind(task.max_retries)
        .bind(task.resume_cursor)
        .bind(&params_json)
        .bind(&task.error_code)
        .bind(&task.error_message)
        .bind(&created)
        .bind(&started)
        .bind(&finished)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(())
    }

    async fn list_all(&self, status: Option<TaskStatus>) -> MoGrabResult<Vec<Task>> {
        let rows = match status {
            Some(st) => {
                sqlx::query("SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC")
                    .bind(st.as_str())
                    .fetch_all(self.db.pool())
                    .await
                    .map_err(db_err)?
            }
            None => sqlx::query("SELECT * FROM tasks ORDER BY created_at DESC")
                .fetch_all(self.db.pool())
                .await
                .map_err(db_err)?,
        };
        rows.iter().map(Self::row_to_task).collect()
    }

    async fn list_by_status(&self, status: TaskStatus) -> MoGrabResult<Vec<Task>> {
        self.list_all(Some(status)).await
    }

    async fn list_items(&self, task_id: &str) -> MoGrabResult<Vec<TaskItem>> {
        let rows =
            sqlx::query("SELECT * FROM task_items WHERE task_id = ? ORDER BY chapter_index ASC")
                .bind(task_id)
                .fetch_all(self.db.pool())
                .await
                .map_err(db_err)?;
        rows.iter().map(Self::row_to_item).collect()
    }

    async fn save_item(&self, item: &TaskItem) -> MoGrabResult<()> {
        let created = item.created_at.to_rfc3339();
        let updated = item.updated_at.to_rfc3339();
        sqlx::query(
            r#"
            INSERT INTO task_items (
                id, task_id, chapter_id, chapter_index, title, status,
                attempts, error_code, error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                chapter_id = excluded.chapter_id,
                chapter_index = excluded.chapter_index,
                title = excluded.title,
                status = excluded.status,
                attempts = excluded.attempts,
                error_code = excluded.error_code,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            "#,
        )
        .bind(&item.id)
        .bind(&item.task_id)
        .bind(&item.chapter_id)
        .bind(item.chapter_index)
        .bind(&item.title)
        .bind(item.status.as_str())
        .bind(item.attempts)
        .bind(&item.error_code)
        .bind(&item.error_message)
        .bind(&created)
        .bind(&updated)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// SqliteSettingsRepository
// ---------------------------------------------------------------------------
pub struct SqliteSettingsRepository {
    db: Database,
}

impl SqliteSettingsRepository {
    pub fn new(db: Database) -> Self {
        Self { db }
    }
}

#[async_trait]
impl SettingsRepository for SqliteSettingsRepository {
    async fn get(&self, key: &str) -> MoGrabResult<Option<String>> {
        let row = sqlx::query("SELECT value FROM settings WHERE key = ?")
            .bind(key)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.map(|r| r.try_get("value").map_err(db_err)).transpose()
    }

    async fn set(&self, key: &str, value: &str) -> MoGrabResult<()> {
        let now = utc_now_iso();
        sqlx::query(
            r#"
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            "#,
        )
        .bind(key)
        .bind(value)
        .bind(&now)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(())
    }

    async fn all(&self) -> MoGrabResult<BTreeMap<String, String>> {
        let rows = sqlx::query("SELECT key, value FROM settings")
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        let mut map = BTreeMap::new();
        for r in rows {
            map.insert(
                r.try_get("key").map_err(db_err)?,
                r.try_get("value").map_err(db_err)?,
            );
        }
        Ok(map)
    }
}

// ---------------------------------------------------------------------------
// SqliteSourceRepository
// ---------------------------------------------------------------------------
pub struct SqliteSourceRepository {
    db: Database,
    sources_dir: PathBuf,
}

#[derive(Debug)]
struct SourceMeta {
    enabled: bool,
    health: HealthStatus,
    installed_version: String,
    previous_version: Option<String>,
    installed_at: Option<DateTime<Utc>>,
    updated_at: Option<DateTime<Utc>>,
}

impl SqliteSourceRepository {
    pub fn new(db: Database, sources_dir: impl AsRef<Path>) -> Self {
        Self {
            db,
            sources_dir: sources_dir.as_ref().to_path_buf(),
        }
    }

    fn row_meta(row: &SqliteRow) -> MoGrabResult<SourceMeta> {
        let enabled_int: i64 = row.try_get("enabled").map_err(db_err)?;
        let health_str: String = row.try_get("health").map_err(db_err)?;
        let inst_at: String = row.try_get("installed_at").map_err(db_err)?;
        let upd_at: String = row.try_get("updated_at").map_err(db_err)?;
        Ok(SourceMeta {
            enabled: enabled_int != 0,
            health: HealthStatus::from_str_opt(&health_str).unwrap_or(HealthStatus::Unknown),
            installed_version: row.try_get("installed_version").map_err(db_err)?,
            previous_version: row.try_get("previous_version").map_err(db_err)?,
            installed_at: Some(parse_dt(&inst_at)),
            updated_at: Some(parse_dt(&upd_at)),
        })
    }

    fn read_spec_opt(path: &Path) -> Option<SourceSpec> {
        if !path.is_file() {
            return None;
        }
        match load_source_file(path) {
            Ok(spec) => Some(spec),
            Err(err) => {
                warn!(path = %path.display(), error = %err, "storage.source_load_failed");
                None
            }
        }
    }
}

#[async_trait]
impl SourceRepository for SqliteSourceRepository {
    fn source_path(&self, source_id: &str) -> PathBuf {
        self.sources_dir.join(source_id).join("source.yaml")
    }

    async fn get(&self, source_id: &str) -> MoGrabResult<Option<InstalledSource>> {
        let row = sqlx::query("SELECT * FROM sources WHERE id = ?")
            .bind(source_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let meta = Self::row_meta(&row)?;
        let path = self.source_path(source_id);
        let spec = tokio::task::spawn_blocking(move || Self::read_spec_opt(&path))
            .await
            .map_err(|e| MoGrabError::storage(e.to_string()))?;

        let Some(spec) = spec else {
            warn!(source_id, "storage.source_file_missing");
            return Ok(None);
        };
        Ok(Some(InstalledSource {
            spec,
            enabled: meta.enabled,
            health: meta.health,
            installed_version: meta.installed_version,
            previous_version: meta.previous_version,
            installed_at: meta.installed_at,
            updated_at: meta.updated_at,
        }))
    }

    async fn save(&self, source: &SourceSpec) -> MoGrabResult<()> {
        let path = self.source_path(&source.id);
        let spec_clone = source.clone();
        tokio::task::spawn_blocking(move || write_source_file(&spec_clone, &path))
            .await
            .map_err(|e| MoGrabError::storage(e.to_string()))??;

        let now = utc_now_iso();
        let caps_json = serde_json::to_string(
            &source
                .capabilities
                .iter()
                .map(|c| c.as_str())
                .collect::<Vec<_>>(),
        )
        .unwrap_or_else(|_| "[]".to_string());

        let existing = sqlx::query("SELECT installed_version FROM sources WHERE id = ?")
            .bind(&source.id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;

        match existing {
            None => {
                sqlx::query(
                    r#"
                    INSERT INTO sources (
                        id, name, version, spec_version, homepage, license, capabilities,
                        enabled, installed_version, previous_version, health, installed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, 'unknown', ?, ?)
                    "#,
                )
                .bind(&source.id)
                .bind(&source.name)
                .bind(&source.version)
                .bind(source.spec_version)
                .bind(&source.homepage)
                .bind(&source.license)
                .bind(&caps_json)
                .bind(&source.version)
                .bind(&now)
                .bind(&now)
                .execute(self.db.pool())
                .await
                .map_err(db_err)?;
            }
            Some(row) => {
                let prev_installed: String = row.try_get("installed_version").map_err(db_err)?;
                let (new_installed, new_previous) = if prev_installed != source.version {
                    (source.version.clone(), Some(prev_installed))
                } else {
                    (prev_installed, None)
                };
                sqlx::query(
                    r#"
                    UPDATE sources SET
                        name = ?,
                        version = ?,
                        spec_version = ?,
                        homepage = ?,
                        license = ?,
                        capabilities = ?,
                        installed_version = ?,
                        previous_version = COALESCE(?, previous_version),
                        updated_at = ?
                    WHERE id = ?
                    "#,
                )
                .bind(&source.name)
                .bind(&source.version)
                .bind(source.spec_version)
                .bind(&source.homepage)
                .bind(&source.license)
                .bind(&caps_json)
                .bind(&new_installed)
                .bind(&new_previous)
                .bind(&now)
                .bind(&source.id)
                .execute(self.db.pool())
                .await
                .map_err(db_err)?;
            }
        }
        Ok(())
    }

    async fn list_all(&self) -> MoGrabResult<Vec<InstalledSource>> {
        let rows = sqlx::query("SELECT * FROM sources")
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;

        let mut entries = Vec::with_capacity(rows.len());
        for r in rows {
            let id: String = r.try_get("id").map_err(db_err)?;
            let meta = Self::row_meta(&r)?;
            entries.push((id, meta));
        }

        let dir = self.sources_dir.clone();
        let installed = tokio::task::spawn_blocking(move || {
            let mut out = Vec::new();
            for (source_id, meta) in entries {
                let path = dir.join(&source_id).join("source.yaml");
                let Some(spec) = Self::read_spec_opt(&path) else {
                    warn!(source_id, "storage.source_file_missing");
                    continue;
                };
                out.push(InstalledSource {
                    spec,
                    enabled: meta.enabled,
                    health: meta.health,
                    installed_version: meta.installed_version,
                    previous_version: meta.previous_version,
                    installed_at: meta.installed_at,
                    updated_at: meta.updated_at,
                });
            }
            out
        })
        .await
        .map_err(|e| MoGrabError::storage(e.to_string()))?;

        Ok(installed)
    }

    async fn list_enabled(&self) -> MoGrabResult<Vec<InstalledSource>> {
        let all = self.list_all().await?;
        Ok(all.into_iter().filter(|s| s.is_usable()).collect())
    }

    async fn delete(&self, source_id: &str) -> MoGrabResult<bool> {
        if !SOURCE_ID_RE.is_match(source_id) {
            return Ok(false);
        }
        let res = sqlx::query("DELETE FROM sources WHERE id = ?")
            .bind(source_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        if res.rows_affected() == 0 {
            return Ok(false);
        }
        let target = self.sources_dir.join(source_id);
        if target.is_dir() {
            let _ = tokio::task::spawn_blocking(move || fs::remove_dir_all(target)).await;
        }
        Ok(true)
    }

    async fn set_enabled(&self, source_id: &str, enabled: bool) -> MoGrabResult<()> {
        let res = sqlx::query("UPDATE sources SET enabled = ?, updated_at = ? WHERE id = ?")
            .bind(if enabled { 1i64 } else { 0i64 })
            .bind(utc_now_iso())
            .bind(source_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        if res.rows_affected() == 0 {
            return Err(MoGrabError::source_not_found(
                format!("书源未安装: {source_id}"),
                json!({"source_id": source_id}),
            ));
        }
        Ok(())
    }

    async fn set_health(&self, source_id: &str, health: HealthStatus) -> MoGrabResult<()> {
        let res = sqlx::query("UPDATE sources SET health = ?, updated_at = ? WHERE id = ?")
            .bind(health.as_str())
            .bind(utc_now_iso())
            .bind(source_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        if res.rows_affected() == 0 {
            return Err(MoGrabError::source_not_found(
                format!("书源未安装: {source_id}"),
                json!({"source_id": source_id}),
            ));
        }
        Ok(())
    }

    async fn rescan(&self) -> MoGrabResult<Vec<InstalledSource>> {
        if !self.sources_dir.is_dir() {
            return Ok(Vec::new());
        }
        let dir = self.sources_dir.clone();
        let found: Vec<SourceSpec> = tokio::task::spawn_blocking(move || {
            let mut specs = Vec::new();
            let Ok(entries) = fs::read_dir(&dir) else {
                return specs;
            };
            let mut paths: Vec<PathBuf> = entries
                .flatten()
                .map(|e| e.path().join("source.yaml"))
                .filter(|p| p.is_file())
                .collect();
            paths.sort();
            for p in paths {
                if let Some(spec) = Self::read_spec_opt(&p) {
                    specs.push(spec);
                }
            }
            specs
        })
        .await
        .map_err(|e| MoGrabError::storage(e.to_string()))?;

        let now = utc_now_iso();
        let found_ids: HashSet<String> = found.iter().map(|s| s.id.clone()).collect();

        let existing_rows = sqlx::query("SELECT id FROM sources")
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        let existing_ids: HashSet<String> = existing_rows
            .iter()
            .filter_map(|r| r.try_get("id").ok())
            .collect();

        let mut tx = self.db.pool().begin().await.map_err(db_err)?;
        for spec in &found {
            let caps_json = serde_json::to_string(
                &spec
                    .capabilities
                    .iter()
                    .map(|c| c.as_str())
                    .collect::<Vec<_>>(),
            )
            .unwrap_or_else(|_| "[]".to_string());

            if !existing_ids.contains(&spec.id) {
                sqlx::query(
                    r#"
                    INSERT INTO sources (
                        id, name, version, spec_version, homepage, license, capabilities,
                        enabled, installed_version, previous_version, health, installed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, NULL, 'unknown', ?, ?)
                    "#,
                )
                .bind(&spec.id)
                .bind(&spec.name)
                .bind(&spec.version)
                .bind(spec.spec_version)
                .bind(&spec.homepage)
                .bind(&spec.license)
                .bind(&caps_json)
                .bind(&spec.version)
                .bind(&now)
                .bind(&now)
                .execute(&mut *tx)
                .await
                .map_err(db_err)?;
            } else {
                sqlx::query(
                    r#"
                    UPDATE sources SET
                        name = ?,
                        version = ?,
                        spec_version = ?,
                        homepage = ?,
                        license = ?,
                        capabilities = ?,
                        installed_version = ?,
                        updated_at = ?
                    WHERE id = ?
                    "#,
                )
                .bind(&spec.name)
                .bind(&spec.version)
                .bind(spec.spec_version)
                .bind(&spec.homepage)
                .bind(&spec.license)
                .bind(&caps_json)
                .bind(&spec.version)
                .bind(&now)
                .bind(&spec.id)
                .execute(&mut *tx)
                .await
                .map_err(db_err)?;
            }
        }

        for id in existing_ids {
            if !found_ids.contains(&id) {
                sqlx::query("DELETE FROM sources WHERE id = ?")
                    .bind(&id)
                    .execute(&mut *tx)
                    .await
                    .map_err(db_err)?;
            }
        }
        tx.commit().await.map_err(db_err)?;
        self.list_all().await
    }
}

// ---------------------------------------------------------------------------
// SqliteExportRepository
// ---------------------------------------------------------------------------
pub struct SqliteExportRepository {
    db: Database,
}

impl SqliteExportRepository {
    pub fn new(db: Database) -> Self {
        Self { db }
    }

    fn row_to_export(row: &SqliteRow) -> MoGrabResult<ExportRecord> {
        let fmt_str: String = row.try_get("format").map_err(db_err)?;
        let status_str: String = row.try_get("status").map_err(db_err)?;
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        let finished_str: Option<String> = row.try_get("finished_at").map_err(db_err)?;
        Ok(ExportRecord {
            id: row.try_get("id").map_err(db_err)?,
            book_id: row.try_get("book_id").map_err(db_err)?,
            format: ExportFormat::from_str_opt(&fmt_str).unwrap_or(ExportFormat::Epub),
            status: ExportStatus::from_str_opt(&status_str).unwrap_or(ExportStatus::Pending),
            path: row.try_get("path").map_err(db_err)?,
            size_bytes: row.try_get("size_bytes").map_err(db_err)?,
            error_message: row.try_get("error_message").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            finished_at: finished_str.as_deref().map(parse_dt),
        })
    }
}

#[async_trait]
impl ExportRepository for SqliteExportRepository {
    async fn save(&self, record: &ExportRecord) -> MoGrabResult<()> {
        let created = record.created_at.to_rfc3339();
        let finished = record.finished_at.map(|d| d.to_rfc3339());
        sqlx::query(
            r#"
            INSERT INTO exports (
                id, book_id, format, status, path, size_bytes, error_message, created_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                book_id = excluded.book_id,
                format = excluded.format,
                status = excluded.status,
                path = excluded.path,
                size_bytes = excluded.size_bytes,
                error_message = excluded.error_message,
                finished_at = excluded.finished_at
            "#,
        )
        .bind(&record.id)
        .bind(&record.book_id)
        .bind(record.format.as_str())
        .bind(record.status.as_str())
        .bind(&record.path)
        .bind(record.size_bytes)
        .bind(&record.error_message)
        .bind(&created)
        .bind(&finished)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(())
    }

    async fn get(&self, export_id: &str) -> MoGrabResult<Option<ExportRecord>> {
        let row = sqlx::query("SELECT * FROM exports WHERE id = ?")
            .bind(export_id)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        row.as_ref().map(Self::row_to_export).transpose()
    }

    async fn list_by_book(&self, book_id: &str) -> MoGrabResult<Vec<ExportRecord>> {
        let rows = sqlx::query("SELECT * FROM exports WHERE book_id = ? ORDER BY created_at DESC")
            .bind(book_id)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        rows.iter().map(Self::row_to_export).collect()
    }

    async fn list_recent(&self, limit: i64) -> MoGrabResult<Vec<ExportRecord>> {
        let rows = sqlx::query("SELECT * FROM exports ORDER BY created_at DESC LIMIT ?")
            .bind(limit)
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;
        rows.iter().map(Self::row_to_export).collect()
    }
}

// ---------------------------------------------------------------------------
// SqliteHttpCache
// ---------------------------------------------------------------------------
pub struct SqliteHttpCache {
    db: Database,
    max_size_bytes: u64,
}

impl SqliteHttpCache {
    pub fn new(db: Database, max_size_bytes: u64) -> Self {
        Self { db, max_size_bytes }
    }

    pub async fn enforce_capacity(&self) -> MoGrabResult<usize> {
        if self.max_size_bytes == 0 {
            return Ok(0);
        }
        let rows = sqlx::query("SELECT key, size_bytes FROM http_cache ORDER BY accessed_at ASC")
            .fetch_all(self.db.pool())
            .await
            .map_err(db_err)?;

        let mut total: u64 = 0;
        let mut entries: Vec<(String, u64)> = Vec::with_capacity(rows.len());
        for r in rows {
            let key: String = r.try_get("key").map_err(db_err)?;
            let sz: i64 = r.try_get("size_bytes").map_err(db_err)?;
            let sz_u = sz.max(0) as u64;
            total += sz_u;
            entries.push((key, sz_u));
        }

        if total <= self.max_size_bytes {
            return Ok(0);
        }

        let mut doomed = Vec::new();
        for (key, sz) in entries {
            if total <= self.max_size_bytes {
                break;
            }
            doomed.push(key);
            total = total.saturating_sub(sz);
        }

        if !doomed.is_empty() {
            let mut tx = self.db.pool().begin().await.map_err(db_err)?;
            for key in &doomed {
                sqlx::query("DELETE FROM http_cache WHERE key = ?")
                    .bind(key)
                    .execute(&mut *tx)
                    .await
                    .map_err(db_err)?;
            }
            tx.commit().await.map_err(db_err)?;
            info!(removed = doomed.len(), "storage.cache_evicted");
        }
        Ok(doomed.len())
    }
}

#[async_trait]
impl HttpCache for SqliteHttpCache {
    async fn get(&self, key: &str) -> MoGrabResult<Option<CacheEntry>> {
        let row = sqlx::query("SELECT * FROM http_cache WHERE key = ?")
            .bind(key)
            .fetch_optional(self.db.pool())
            .await
            .map_err(db_err)?;
        let Some(row) = row else {
            return Ok(None);
        };

        let expires_str: String = row.try_get("expires_at").map_err(db_err)?;
        let expires_at = parse_dt(&expires_str);
        let now = Utc::now();

        if expires_at <= now {
            sqlx::query("DELETE FROM http_cache WHERE key = ?")
                .bind(key)
                .execute(self.db.pool())
                .await
                .map_err(db_err)?;
            return Ok(None);
        }

        let accessed_str: String = row.try_get("accessed_at").map_err(db_err)?;
        let accessed_at = parse_dt(&accessed_str);
        if now - accessed_at >= Duration::hours(1) {
            let _ = sqlx::query("UPDATE http_cache SET accessed_at = ? WHERE key = ?")
                .bind(now.to_rfc3339())
                .bind(key)
                .execute(self.db.pool())
                .await;
        }

        let status_i64: i64 = row.try_get("status_code").map_err(db_err)?;
        let created_str: String = row.try_get("created_at").map_err(db_err)?;
        Ok(Some(CacheEntry {
            key: row.try_get("key").map_err(db_err)?,
            source_id: row.try_get("source_id").map_err(db_err)?,
            url: row.try_get("url").map_err(db_err)?,
            status_code: status_i64 as u16,
            content: row.try_get("content").map_err(db_err)?,
            encoding: row.try_get("encoding").map_err(db_err)?,
            created_at: parse_dt(&created_str),
            expires_at,
        }))
    }

    async fn put(&self, entry: CacheEntry) -> MoGrabResult<()> {
        let created = entry.created_at.to_rfc3339();
        let expires = entry.expires_at.to_rfc3339();
        let accessed = utc_now_iso();
        let size = entry.size();

        sqlx::query(
            r#"
            INSERT INTO http_cache (
                key, source_id, url, status_code, encoding, content,
                created_at, expires_at, accessed_at, size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                source_id = excluded.source_id,
                url = excluded.url,
                status_code = excluded.status_code,
                encoding = excluded.encoding,
                content = excluded.content,
                expires_at = excluded.expires_at,
                accessed_at = excluded.accessed_at,
                size_bytes = excluded.size_bytes
            "#,
        )
        .bind(&entry.key)
        .bind(&entry.source_id)
        .bind(&entry.url)
        .bind(entry.status_code as i64)
        .bind(&entry.encoding)
        .bind(&entry.content)
        .bind(&created)
        .bind(&expires)
        .bind(&accessed)
        .bind(size)
        .execute(self.db.pool())
        .await
        .map_err(db_err)?;

        let _ = self.enforce_capacity().await?;
        Ok(())
    }

    async fn invalidate_url(&self, source_id: &str, url: &str) -> MoGrabResult<u64> {
        let res = sqlx::query("DELETE FROM http_cache WHERE source_id = ? AND url = ?")
            .bind(source_id)
            .bind(url)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected())
    }

    async fn invalidate_source(&self, source_id: &str) -> MoGrabResult<u64> {
        let res = sqlx::query("DELETE FROM http_cache WHERE source_id = ?")
            .bind(source_id)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected())
    }

    async fn clear(&self) -> MoGrabResult<u64> {
        let res = sqlx::query("DELETE FROM http_cache")
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected())
    }

    async fn purge_expired(&self) -> MoGrabResult<u64> {
        let now = utc_now_iso();
        let res = sqlx::query("DELETE FROM http_cache WHERE expires_at <= ?")
            .bind(&now)
            .execute(self.db.pool())
            .await
            .map_err(db_err)?;
        Ok(res.rows_affected())
    }

    async fn stats(&self) -> MoGrabResult<CacheStats> {
        let row = sqlx::query(
            "SELECT COUNT(key) AS cnt, COALESCE(SUM(size_bytes), 0) AS total FROM http_cache",
        )
        .fetch_one(self.db.pool())
        .await
        .map_err(db_err)?;
        Ok(CacheStats {
            entries: row.try_get("cnt").map_err(db_err)?,
            size_bytes: row.try_get("total").map_err(db_err)?,
            max_size_bytes: self.max_size_bytes,
        })
    }
}

// Keep unused imports clean in release
#[allow(dead_code)]
fn _unused_map_guard(_: &HashMap<String, String>) {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::ids::new_id;

    #[tokio::test]
    async fn test_sqlite_books_chapters_search_and_cache() {
        let dir = tempfile::tempdir().unwrap();
        let db = Database::open(dir.path().join("mograb.db")).await.unwrap();
        db.init_schema().await.unwrap();

        let sources = SqliteSourceRepository::new(db.clone(), dir.path().join("sources"));
        let books = SqliteBookRepository::new(db.clone());
        let chapters = SqliteChapterRepository::new(db.clone());
        let cache = SqliteHttpCache::new(db.clone(), 100);

        let ex_yaml = include_str!("../../../../tests/fixtures/example-source/source.yaml");
        let spec = crate::source::load_source_str(ex_yaml, "test").unwrap();
        sources.save(&spec).await.unwrap();
        assert_eq!(sources.list_all().await.unwrap().len(), 1);

        let now = Utc::now();
        let book = Book {
            id: new_id("book"),
            source_id: spec.id.clone(),
            source_book_id: "1001".into(),
            url: "https://example.com/book/1001".into(),
            title: "三体".into(),
            author: Some("刘慈欣".into()),
            intro: None,
            language: Some("zh-CN".into()),
            cover_url: None,
            cover_path: None,
            status: BookStatus::Ongoing,
            latest_chapter: None,
            word_count: 100,
            chapter_count: 1,
            created_at: now,
            updated_at: now,
            metadata: Map::new(),
        };
        books.save(&book).await.unwrap();

        let ch = Chapter {
            id: new_id("chap"),
            book_id: book.id.clone(),
            source_chapter_id: Some("c1".into()),
            title: "第一章".into(),
            url: "https://example.com/1".into(),
            index: 0,
            content: Some("这里有 100% 纯正的中文故事片段。".into()),
            content_hash: Some("abc".into()),
            word_count: 15,
            created_at: now,
            updated_at: now,
        };
        chapters.save_many(&[ch]).await.unwrap();

        let hits = chapters.search_content("100%", None, 10).await.unwrap();
        assert_eq!(hits.len(), 1);
        assert!(hits[0].snippet.contains("100%"));
        assert!(
            chapters
                .search_content("100_%", None, 10)
                .await
                .unwrap()
                .is_empty()
        );

        let e1 = CacheEntry {
            key: "k1".into(),
            source_id: "example".into(),
            url: "https://example.com/1".into(),
            status_code: 200,
            content: vec![1u8; 60],
            encoding: Some("utf-8".into()),
            created_at: now,
            expires_at: now + Duration::minutes(10),
        };
        let e2 = CacheEntry {
            key: "k2".into(),
            source_id: "example".into(),
            url: "https://example.com/2".into(),
            status_code: 200,
            content: vec![2u8; 60],
            encoding: Some("utf-8".into()),
            created_at: now,
            expires_at: now + Duration::minutes(10),
        };
        cache.put(e1).await.unwrap();
        cache.put(e2).await.unwrap();
        let st = cache.stats().await.unwrap();
        assert_eq!(st.entries, 1);
        assert_eq!(st.size_bytes, 60);
    }
}
