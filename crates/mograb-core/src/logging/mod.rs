// SPDX-License-Identifier: GPL-3.0-only
//! 结构化日志与请求头脱敏。

use std::collections::BTreeMap;
use std::fs::{self, OpenOptions};
use std::path::Path;
use std::sync::OnceLock;
use tracing_subscriber::EnvFilter;
use tracing_subscriber::fmt::writer::MakeWriterExt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;

pub const SENSITIVE_KEYS: &[&str] = &[
    "cookie",
    "set-cookie",
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api_key",
    "apikey",
    "token",
    "password",
    "secret",
];

const REDACTED: &str = "***";

static LOG_INIT: OnceLock<()> = OnceLock::new();

pub fn redact_headers(headers: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    headers
        .iter()
        .map(|(k, v)| {
            let lowered = k.to_lowercase();
            let val = if SENSITIVE_KEYS.contains(&lowered.as_str()) {
                REDACTED.to_string()
            } else {
                v.clone()
            };
            (k.clone(), val)
        })
        .collect()
}

pub fn configure_logging(level: &str, log_dir: Option<&Path>, json_output: bool, console: bool) {
    LOG_INIT.get_or_init(|| {
        let filter = EnvFilter::try_new(level).unwrap_or_else(|_| EnvFilter::new("info"));

        let file_writer = log_dir.and_then(|dir| {
            fs::create_dir_all(dir).ok()?;
            let app_log = OpenOptions::new()
                .create(true)
                .append(true)
                .open(dir.join("app.log"))
                .ok()?;
            Some(std::sync::Mutex::new(app_log))
        });

        let registry = tracing_subscriber::registry().with(filter);

        match (console, file_writer, json_output) {
            (true, Some(file), true) => {
                let writer = std::io::stderr.and(file);
                let _ = registry
                    .with(tracing_subscriber::fmt::layer().json().with_writer(writer))
                    .try_init();
            }
            (true, Some(file), false) => {
                let writer = std::io::stderr.and(file);
                let _ = registry
                    .with(tracing_subscriber::fmt::layer().with_writer(writer))
                    .try_init();
            }
            (true, None, true) => {
                let _ = registry
                    .with(
                        tracing_subscriber::fmt::layer()
                            .json()
                            .with_writer(std::io::stderr),
                    )
                    .try_init();
            }
            (true, None, false) => {
                let _ = registry
                    .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
                    .try_init();
            }
            (false, Some(file), true) => {
                let _ = registry
                    .with(tracing_subscriber::fmt::layer().json().with_writer(file))
                    .try_init();
            }
            (false, Some(file), false) => {
                let _ = registry
                    .with(tracing_subscriber::fmt::layer().with_writer(file))
                    .try_init();
            }
            (false, None, _) => {}
        }
    });
}
