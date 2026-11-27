// SPDX-License-Identifier: GPL-3.0-only
//! `mog export` —— 导出本地已下载书籍（txt / markdown / epub）。

use crate::common::{CliExit, EXIT_ERROR, emit_json, fail_err, fail_msg, open_app};
use clap::Args;
use mograb_core::domain::enums::TaskType;
use serde_json::{Map, Value, json};

#[derive(Debug, Args)]
pub struct ExportArgs {
    /// 书籍 ID
    pub book_id: String,
    /// 导出格式（txt / markdown / epub）
    #[arg(short = 'f', long)]
    pub format: Option<String>,
    /// 输出文件路径
    #[arg(short = 'o', long)]
    pub output: Option<String>,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: ExportArgs, verbose: bool) -> Result<(), CliExit> {
    let app = open_app(verbose, args.json).await?;
    let book = match app
        .books
        .get(&args.book_id)
        .await
        .map_err(|e| fail_err(&e, args.json))?
    {
        Some(b) => b,
        None => {
            app.aclose().await;
            return Err(fail_msg(
                "ENTITY_NOT_FOUND",
                &format!("书籍不存在: {}", args.book_id),
                Map::new(),
                crate::common::EXIT_NOT_FOUND,
                args.json,
            ));
        }
    };

    if book.chapter_count == 0 {
        app.aclose().await;
        return Err(fail_msg(
            "EXPORT_ERROR",
            &format!("书籍 {:?} 暂无任何已下载章节，无法导出", book.title),
            Map::new(),
            EXIT_ERROR,
            args.json,
        ));
    }

    let fmt = args
        .format
        .unwrap_or_else(|| app.settings.output.format.clone());
    let mut params = Map::new();
    params.insert("format".to_string(), Value::String(fmt.clone()));
    if let Some(ref out) = args.output {
        params.insert("target".to_string(), Value::String(out.clone()));
    }

    let task = app
        .run_task(
            TaskType::ExportBook,
            Some(book.id.clone()),
            Some(book.source_id.clone()),
            params,
            None,
        )
        .await
        .map_err(|e| fail_err(&e, args.json))?;

    let export_id = task
        .params
        .get("export_id")
        .and_then(|v| v.as_str())
        .map(str::to_string);
    let export_path = task
        .params
        .get("path")
        .and_then(|v| v.as_str())
        .map(str::to_string);
    let size_bytes = if let Some(ref eid) = export_id {
        app.exports
            .get(eid)
            .await
            .ok()
            .flatten()
            .map(|r| r.size_bytes)
            .unwrap_or(0)
    } else {
        0
    };
    app.aclose().await;

    if let Some(err_msg) = task.error_message {
        let code = task.error_code.as_deref().unwrap_or("EXPORT_ERROR");
        return Err(fail_msg(code, &err_msg, Map::new(), EXIT_ERROR, args.json));
    }

    let path_str = export_path.unwrap_or_default();
    if args.json {
        emit_json(&json!({
            "export_id": export_id,
            "book_id": book.id,
            "title": book.title,
            "format": fmt,
            "path": path_str,
            "size_bytes": size_bytes,
        }));
    } else {
        println!(
            "导出成功: 《{}》 ({}) -> {} ({} 字节)",
            book.title, fmt, path_str, size_bytes
        );
    }
    Ok(())
}
