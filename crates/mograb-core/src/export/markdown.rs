// SPDX-License-Identifier: GPL-3.0-only
//! Markdown 导出器。

use super::base::{ExportResult, Exporter};
use crate::content::normalizer::split_paragraphs;
use crate::domain::book::Book;
use crate::domain::chapter::Chapter;
use crate::domain::enums::ExportFormat;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use serde_json::json;
use std::fs;
use std::path::Path;
use tracing::info;

#[derive(Debug, Clone)]
pub struct MarkdownExporter {
    heading_level: usize,
}

impl Default for MarkdownExporter {
    fn default() -> Self {
        Self { heading_level: 2 }
    }
}

impl MarkdownExporter {
    pub fn new(heading_level: usize) -> Self {
        Self {
            heading_level: heading_level.clamp(1, 6),
        }
    }

    pub fn render(&self, book: &Book, chapters: &[Chapter]) -> String {
        let mut parts = vec![self.render_header(book)];
        for ch in chapters {
            parts.push(self.render_chapter(ch));
        }
        format!("{}\n", parts.join("\n").trim())
    }

    fn render_header(&self, book: &Book) -> String {
        let mut lines = vec![format!("# {}", book.title), String::new()];
        if let Some(ref author) = book.author
            && !author.is_empty()
        {
            lines.push(format!("- 作者：{author}"));
        }
        lines.push(format!("- 来源：{}", book.source_id));
        if let Some(ref intro) = book.intro
            && !intro.is_empty()
        {
            lines.push(String::new());
            lines.push(format!("> {intro}"));
        }
        lines.join("\n")
    }

    fn render_chapter(&self, chapter: &Chapter) -> String {
        let hashes = "#".repeat(self.heading_level);
        let paragraphs = split_paragraphs(chapter.content.as_deref().unwrap_or(""));
        let body = if paragraphs.is_empty() {
            "_（本章内容为空）_".to_string()
        } else {
            paragraphs.join("\n\n")
        };
        format!("{hashes} {}\n\n{body}", chapter.title)
    }
}

#[async_trait]
impl Exporter for MarkdownExporter {
    fn format(&self) -> ExportFormat {
        ExportFormat::Markdown
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
        .map_err(|e| MoGrabError::export(format!("Markdown 写入失败: {e}"), json!({})))?;

        info!(book_id = %book.id, path = %target.display(), size, "export.markdown");
        Ok(ExportResult {
            book_id: book.id.clone(),
            format: ExportFormat::Markdown,
            path: target.to_path_buf(),
            size_bytes: size,
            chapter_count: chapters.len(),
            warnings: Vec::new(),
        })
    }
}
