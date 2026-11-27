// SPDX-License-Identifier: GPL-3.0-only
//! TXT 导出器。

use super::base::{ExportResult, Exporter};
use crate::domain::book::Book;
use crate::domain::chapter::Chapter;
use crate::domain::enums::ExportFormat;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use serde_json::json;
use std::fs;
use std::path::Path;
use tracing::info;

pub const CHAPTER_SEPARATOR: &str = "\n\n========================================\n\n";

#[derive(Debug, Clone)]
pub struct TxtExporter {
    include_header: bool,
}

impl Default for TxtExporter {
    fn default() -> Self {
        Self {
            include_header: true,
        }
    }
}

impl TxtExporter {
    pub fn new(include_header: bool) -> Self {
        Self { include_header }
    }

    pub fn render(&self, book: &Book, chapters: &[Chapter]) -> String {
        let mut parts = Vec::new();
        if self.include_header {
            parts.push(Self::render_header(book));
        }
        for ch in chapters {
            parts.push(Self::render_chapter(ch));
        }
        let joined = parts.concat();
        format!("{}\n", joined.trim())
    }

    fn render_header(book: &Book) -> String {
        let mut lines = vec![book.title.clone()];
        if let Some(ref author) = book.author
            && !author.is_empty()
        {
            lines.push(format!("作者：{author}"));
        }
        if let Some(ref intro) = book.intro
            && !intro.is_empty()
        {
            lines.push(String::new());
            lines.push(intro.clone());
        }
        format!("{}{CHAPTER_SEPARATOR}", lines.join("\n"))
    }

    fn render_chapter(chapter: &Chapter) -> String {
        let body = chapter.content.as_deref().unwrap_or("");
        format!("{}\n\n{body}{CHAPTER_SEPARATOR}", chapter.title)
    }
}

#[async_trait]
impl Exporter for TxtExporter {
    fn format(&self) -> ExportFormat {
        ExportFormat::Txt
    }

    async fn export(
        &self,
        book: &Book,
        chapters: &[Chapter],
        target: &Path,
    ) -> MoGrabResult<ExportResult> {
        let content = self.render(book, chapters);
        let target_owned = target.to_path_buf();
        let size = tokio::task::spawn_blocking(move || -> std::io::Result<u64> {
            if let Some(parent) = target_owned.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::write(&target_owned, content.as_bytes())?;
            Ok(fs::metadata(&target_owned)?.len())
        })
        .await
        .map_err(|e| MoGrabError::export(e.to_string(), json!({})))?
        .map_err(|e| MoGrabError::export(format!("TXT 写入失败: {e}"), json!({})))?;

        info!(book_id = %book.id, path = %target.display(), size, "export.txt");
        Ok(ExportResult {
            book_id: book.id.clone(),
            format: ExportFormat::Txt,
            path: target.to_path_buf(),
            size_bytes: size,
            chapter_count: chapters.len(),
            warnings: Vec::new(),
        })
    }
}
