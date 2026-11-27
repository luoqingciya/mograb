// SPDX-License-Identifier: GPL-3.0-only
//! Book 领域模型。

use super::enums::BookStatus;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Book {
    pub id: String,
    pub source_id: String,
    pub source_book_id: String,
    pub url: String,
    pub title: String,
    pub author: Option<String>,
    pub intro: Option<String>,
    pub language: Option<String>,
    pub cover_url: Option<String>,
    pub cover_path: Option<String>,
    pub status: BookStatus,
    pub latest_chapter: Option<String>,
    pub word_count: i64,
    pub chapter_count: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub metadata: Map<String, Value>,
}

impl Book {
    pub fn identity(&self) -> (&str, &str) {
        (&self.source_id, &self.source_book_id)
    }
}
