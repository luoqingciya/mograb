// SPDX-License-Identifier: GPL-3.0-only
//! Export 模块入口与工厂函数。

pub mod base;
pub mod epub;
pub mod markdown;
pub mod txt;

pub use base::{
    DEFAULT_BOOK_TEMPLATE, DEFAULT_CHAPTER_TEMPLATE, ExportResult, Exporter, book_variables,
    render_filename, render_template, safe_path, sanitize_component,
};
pub use epub::EpubExporter;
pub use markdown::MarkdownExporter;
pub use txt::TxtExporter;

use crate::domain::enums::ExportFormat;
use crate::errors::{MoGrabError, MoGrabResult};
use serde_json::json;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;

pub fn get_exporter(
    fmt: &str,
    covers_dir: Option<PathBuf>,
    metadata: BTreeMap<String, String>,
) -> MoGrabResult<Arc<dyn Exporter>> {
    let parsed = ExportFormat::from_str_opt(fmt).ok_or_else(|| {
        MoGrabError::export(
            format!("不支持的导出格式: {fmt}（可选 txt / markdown / epub）"),
            json!({"format": fmt}),
        )
    })?;
    Ok(match parsed {
        ExportFormat::Txt => Arc::new(TxtExporter::default()),
        ExportFormat::Markdown => Arc::new(MarkdownExporter::default()),
        ExportFormat::Epub => Arc::new(EpubExporter::new(None, true, covers_dir, metadata)),
    })
}
