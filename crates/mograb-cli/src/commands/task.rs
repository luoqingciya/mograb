// SPDX-License-Identifier: GPL-3.0-only
//! `mog task` —— 任务队列查看与生命周期控制。

use crate::api_client::LocalApiClient;
use crate::common::{
    CliExit, EXIT_USAGE, emit_json, fail_err, fail_msg, new_table, open_app, truncate,
};
use clap::{Args, Subcommand};
use mograb_core::domain::enums::TaskStatus;
use serde_json::{Map, Value};

#[derive(Debug, Args)]
pub struct TaskArgs {
    #[command(subcommand)]
    pub command: TaskCommand,
}

#[derive(Debug, Subcommand)]
pub enum TaskCommand {
    /// 列出任务
    List {
        /// 按状态过滤（queued / running / paused / success / failed / cancelled）
        #[arg(short = 's', long)]
        status: Option<String>,
        /// 返回上限
        #[arg(short = 'n', long, default_value_t = 20)]
        limit: usize,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 查看单个任务详情与条目
    Show {
        /// 任务 ID
        task_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 暂停任务（需运行本地 API 服务）
    Pause {
        /// 任务 ID
        task_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 恢复任务（需运行本地 API 服务）
    Resume {
        /// 任务 ID
        task_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 取消任务（需运行本地 API 服务）
    Cancel {
        /// 任务 ID
        task_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 重试失败或已取消的任务（需运行本地 API 服务）
    Retry {
        /// 任务 ID
        task_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 实时监听任务事件流（SSE）
    Watch {
        /// 限定只监听指定任务 ID（达到终态后自动退出）
        task_id: Option<String>,
        /// 每条事件输出一行 JSON
        #[arg(long)]
        json: bool,
    },
}

fn task_to_json(t: &mograb_core::domain::task::Task) -> Value {
    let progress = (t.progress() * 10000.0).round() / 10000.0;
    serde_json::json!({
        "id": t.id,
        "type": t.task_type.as_str(),
        "status": t.status.as_str(),
        "priority": t.priority,
        "book_id": t.book_id,
        "source_id": t.source_id,
        "total": t.total,
        "completed": t.completed,
        "failed": t.failed,
        "progress": progress,
        "error_code": t.error_code,
        "error_message": t.error_message,
        "params": t.params,
        "created_at": t.created_at,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
    })
}

async fn post_action(task_id: &str, action: &str, json_mode: bool) -> Result<(), CliExit> {
    let client = LocalApiClient::from_config(json_mode)?;
    let resp = client
        .post_json(
            &format!("/api/v1/tasks/{task_id}/{action}"),
            None,
            json_mode,
        )
        .await?;
    if json_mode {
        emit_json(&resp);
    } else {
        println!(
            "任务 {} 状态更新: {}",
            resp["id"].as_str().unwrap_or(task_id),
            resp["status"].as_str().unwrap_or("-")
        );
    }
    Ok(())
}

pub async fn run(args: TaskArgs, verbose: bool) -> Result<(), CliExit> {
    match args.command {
        TaskCommand::List {
            status,
            limit,
            json,
        } => {
            let status_filter = match status.as_deref() {
                Some(s) if !s.is_empty() => Some(TaskStatus::from_str_opt(s).ok_or_else(|| {
                    fail_msg(
                        "USAGE_ERROR",
                        &format!("未知任务状态: {s}"),
                        Map::new(),
                        EXIT_USAGE,
                        json,
                    )
                })?),
                _ => None,
            };
            let app = open_app(verbose, json).await?;
            let tasks = app
                .tasks
                .list_all(status_filter)
                .await
                .map_err(|e| fail_err(&e, json))?;
            app.aclose().await;
            let slice: Vec<_> = tasks.into_iter().take(limit.clamp(1, 200)).collect();
            if json {
                let items: Vec<_> = slice.iter().map(task_to_json).collect();
                emit_json(&items);
            } else if slice.is_empty() {
                println!("暂无任务记录");
            } else {
                let mut table = new_table(&["ID", "类型", "状态", "进度", "书名/书源", "错误"]);
                for t in &slice {
                    let target = t
                        .book_id
                        .as_deref()
                        .or(t.source_id.as_deref())
                        .unwrap_or("-");
                    table.add_row([
                        t.id.clone(),
                        t.task_type.as_str().to_string(),
                        t.status.as_str().to_string(),
                        format!("{}/{} (失败 {})", t.completed, t.total, t.failed),
                        truncate(target, 22),
                        truncate(t.error_message.as_deref().unwrap_or("-"), 28),
                    ]);
                }
                println!("{table}");
            }
            Ok(())
        }
        TaskCommand::Show { task_id, json } => {
            let app = open_app(verbose, json).await?;
            let task = app
                .task_manager
                .get(&task_id)
                .await
                .map_err(|e| fail_err(&e, json))?;
            let items = app
                .tasks
                .list_items(&task.id)
                .await
                .map_err(|e| fail_err(&e, json))?;
            app.aclose().await;
            if json {
                let mut obj = task_to_json(&task);
                if let Some(m) = obj.as_object_mut() {
                    m.insert(
                        "items".to_string(),
                        serde_json::to_value(&items).unwrap_or(Value::Array(vec![])),
                    );
                }
                emit_json(&obj);
            } else {
                println!("ID:       {}", task.id);
                println!("类型:     {}", task.task_type.as_str());
                println!("状态:     {}", task.status.as_str());
                println!(
                    "进度:     {}/{} (失败 {})",
                    task.completed, task.total, task.failed
                );
                if let Some(ref b) = task.book_id {
                    println!("书籍 ID:  {b}");
                }
                if let Some(ref s) = task.source_id {
                    println!("书源 ID:  {s}");
                }
                if let Some(ref msg) = task.error_message {
                    println!("错误:     {msg}");
                }
                println!("子项数量: {}", items.len());
            }
            Ok(())
        }
        TaskCommand::Pause { task_id, json } => post_action(&task_id, "pause", json).await,
        TaskCommand::Resume { task_id, json } => post_action(&task_id, "resume", json).await,
        TaskCommand::Cancel { task_id, json } => post_action(&task_id, "cancel", json).await,
        TaskCommand::Retry { task_id, json } => post_action(&task_id, "retry", json).await,
        TaskCommand::Watch { task_id, json } => {
            let client = LocalApiClient::from_config(json)?;
            let target = task_id.clone();
            client
                .stream_task_events(task_id.as_deref(), json, move |ev| {
                    if json {
                        println!("{}", serde_json::to_string(ev).unwrap_or_default());
                    } else {
                        let tid = ev["task_id"].as_str().unwrap_or("-");
                        let st = ev["status"].as_str().unwrap_or("-");
                        let done = ev["completed"].as_i64().unwrap_or(0);
                        let total = ev["total"].as_i64().unwrap_or(0);
                        let failed = ev["failed"].as_i64().unwrap_or(0);
                        println!("[{tid}] {st} {done}/{total} (failed={failed})");
                    }
                    if let Some(ref wanted) = target
                        && ev["task_id"].as_str() == Some(wanted.as_str())
                        && matches!(
                            ev["status"].as_str(),
                            Some("success" | "failed" | "cancelled")
                        )
                    {
                        return true;
                    }
                    false
                })
                .await
        }
    }
}
