// SPDX-License-Identifier: GPL-3.0-only
//! `mog update` —— 增量检测并更新已入库书籍的新章节。

use crate::common::{CliExit, EXIT_ERROR, EXIT_NOT_FOUND, emit_json, fail_err, fail_msg, open_app};
use clap::Args;
use mograb_core::domain::enums::{TaskStatus, TaskType};
use mograb_core::task::scheduler::compute_chapter_diff;
use serde_json::{Map, json};

#[derive(Debug, Args)]
pub struct UpdateArgs {
    /// 书籍 ID
    pub book_id: String,
    /// 仅检查差异，不实际下载
    #[arg(long)]
    pub dry_run: bool,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: UpdateArgs, verbose: bool) -> Result<(), CliExit> {
    let app = open_app(verbose, args.json).await?;
    let Some(book) = app
        .books
        .get(&args.book_id)
        .await
        .map_err(|e| fail_err(&e, args.json))?
    else {
        app.aclose().await;
        return Err(fail_msg(
            "ENTITY_NOT_FOUND",
            &format!("书籍不存在: {}", args.book_id),
            Map::new(),
            EXIT_NOT_FOUND,
            args.json,
        ));
    };

    if args.dry_run {
        let Some(src) = app
            .sources
            .get(&book.source_id)
            .await
            .map_err(|e| fail_err(&e, args.json))?
        else {
            app.aclose().await;
            return Err(fail_msg(
                "SOURCE_NOT_FOUND",
                &format!("书源不存在: {}", book.source_id),
                Map::new(),
                EXIT_NOT_FOUND,
                args.json,
            ));
        };
        let draft_book = app
            .engine
            .fetch_book(&src.spec, &book.url)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        let remote = app
            .engine
            .fetch_chapters(&src.spec, &draft_book.url)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        let local = app
            .chapters
            .list_by_book(&book.id)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        app.aclose().await;

        let diff = compute_chapter_diff(&local, &remote);
        if args.json {
            let new_titles: Vec<_> = diff.new.iter().map(|c| &c.title).collect();
            let changed_titles: Vec<_> = diff.changed.iter().map(|c| &c.title).collect();
            emit_json(&json!({
                "book_id": book.id,
                "title": book.title,
                "dry_run": true,
                "new_count": diff.new.len(),
                "changed_count": diff.changed.len(),
                "missing_count": diff.missing.len(),
                "unchanged_count": diff.unchanged.len(),
                "new_titles": new_titles,
                "changed_titles": changed_titles,
            }));
        } else {
            println!("《{}》增量检查（dry-run）:", book.title);
            println!(
                "  新增: {} 章，变更: {} 章，缺失: {} 章，未变: {} 章",
                diff.new.len(),
                diff.changed.len(),
                diff.missing.len(),
                diff.unchanged.len()
            );
            for ch in diff.new.iter().take(10) {
                println!("  + {}", ch.title);
            }
        }
        return Ok(());
    }

    let task = app
        .run_task(
            TaskType::UpdateBook,
            Some(book.id.clone()),
            Some(book.source_id.clone()),
            Map::new(),
            None,
        )
        .await
        .map_err(|e| fail_err(&e, args.json))?;
    app.aclose().await;

    if task.status != TaskStatus::Success {
        return Err(fail_msg(
            task.error_code.as_deref().unwrap_or("UPDATE_ERROR"),
            task.error_message.as_deref().unwrap_or("更新任务未成功"),
            Map::new(),
            EXIT_ERROR,
            args.json,
        ));
    }

    if args.json {
        emit_json(&json!({
            "task_id": task.id,
            "book_id": book.id,
            "title": book.title,
            "total": task.total,
            "completed": task.completed,
            "failed": task.failed,
        }));
    } else {
        println!(
            "更新完成: 《{}》 本次处理 {}/{} 章 (失败 {})",
            book.title, task.completed, task.total, task.failed
        );
    }
    Ok(())
}
