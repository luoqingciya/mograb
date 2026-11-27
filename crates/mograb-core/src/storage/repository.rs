// SPDX-License-Identifier: GPL-3.0-only
//! 仓储接口（业务层不直接写 SQL）。

use crate::domain::book::Book;
use crate::domain::chapter::{Chapter, ChapterSearchHit, ChapterSummary};
use crate::domain::enums::{HealthStatus, TaskStatus};
use crate::domain::export::ExportRecord;
use crate::domain::source::{InstalledSource, SourceSpec};
use crate::domain::task::{Task, TaskItem};
use crate::errors::MoGrabResult;
use async_trait::async_trait;
use std::collections::BTreeMap;
use std::path::PathBuf;

#[async_trait]
pub trait SourceRepository: Send + Sync {
    fn source_path(&self, source_id: &str) -> PathBuf;
    async fn get(&self, source_id: &str) -> MoGrabResult<Option<InstalledSource>>;
    async fn save(&self, source: &SourceSpec) -> MoGrabResult<()>;
    async fn list_all(&self) -> MoGrabResult<Vec<InstalledSource>>;
    async fn list_enabled(&self) -> MoGrabResult<Vec<InstalledSource>>;
    async fn delete(&self, source_id: &str) -> MoGrabResult<bool>;
    async fn set_enabled(&self, source_id: &str, enabled: bool) -> MoGrabResult<()>;
    async fn set_health(&self, source_id: &str, health: HealthStatus) -> MoGrabResult<()>;
    async fn rescan(&self) -> MoGrabResult<Vec<InstalledSource>>;
}

#[async_trait]
pub trait BookRepository: Send + Sync {
    async fn get(&self, book_id: &str) -> MoGrabResult<Option<Book>>;
    async fn get_by_identity(
        &self,
        source_id: &str,
        source_book_id: &str,
    ) -> MoGrabResult<Option<Book>>;
    async fn save(&self, book: &Book) -> MoGrabResult<()>;
    async fn list_all(&self, limit: i64, offset: i64) -> MoGrabResult<Vec<Book>>;
    async fn delete(&self, book_id: &str) -> MoGrabResult<bool>;
    async fn count(&self) -> MoGrabResult<i64>;
}

#[async_trait]
pub trait ChapterRepository: Send + Sync {
    async fn get(&self, chapter_id: &str) -> MoGrabResult<Option<Chapter>>;
    async fn list_by_book(&self, book_id: &str) -> MoGrabResult<Vec<Chapter>>;
    async fn list_summaries(&self, book_id: &str) -> MoGrabResult<Vec<ChapterSummary>>;
    async fn get_by_index(&self, book_id: &str, index: i64) -> MoGrabResult<Option<Chapter>>;
    async fn list_identities(&self, book_id: &str) -> MoGrabResult<Vec<(String, String)>>;
    async fn stats_by_book(&self, book_id: &str) -> MoGrabResult<(i64, i64)>;
    async fn save(&self, chapter: &Chapter) -> MoGrabResult<()>;
    async fn save_many(&self, chapters: &[Chapter]) -> MoGrabResult<()>;
    async fn delete_by_book(&self, book_id: &str) -> MoGrabResult<u64>;
    async fn search_content(
        &self,
        keyword: &str,
        book_id: Option<&str>,
        limit: i64,
    ) -> MoGrabResult<Vec<ChapterSearchHit>>;
}

#[async_trait]
pub trait TaskRepository: Send + Sync {
    async fn get(&self, task_id: &str) -> MoGrabResult<Option<Task>>;
    async fn save(&self, task: &Task) -> MoGrabResult<()>;
    async fn list_all(&self, status: Option<TaskStatus>) -> MoGrabResult<Vec<Task>>;
    async fn list_by_status(&self, status: TaskStatus) -> MoGrabResult<Vec<Task>>;
    async fn list_items(&self, task_id: &str) -> MoGrabResult<Vec<TaskItem>>;
    async fn save_item(&self, item: &TaskItem) -> MoGrabResult<()>;
}

#[async_trait]
pub trait ExportRepository: Send + Sync {
    async fn save(&self, record: &ExportRecord) -> MoGrabResult<()>;
    async fn get(&self, export_id: &str) -> MoGrabResult<Option<ExportRecord>>;
    async fn list_by_book(&self, book_id: &str) -> MoGrabResult<Vec<ExportRecord>>;
    async fn list_recent(&self, limit: i64) -> MoGrabResult<Vec<ExportRecord>>;
}

#[async_trait]
pub trait SettingsRepository: Send + Sync {
    async fn get(&self, key: &str) -> MoGrabResult<Option<String>>;
    async fn set(&self, key: &str, value: &str) -> MoGrabResult<()>;
    async fn all(&self) -> MoGrabResult<BTreeMap<String, String>>;
}
