// SPDX-License-Identifier: GPL-3.0-only
//! `mog cache` —— HTTP 缓存统计与清理。

use crate::common::{CliExit, emit_json, fail_err, open_app};
use clap::{Args, Subcommand};
use mograb_core::network::HttpCache;
use serde_json::json;

#[derive(Debug, Args)]
pub struct CacheArgs {
    #[command(subcommand)]
    pub command: CacheCommand,
}

#[derive(Debug, Subcommand)]
pub enum CacheCommand {
    /// 查看缓存统计
    Stats {
        /// 顺便清理已过期缓存条目
        #[arg(long)]
        purge: bool,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 清空全部缓存
    Clear {
        /// 跳过确认提示
        #[arg(short = 'y', long)]
        yes: bool,
    },
    /// 清理指定书源的缓存
    ClearSource {
        /// 书源 ID
        source_id: String,
    },
}

pub async fn run(args: CacheArgs, verbose: bool) -> Result<(), CliExit> {
    match args.command {
        CacheCommand::Stats { purge, json } => {
            let app = open_app(verbose, json).await?;
            let purged = if purge {
                app.cache
                    .purge_expired()
                    .await
                    .map_err(|e| fail_err(&e, json))?
            } else {
                0
            };
            let stats = app.cache.stats().await.map_err(|e| fail_err(&e, json))?;
            app.aclose().await;
            if json {
                emit_json(&json!({
                    "entries": stats.entries,
                    "size_bytes": stats.size_bytes,
                    "max_size_bytes": stats.max_size_bytes,
                    "purged": purged,
                }));
            } else {
                let mb = stats.size_bytes as f64 / (1024.0 * 1024.0);
                let max_mb = stats.max_size_bytes as f64 / (1024.0 * 1024.0);
                println!(
                    "缓存条目: {} 条，占用 {:.2} MB / {:.0} MB",
                    stats.entries, mb, max_mb
                );
                if purge {
                    println!("已清理过期条目: {purged} 条");
                }
            }
            Ok(())
        }
        CacheCommand::Clear { yes } => {
            if !yes {
                eprint!("确认清空全部 HTTP 缓存？[y/N]: ");
                let mut line = String::new();
                if std::io::stdin().read_line(&mut line).is_err()
                    || !matches!(line.trim().to_ascii_lowercase().as_str(), "y" | "yes")
                {
                    println!("已取消");
                    return Ok(());
                }
            }
            let app = open_app(verbose, false).await?;
            let deleted = app.cache.clear().await.map_err(|e| fail_err(&e, false))?;
            app.aclose().await;
            println!("已清空缓存（移除 {deleted} 条）");
            Ok(())
        }
        CacheCommand::ClearSource { source_id } => {
            let app = open_app(verbose, false).await?;
            let deleted = app
                .cache
                .invalidate_source(&source_id)
                .await
                .map_err(|e| fail_err(&e, false))?;
            app.aclose().await;
            println!("已清理书源 {source_id} 的缓存（移除 {deleted} 条）");
            Ok(())
        }
    }
}
