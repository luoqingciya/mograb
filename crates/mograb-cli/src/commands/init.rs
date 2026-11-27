// SPDX-License-Identifier: GPL-3.0-only
//! `mog init` —— 初始化数据目录、默认配置、数据库与认证令牌。

use crate::common::{CliExit, EXIT_ERROR, emit_json, fail_err, fail_msg, open_app};
use clap::Args;
use mograb_core::config::{ensure_token, get_paths, write_default_config};
use serde_json::{Map, json};

#[derive(Debug, Args)]
pub struct InitArgs {
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: InitArgs, verbose: bool) -> Result<(), CliExit> {
    let paths = get_paths(None);
    let mut created: Vec<String> = Vec::new();

    if !paths.root.exists() {
        created.push("data_dir".to_string());
    }
    let config_existed = paths.config_file.exists();
    let db_existed = paths.database.exists();
    let token_existed = paths.token_file.exists();

    paths.ensure().map_err(|e| {
        fail_msg(
            "INIT_ERROR",
            &format!("创建数据目录失败: {e}"),
            Map::new(),
            EXIT_ERROR,
            args.json,
        )
    })?;

    if !config_existed {
        write_default_config(&paths.config_file, false).map_err(|e| fail_err(&e, args.json))?;
        created.push("config".to_string());
    }

    let app = open_app(verbose, args.json).await?;
    app.aclose().await;
    if !db_existed && paths.database.exists() {
        created.push("database".to_string());
    }

    ensure_token(Some(&paths)).map_err(|e| {
        fail_msg(
            "INIT_ERROR",
            &format!("生成 API 令牌失败: {e}"),
            Map::new(),
            EXIT_ERROR,
            args.json,
        )
    })?;
    if !token_existed && paths.token_file.exists() {
        created.push("token".to_string());
    }

    if args.json {
        emit_json(&json!({
            "data_dir": paths.root.display().to_string(),
            "created": created,
            "config": paths.config_file.display().to_string(),
            "database": paths.database.display().to_string(),
            "directories": {
                "covers": paths.covers_dir.display().to_string(),
                "exports": paths.exports_dir.display().to_string(),
                "logs": paths.logs_dir.display().to_string(),
                "sources": paths.sources_dir.display().to_string(),
            }
        }));
    } else {
        println!("MoGrab 数据目录已就绪: {}", paths.root.display());
        println!("  配置文件: {}", paths.config_file.display());
        println!("  数据库:   {}", paths.database.display());
        println!("  令牌文件: {}", paths.token_file.display());
        if !created.is_empty() {
            println!("  本次新建: {}", created.join(", "));
        }
    }
    Ok(())
}
