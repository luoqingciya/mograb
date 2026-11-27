// SPDX-License-Identifier: GPL-3.0-only
//! CLI 公共输出、退出码与 Application 初始化辅助。

use comfy_table::presets::UTF8_FULL_CONDENSED;
use comfy_table::{ContentArrangement, Table};
use mograb_core::app::Application;
use mograb_core::errors::MoGrabError;
use serde::Serialize;
use serde_json::{Map, Value, json};

pub const EXIT_OK: i32 = 0;
pub const EXIT_ERROR: i32 = 1;
pub const EXIT_USAGE: i32 = 2;
pub const EXIT_NOT_FOUND: i32 = 3;
pub const EXIT_VALIDATION: i32 = 4;
pub const EXIT_NETWORK: i32 = 5;
pub const EXIT_INTERRUPTED: i32 = 130;

/// 命令执行失败并已格式化输出后的退出码封装。
#[derive(Debug, Clone, Copy)]
pub struct CliExit(pub i32);

pub fn exit_code_for(err: &MoGrabError) -> i32 {
    match err {
        MoGrabError::EntityNotFound { .. }
        | MoGrabError::SourceNotFound { .. }
        | MoGrabError::TaskNotFound { .. } => EXIT_NOT_FOUND,
        MoGrabError::SourceSchema { .. } | MoGrabError::ContentValidation { .. } => EXIT_VALIDATION,
        MoGrabError::TaskParameter { .. } => EXIT_USAGE,
        MoGrabError::Network { .. }
        | MoGrabError::Timeout { .. }
        | MoGrabError::RateLimited { .. }
        | MoGrabError::HttpStatus { .. } => EXIT_NETWORK,
        _ => EXIT_ERROR,
    }
}

pub fn emit_json<T: Serialize + ?Sized>(data: &T) {
    match serde_json::to_string_pretty(data) {
        Ok(s) => println!("{s}"),
        Err(e) => eprintln!("JSON 序列化失败: {e}"),
    }
}

pub fn fail_err(err: &MoGrabError, json_mode: bool) -> CliExit {
    let code = err.code();
    let message = err.message();
    let details = err.details().clone();
    let exit_code = exit_code_for(err);
    fail_raw(code, message, details, exit_code, json_mode)
}

pub fn fail_msg(
    code: &str,
    message: &str,
    details: Map<String, Value>,
    exit_code: i32,
    json_mode: bool,
) -> CliExit {
    fail_raw(code, message, Value::Object(details), exit_code, json_mode)
}

fn fail_raw(code: &str, message: &str, details: Value, exit_code: i32, json_mode: bool) -> CliExit {
    if json_mode {
        let body = json!({
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        });
        eprintln!(
            "{}",
            serde_json::to_string_pretty(&body).unwrap_or_else(|_| body.to_string())
        );
    } else {
        eprintln!("错误 [{code}] {message}");
        let non_empty = details.as_object().is_some_and(|m| !m.is_empty());
        if non_empty && let Ok(pretty) = serde_json::to_string(&details) {
            eprintln!("  详情: {pretty}");
        }
    }
    CliExit(exit_code)
}

pub async fn open_app(verbose: bool, json_mode: bool) -> Result<Application, CliExit> {
    let level = if verbose { "DEBUG" } else { "WARNING" };
    Application::create(None, None, Some(level), verbose, None)
        .await
        .map_err(|e| fail_err(&e, json_mode))
}

pub fn new_table(headers: &[&str]) -> Table {
    let mut table = Table::new();
    table.load_style(UTF8_FULL_CONDENSED);
    table.set_content_arrangement(ContentArrangement::Dynamic);
    table.set_header(headers);
    table
}

pub fn truncate(s: &str, max_chars: usize) -> String {
    let count = s.chars().count();
    if count <= max_chars {
        return s.to_string();
    }
    if max_chars <= 1 {
        return "…".to_string();
    }
    let prefix: String = s.chars().take(max_chars - 1).collect();
    format!("{prefix}…")
}
