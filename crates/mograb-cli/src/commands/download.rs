// SPDX-License-Identifier: GPL-3.0-only
//! `mog download` —— 下载整本（或按目录/URL），并可选直接导出。

use crate::common::{CliExit, EXIT_ERROR, EXIT_USAGE, emit_json, fail_err, fail_msg, open_app};
use async_trait::async_trait;
use clap::Args;
use indicatif::{ProgressBar, ProgressStyle};
use mograb_core::domain::enums::{TaskStatus, TaskType};
use mograb_core::task::scheduler::ProgressHook;
use serde_json::{Map, Value, json};
use std::sync::{Arc, Mutex};

#[derive(Debug, Args)]
pub struct DownloadArgs {
    /// 已入库书籍 ID
    pub book_id: Option<String>,
    /// 书籍详情页 URL（配合 --source 使用）
    #[arg(short = 'u', long)]
    pub url: Option<String>,
    /// 书源 ID（配合 --url 使用）
    #[arg(short = 's', long)]
    pub source: Option<String>,
    /// 下载完成后直接导出格式（txt / markdown / epub）
    #[arg(short = 'f', long)]
    pub format: Option<String>,
    /// 下载完成后导出目标路径
    #[arg(short = 'o', long)]
    pub output: Option<String>,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

struct CliProgressHook {
    bar: Mutex<Option<ProgressBar>>,
}

impl CliProgressHook {
    fn new() -> Self {
        Self {
            bar: Mutex::new(None),
        }
    }

    fn finish(&self) {
        if let Ok(mut guard) = self.bar.lock()
            && let Some(pb) = guard.take()
        {
            pb.finish_and_clear();
        }
    }
}

#[async_trait]
impl ProgressHook for CliProgressHook {
    async fn on_progress(&self, done: usize, total: usize) {
        if let Ok(mut guard) = self.bar.lock() {
            let pb = guard.get_or_insert_with(|| {
                let b = ProgressBar::new(total as u64);
                if let Ok(style) = ProgressStyle::with_template(
                    "{spinner:.cyan} [{elapsed_precise}] [{bar:32.green/dim}] {pos}/{len} ({eta})",
                ) {
                    b.set_style(style.progress_chars("=>-"));
                }
                b
            });
            pb.set_length(total as u64);
            pb.set_position(done as u64);
        }
    }
}

pub async fn run(args: DownloadArgs, verbose: bool) -> Result<(), CliExit> {
    let has_book = args.book_id.as_deref().is_some_and(|s| !s.is_empty());
    let has_url_src = args.url.as_deref().is_some_and(|s| !s.is_empty())
        && args.source.as_deref().is_some_and(|s| !s.is_empty());
    if !has_book && !has_url_src {
        return Err(fail_msg(
            "USAGE_ERROR",
            "需要提供 <book_id>，或同时提供 --url 与 --source",
            Map::new(),
            EXIT_USAGE,
            args.json,
        ));
    }

    let app = open_app(verbose, args.json).await?;
    let mut params = Map::new();
    if let Some(ref u) = args.url {
        params.insert("url".to_string(), Value::String(u.clone()));
    }

    let hook = if args.json {
        None
    } else {
        Some(Arc::new(CliProgressHook::new()))
    };
    let hook_dyn: Option<Arc<dyn ProgressHook>> = hook
        .as_ref()
        .map(|h| Arc::clone(h) as Arc<dyn ProgressHook>);

    let task = app
        .run_task(
            TaskType::DownloadBook,
            args.book_id.clone(),
            args.source.clone(),
            params,
            hook_dyn,
        )
        .await;
    if let Some(h) = &hook {
        h.finish();
    }
    let task = match task {
        Ok(t) => t,
        Err(e) => {
            app.aclose().await;
            return Err(fail_err(&e, args.json));
        }
    };

    if task.status != TaskStatus::Success {
        app.aclose().await;
        let code = task.error_code.as_deref().unwrap_or("DOWNLOAD_ERROR");
        let msg = task.error_message.as_deref().unwrap_or("下载任务未成功");
        return Err(fail_msg(code, msg, Map::new(), EXIT_ERROR, args.json));
    }

    let mut export_info: Option<Value> = None;
    if (args.format.is_some() || args.output.is_some())
        && let Some(ref bid) = task.book_id
    {
        let fmt = args
            .format
            .clone()
            .unwrap_or_else(|| app.settings.output.format.clone());
        let mut exp_params = Map::new();
        exp_params.insert("format".to_string(), Value::String(fmt.clone()));
        if let Some(ref out) = args.output {
            exp_params.insert("target".to_string(), Value::String(out.clone()));
        }
        let exp_task = app
            .run_task(
                TaskType::ExportBook,
                Some(bid.clone()),
                task.source_id.clone(),
                exp_params,
                None,
            )
            .await;
        match exp_task {
            Ok(et) if et.status == TaskStatus::Success => {
                export_info = Some(json!({
                    "format": fmt,
                    "path": et.params.get("path").and_then(|v| v.as_str()).unwrap_or(""),
                    "export_id": et.params.get("export_id").and_then(|v| v.as_str()),
                }));
            }
            Ok(et) => {
                app.aclose().await;
                return Err(fail_msg(
                    et.error_code.as_deref().unwrap_or("EXPORT_ERROR"),
                    et.error_message.as_deref().unwrap_or("导出失败"),
                    Map::new(),
                    EXIT_ERROR,
                    args.json,
                ));
            }
            Err(e) => {
                app.aclose().await;
                return Err(fail_err(&e, args.json));
            }
        }
    }

    let book = if let Some(ref bid) = task.book_id {
        app.books.get(bid).await.ok().flatten()
    } else {
        None
    };
    app.aclose().await;

    if args.json {
        emit_json(&json!({
            "task_id": task.id,
            "book_id": task.book_id,
            "title": book.as_ref().map(|b| b.title.as_str()),
            "total": task.total,
            "completed": task.completed,
            "failed": task.failed,
            "export": export_info,
        }));
    } else {
        let title = book
            .as_ref()
            .map(|b| format!("《{}》", b.title))
            .unwrap_or_else(|| task.book_id.clone().unwrap_or_default());
        println!(
            "下载完成: {title} ({}/{} 章, 失败 {}) [book_id={}]",
            task.completed,
            task.total,
            task.failed,
            task.book_id.as_deref().unwrap_or("-")
        );
        if let Some(exp) = export_info {
            println!(
                "已导出 ({}): {}",
                exp["format"].as_str().unwrap_or("-"),
                exp["path"].as_str().unwrap_or("-")
            );
        }
    }
    Ok(())
}
