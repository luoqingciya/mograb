// SPDX-License-Identifier: GPL-3.0-only
//! `mog logs` —— 查看应用、任务或书源日志。

use crate::common::{CliExit, EXIT_ERROR, EXIT_INTERRUPTED, EXIT_USAGE, fail_msg};
use clap::Args;
use mograb_core::config::get_paths;
use serde_json::Map;
use std::fs::File;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom};
use std::time::Duration;

#[derive(Debug, Args)]
pub struct LogsArgs {
    /// 日志目标（app / task / source）
    #[arg(short = 't', long, default_value = "app")]
    pub target: String,
    /// 持续跟踪新日志输出
    #[arg(short = 'f', long)]
    pub follow: bool,
    /// 显示最后多少行
    #[arg(short = 'n', long, default_value_t = 50)]
    pub lines: usize,
}

pub async fn run(args: LogsArgs) -> Result<(), CliExit> {
    let filename = match args.target.as_str() {
        "app" => "mograb.log",
        "task" => "task.log",
        "source" => "source.log",
        other => {
            return Err(fail_msg(
                "USAGE_ERROR",
                &format!("未知日志目标: {other}（可选 app / task / source）"),
                Map::new(),
                EXIT_USAGE,
                false,
            ));
        }
    };

    let paths = get_paths(None);
    let log_path = paths.logs_dir.join(filename);
    if !log_path.is_file() {
        println!("暂无日志文件: {}", log_path.display());
        return Ok(());
    }

    let file = File::open(&log_path).map_err(|e| {
        fail_msg(
            "LOG_READ_ERROR",
            &format!("打开日志失败: {e}"),
            Map::new(),
            EXIT_ERROR,
            false,
        )
    })?;
    let mut reader = BufReader::new(file);
    let mut all_lines = Vec::new();
    let mut line = String::new();
    while reader.read_line(&mut line).unwrap_or(0) > 0 {
        all_lines.push(line.clone());
        line.clear();
    }
    let start = all_lines.len().saturating_sub(args.lines);
    for l in &all_lines[start..] {
        print!("{l}");
    }

    if !args.follow {
        return Ok(());
    }

    let mut pos = reader.stream_position().unwrap_or(0);
    loop {
        tokio::select! {
            _ = tokio::signal::ctrl_c() => {
                return Err(CliExit(EXIT_INTERRUPTED));
            }
            _ = tokio::time::sleep(Duration::from_millis(250)) => {
                if let Ok(mut f) = File::open(&log_path) {
                    if let Ok(meta) = f.metadata()
                        && meta.len() < pos
                    {
                        pos = 0;
                    }
                    if f.seek(SeekFrom::Start(pos)).is_ok() {
                        let mut buf = String::new();
                        if f.read_to_string(&mut buf).is_ok() && !buf.is_empty() {
                            print!("{buf}");
                            pos += buf.len() as u64;
                        }
                    }
                }
            }
        }
    }
}
