// SPDX-License-Identifier: GPL-3.0-only
//! 导出层公共契约、文件名渲染与路径安全校验。

use crate::domain::book::Book;
use crate::domain::chapter::Chapter;
use crate::domain::enums::ExportFormat;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use regex::{Captures, Regex};
use serde_json::json;
use std::collections::BTreeMap;
use std::path::{Component, Path, PathBuf};
use std::sync::LazyLock;

static ILLEGAL_CHARS_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"[<>:"/\\|?*\x00-\x1f]"#).expect("valid ILLEGAL_CHARS_RE"));
static MULTI_WS_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\s+").expect("valid MULTI_WS_RE"));
static TEMPLATE_VAR_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\{\{\s*([\w.]+)\s*\}\}").expect("valid TEMPLATE_VAR_RE"));

const RESERVED_NAMES: &[&str] = &[
    "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8",
    "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
];

pub const DEFAULT_BOOK_TEMPLATE: &str = "{{author}} - {{title}}";
pub const DEFAULT_CHAPTER_TEMPLATE: &str = "{{index}}. {{title}}";

#[derive(Debug, Clone)]
pub struct ExportResult {
    pub book_id: String,
    pub format: ExportFormat,
    pub path: PathBuf,
    pub size_bytes: u64,
    pub chapter_count: usize,
    pub warnings: Vec<String>,
}

#[async_trait]
pub trait Exporter: Send + Sync {
    fn format(&self) -> ExportFormat;
    async fn export(
        &self,
        book: &Book,
        chapters: &[Chapter],
        target: &Path,
    ) -> MoGrabResult<ExportResult>;
}

pub fn book_variables(book: &Book) -> BTreeMap<String, String> {
    let mut map = BTreeMap::new();
    map.insert(
        "title".to_string(),
        if book.title.is_empty() {
            "untitled".to_string()
        } else {
            book.title.clone()
        },
    );
    map.insert(
        "author".to_string(),
        book.author
            .clone()
            .filter(|a| !a.is_empty())
            .unwrap_or_else(|| "unknown".to_string()),
    );
    map.insert("source_id".to_string(), book.source_id.clone());
    map.insert("source_book_id".to_string(), book.source_book_id.clone());
    map.insert(
        "latest_chapter".to_string(),
        book.latest_chapter.clone().unwrap_or_default(),
    );
    map.insert("status".to_string(), book.status.as_str().to_string());
    map
}

pub fn render_template(template: &str, values: &BTreeMap<String, String>) -> String {
    TEMPLATE_VAR_RE
        .replace_all(template, |caps: &Captures<'_>| {
            values.get(&caps[1]).cloned().unwrap_or_default()
        })
        .into_owned()
}

pub fn render_filename(template: &str, book: &Book, chapter: Option<&Chapter>) -> String {
    let mut values = book_variables(book);
    if let Some(ch) = chapter {
        values.insert("index".to_string(), ch.index.to_string());
        values.insert("chapter_title".to_string(), ch.title.clone());
        values.insert("chapter_id".to_string(), ch.id.clone());
    }
    sanitize_component(&render_template(template, &values))
}

pub fn sanitize_component(name: &str) -> String {
    let replaced = ILLEGAL_CHARS_RE.replace_all(name, "_");
    let trimmed = replaced.trim().trim_matches('.');
    let collapsed = MULTI_WS_RE.replace_all(trimmed, " ");
    let mut cleaned = if collapsed.is_empty() {
        "untitled".to_string()
    } else {
        collapsed.into_owned()
    };

    let stem = cleaned.split('.').next().unwrap_or("").to_uppercase();
    if RESERVED_NAMES.contains(&stem.as_str()) {
        cleaned = format!("_{cleaned}");
    }

    // 限制 150 个 Unicode 标量值（绝不截断 UTF-8 字节边界）
    cleaned.chars().take(150).collect()
}

pub fn safe_path(base_dir: &Path, components: &[&str]) -> MoGrabResult<PathBuf> {
    let base = normalize_abs(base_dir)?;
    let mut candidate = base.clone();
    for &component in components {
        assert_component_safe(component)?;
        candidate.push(component);
    }
    let resolved = normalize_abs(&candidate)?;
    if !resolved.starts_with(&base) {
        return Err(MoGrabError::unsafe_path(
            format!(
                "路径越界: {} 不在 {} 之下",
                resolved.display(),
                base.display()
            ),
            json!({
                "base": base.display().to_string(),
                "candidate": resolved.display().to_string(),
            }),
        ));
    }
    Ok(resolved)
}

fn assert_component_safe(component: &str) -> MoGrabResult<()> {
    if component.is_empty() || component == "." || component == ".." {
        return Err(MoGrabError::unsafe_path(
            format!("非法路径组件: {component:?}"),
            json!({"component": component}),
        ));
    }
    if component.contains('/') || component.contains('\\') || component.contains('\0') {
        return Err(MoGrabError::unsafe_path(
            format!("路径组件不得包含分隔符: {component:?}"),
            json!({"component": component}),
        ));
    }
    Ok(())
}

fn normalize_abs(path: &Path) -> MoGrabResult<PathBuf> {
    if let Ok(canon) = std::fs::canonicalize(path) {
        return Ok(canon);
    }
    let abs = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|e| MoGrabError::export(e.to_string(), json!({})))?
            .join(path)
    };
    let mut out = PathBuf::new();
    for comp in abs.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sanitize_and_safe_path() {
        assert_eq!(sanitize_component("a<b>c:d/e"), "a_b_c_d_e");
        assert_eq!(sanitize_component("CON"), "_CON");
        assert_eq!(sanitize_component("..."), "untitled");

        let dir = tempfile::tempdir().unwrap();
        assert!(safe_path(dir.path(), &["out.epub"]).is_ok());
        assert!(safe_path(dir.path(), &["../escape.txt"]).is_err());
        assert!(safe_path(dir.path(), &[".."]).is_err());
    }
}
