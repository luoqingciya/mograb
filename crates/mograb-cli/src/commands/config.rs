// SPDX-License-Identifier: GPL-3.0-only
//! `mog config` —— 配置与路径管理。

use crate::common::{CliExit, EXIT_ERROR, emit_json, fail_err, fail_msg};
use clap::{Args, Subcommand};
use mograb_core::config::{get_paths, load_settings, runtime_dir, write_default_config};
use serde_json::{Map, json};

#[derive(Debug, Args)]
pub struct ConfigArgs {
    #[command(subcommand)]
    pub command: ConfigCommand,
}

#[derive(Debug, Subcommand)]
pub enum ConfigCommand {
    /// 生成默认 config.toml
    Init {
        /// 覆盖已存在的 config.toml
        #[arg(long)]
        force: bool,
    },
    /// 显示当前生效的各目录与文件路径
    Path {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 显示当前生效的配置内容
    Show {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
}

pub fn run(args: ConfigArgs) -> Result<(), CliExit> {
    match args.command {
        ConfigCommand::Init { force } => {
            let paths = get_paths(None);
            paths.ensure().map_err(|e| {
                fail_msg(
                    "CONFIG_ERROR",
                    &format!("创建目录失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;
            if paths.config_file.exists() && !force {
                println!(
                    "配置文件已存在: {}（使用 --force 覆盖）",
                    paths.config_file.display()
                );
                return Ok(());
            }
            let target =
                write_default_config(&paths.config_file, force).map_err(|e| fail_err(&e, false))?;
            println!("已写入默认配置: {}", target.display());
            Ok(())
        }
        ConfigCommand::Path { json } => {
            let paths = get_paths(None);
            let rt = runtime_dir();
            if json {
                emit_json(&json!({
                    "runtime": rt.display().to_string(),
                    "data": paths.root.display().to_string(),
                    "config": paths.config_file.display().to_string(),
                    "database": paths.database.display().to_string(),
                    "covers": paths.covers_dir.display().to_string(),
                    "exports": paths.exports_dir.display().to_string(),
                    "logs": paths.logs_dir.display().to_string(),
                    "sources": paths.sources_dir.display().to_string(),
                }));
            } else {
                println!("runtime:  {}", rt.display());
                println!("data:     {}", paths.root.display());
                println!("config:   {}", paths.config_file.display());
                println!("database: {}", paths.database.display());
                println!("covers:   {}", paths.covers_dir.display());
                println!("exports:  {}", paths.exports_dir.display());
                println!("logs:     {}", paths.logs_dir.display());
                println!("sources:  {}", paths.sources_dir.display());
            }
            Ok(())
        }
        ConfigCommand::Show { json } => {
            let paths = get_paths(None);
            let settings =
                load_settings(Some(&paths.config_file)).map_err(|e| fail_err(&e, json))?;
            let max_bytes = settings
                .cache
                .max_size_bytes()
                .map_err(|e| fail_err(&e, json))?;
            let mut val = serde_json::to_value(&settings).map_err(|e| {
                fail_msg(
                    "CONFIG_ERROR",
                    &format!("序列化配置失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    json,
                )
            })?;
            if let Some(cache_obj) = val.get_mut("cache").and_then(|v| v.as_object_mut()) {
                cache_obj.insert("max_size_bytes".to_string(), json!(max_bytes));
            }
            if json {
                emit_json(&val);
            } else {
                let toml_text =
                    toml::to_string_pretty(&settings).unwrap_or_else(|_| val.to_string());
                print!("{toml_text}");
            }
            Ok(())
        }
    }
}
