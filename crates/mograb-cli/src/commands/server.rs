// SPDX-License-Identifier: GPL-3.0-only
//! `mog server` —— 启动/停止/查询本地 REST API 服务及令牌。

use crate::api_client::LocalApiClient;
use crate::common::{CliExit, EXIT_ERROR, emit_json, fail_err, fail_msg};
use clap::{Args, Subcommand};
use mograb_core::config::{ensure_token, get_paths, load_settings};
use serde_json::{Map, json};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::Duration;

#[derive(Debug, Args)]
pub struct ServerArgs {
    #[command(subcommand)]
    pub command: ServerCommand,
}

#[derive(Debug, Subcommand)]
pub enum ServerCommand {
    /// 启动本地 API 服务
    Start {
        /// 监听主机（默认读取 config.toml）
        #[arg(long)]
        host: Option<String>,
        /// 监听端口（默认读取 config.toml）
        #[arg(short = 'p', long)]
        port: Option<u16>,
        /// 后台守护启动
        #[arg(short = 'b', long)]
        background: bool,
    },
    /// 检查本地 API 服务状态
    Status {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 停止后台启动的 API 服务
    Stop,
    /// 查看（若不存在则生成）API Bearer 令牌
    Token {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
}

fn pid_file_path() -> PathBuf {
    get_paths(None).root.join("server.pid")
}

fn find_api_binary() -> Option<PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let dir = exe.parent()?;
    let bin_name = if cfg!(windows) {
        "mograb-api.exe"
    } else {
        "mograb-api"
    };
    let candidate = dir.join(bin_name);
    if candidate.is_file() {
        Some(candidate)
    } else {
        None
    }
}

pub async fn run(args: ServerArgs) -> Result<(), CliExit> {
    match args.command {
        ServerCommand::Start {
            host,
            port,
            background,
        } => {
            if !background {
                return mograb_api::serve(host, port)
                    .await
                    .map_err(|e| fail_err(&e, false));
            }

            let paths = get_paths(None);
            paths.ensure().map_err(|e| {
                fail_msg(
                    "SERVER_START_ERROR",
                    &format!("创建数据目录失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;

            let mut cmd = if let Some(api_bin) = find_api_binary() {
                Command::new(api_bin)
            } else {
                let exe = std::env::current_exe().map_err(|e| {
                    fail_msg(
                        "SERVER_START_ERROR",
                        &format!("定位可执行文件失败: {e}"),
                        Map::new(),
                        EXIT_ERROR,
                        false,
                    )
                })?;
                let mut c = Command::new(exe);
                c.args(["server", "start"]);
                if let Some(ref h) = host {
                    c.args(["--host", h]);
                }
                if let Some(p) = port {
                    c.args(["--port", &p.to_string()]);
                }
                c
            };

            if let Some(ref h) = host {
                cmd.env("MOGRAB_SERVER__HOST", h);
            }
            if let Some(p) = port {
                cmd.env("MOGRAB_SERVER__PORT", p.to_string());
            }
            cmd.stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());

            let child = cmd.spawn().map_err(|e| {
                fail_msg(
                    "SERVER_START_ERROR",
                    &format!("后台启动服务失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;
            let pid = child.id();
            let _ = fs::write(pid_file_path(), pid.to_string());

            let settings = load_settings(Some(&paths.config_file)).unwrap_or_default();
            let check_host = host.unwrap_or_else(|| match settings.server.host.as_str() {
                "0.0.0.0" => "127.0.0.1".to_string(),
                other => other.to_string(),
            });
            let check_port = port.unwrap_or(settings.server.port);
            let health_url = format!("http://{check_host}:{check_port}/health");
            let client = reqwest::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(1))
                .build()
                .ok();
            let mut ready = false;
            if let Some(c) = client {
                for _ in 0..25 {
                    tokio::time::sleep(Duration::from_millis(200)).await;
                    if let Ok(resp) = c.get(&health_url).send().await
                        && resp.status().is_success()
                    {
                        ready = true;
                        break;
                    }
                }
            }

            if ready {
                println!("本地 API 服务已在后台启动 (PID {pid}): http://{check_host}:{check_port}");
            } else {
                println!(
                    "已启动后台进程 (PID {pid})，如未就绪请检查日志: {}",
                    paths.logs_dir.join("mograb.log").display()
                );
            }
            Ok(())
        }
        ServerCommand::Status { json } => {
            let client = LocalApiClient::from_config(json)?;
            if let Some(health) = client.health().await {
                if json {
                    emit_json(&json!({
                        "running": true,
                        "url": client.base_url,
                        "health": health,
                    }));
                } else {
                    println!(
                        "服务运行中: {} (version={}, uptime={}s)",
                        client.base_url,
                        health["version"].as_str().unwrap_or("-"),
                        health["uptime_seconds"].as_f64().unwrap_or(0.0) as u64
                    );
                }
            } else if json {
                emit_json(&json!({
                    "running": false,
                    "url": client.base_url,
                }));
            } else {
                println!("服务未运行: {}", client.base_url);
            }
            Ok(())
        }
        ServerCommand::Stop => {
            let pid_path = pid_file_path();
            if !pid_path.is_file() {
                println!("未发现后台服务 PID 文件 ({})", pid_path.display());
                return Ok(());
            }
            let pid_str = fs::read_to_string(&pid_path).unwrap_or_default();
            let pid = pid_str.trim();
            if pid.is_empty() {
                let _ = fs::remove_file(&pid_path);
                println!("PID 文件为空，已清理");
                return Ok(());
            }
            #[cfg(unix)]
            let status = Command::new("kill").args(["-TERM", pid]).status();
            #[cfg(windows)]
            let status = Command::new("taskkill").args(["/PID", pid, "/F"]).status();

            let _ = fs::remove_file(&pid_path);
            match status {
                Ok(s) if s.success() => println!("已停止服务 (PID {pid})"),
                _ => println!("已发送停止信号并清理 PID 文件 (PID {pid})"),
            }
            Ok(())
        }
        ServerCommand::Token { json } => {
            let paths = get_paths(None);
            let token = ensure_token(Some(&paths)).map_err(|e| {
                fail_msg(
                    "TOKEN_ERROR",
                    &format!("读取或生成令牌失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    json,
                )
            })?;
            if json {
                emit_json(&json!({
                    "token": token,
                    "token_file": paths.token_file.display().to_string(),
                }));
            } else {
                println!("{token}");
            }
            Ok(())
        }
    }
}
