// SPDX-License-Identifier: GPL-3.0-only
//! 配置系统（TOML + 环境变量 `MOGRAB_<SECTION>__<FIELD>` 覆盖）。

use super::paths::{Paths, get_paths};
use crate::errors::{MoGrabError, MoGrabResult};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

static DC_KEY_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-z][a-z0-9-]*$").expect("valid DC_KEY_RE"));

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct ServerSettings {
    pub host: String,
    pub port: u16,
    pub health_timeout_ms: u64,
    pub auth: bool,
}

impl Default for ServerSettings {
    fn default() -> Self {
        Self {
            host: "127.0.0.1".to_string(),
            port: 48721,
            health_timeout_ms: 5000,
            auth: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DownloadSettings {
    pub concurrency: usize,
    pub per_source_concurrency: usize,
    pub retry: usize,
    pub request_interval_ms: u64,
    pub timeout_ms: u64,
    pub proxy: Option<String>,
}

impl Default for DownloadSettings {
    fn default() -> Self {
        Self {
            concurrency: 4,
            per_source_concurrency: 2,
            retry: 3,
            request_interval_ms: 500,
            timeout_ms: 15_000,
            proxy: None,
        }
    }
}

pub fn parse_size(text: &str) -> MoGrabResult<u64> {
    let raw = text.trim().to_lowercase();
    if raw.is_empty() {
        return Err(MoGrabError::config("容量配置不能为空"));
    }

    const UNITS: &[(&str, u64)] = &[
        ("tb", 1024u64.pow(4)),
        ("gb", 1024u64.pow(3)),
        ("mb", 1024u64.pow(2)),
        ("kb", 1024),
        ("b", 1),
    ];

    let (num_str, factor) = match UNITS.iter().find(|(u, _)| raw.ends_with(u)) {
        Some((u, factor)) => (raw[..raw.len() - u.len()].trim(), *factor),
        None => (raw.as_str(), 1u64),
    };

    if num_str.is_empty() || !num_str.chars().all(|c| c.is_ascii_digit()) {
        return Err(MoGrabError::config_with(
            format!("无法解析容量: {text:?}"),
            json!({"value": text, "expected": "如 5GB、512MB"}),
        ));
    }

    let n: u64 = num_str.parse().map_err(|_| {
        MoGrabError::config_with(
            format!("无法解析容量: {text:?}"),
            json!({"value": text, "expected": "如 5GB、512MB"}),
        )
    })?;
    Ok(n.saturating_mul(factor))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct CacheSettings {
    pub enabled: bool,
    pub max_size: String,
    pub ttl_seconds: u64,
    pub content_ttl_seconds: u64,
}

impl Default for CacheSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            max_size: "5GB".to_string(),
            ttl_seconds: 1800,
            content_ttl_seconds: 7 * 24 * 3600,
        }
    }
}

impl CacheSettings {
    pub fn max_size_bytes(&self) -> MoGrabResult<u64> {
        parse_size(&self.max_size)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct OutputSettings {
    pub directory: String,
    pub format: String,
    pub template: String,
    pub chapter_template: String,
    pub metadata: BTreeMap<String, String>,
}

impl Default for OutputSettings {
    fn default() -> Self {
        Self {
            directory: "exports".to_string(),
            format: "epub".to_string(),
            template: "{{author}} - {{title}}".to_string(),
            chapter_template: "{{index}}. {{title}}".to_string(),
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct LoggingSettings {
    pub level: String,
    pub json_output: bool,
    pub max_bytes: usize,
    pub backup_count: usize,
}

impl Default for LoggingSettings {
    fn default() -> Self {
        Self {
            level: "INFO".to_string(),
            json_output: false,
            max_bytes: 10 * 1024 * 1024,
            backup_count: 5,
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct AppSettings {
    pub server: ServerSettings,
    pub download: DownloadSettings,
    pub cache: CacheSettings,
    pub output: OutputSettings,
    pub logging: LoggingSettings,
}

impl AppSettings {
    pub fn validate(&self) -> MoGrabResult<()> {
        if self.server.port < 1024 {
            return Err(MoGrabError::config(format!(
                "server.port 必须在 1024..=65535 之间: {}",
                self.server.port
            )));
        }
        if self.server.health_timeout_ms < 100 {
            return Err(MoGrabError::config(format!(
                "server.health_timeout_ms 必须 >= 100: {}",
                self.server.health_timeout_ms
            )));
        }
        if !(1..=64).contains(&self.download.concurrency) {
            return Err(MoGrabError::config(format!(
                "download.concurrency 超出范围 [1, 64]: {}",
                self.download.concurrency
            )));
        }
        if !(1..=32).contains(&self.download.per_source_concurrency) {
            return Err(MoGrabError::config(format!(
                "download.per_source_concurrency 超出范围 [1, 32]: {}",
                self.download.per_source_concurrency
            )));
        }
        if self.download.retry > 10 {
            return Err(MoGrabError::config(format!(
                "download.retry 超出范围 [0, 10]: {}",
                self.download.retry
            )));
        }
        if self.download.request_interval_ms > 60_000 {
            return Err(MoGrabError::config(format!(
                "download.request_interval_ms 超出范围 [0, 60000]: {}",
                self.download.request_interval_ms
            )));
        }
        if !(100..=120_000).contains(&self.download.timeout_ms) {
            return Err(MoGrabError::config(format!(
                "download.timeout_ms 超出范围 [100, 120000]: {}",
                self.download.timeout_ms
            )));
        }
        let _ = self.cache.max_size_bytes()?;

        for key in self.output.metadata.keys() {
            if key == "identifier" {
                return Err(MoGrabError::config(
                    "元数据键 identifier 不可配置 —— 它由书籍 ID 生成，改了会让阅读器把同一本书当成两本",
                ));
            }
            if !DC_KEY_RE.is_match(key) {
                return Err(MoGrabError::config(format!(
                    "元数据键 {key:?} 不合法：只能用 Dublin Core 元素名（小写字母开头，可含数字和连字符），如 publisher、subject"
                )));
            }
        }
        Ok(())
    }

    pub fn apply_env_overrides(&mut self) -> MoGrabResult<()> {
        for (k, v) in env::vars() {
            let upper = k.to_uppercase();
            let Some(rest) = upper.strip_prefix("MOGRAB_") else {
                continue;
            };
            let Some((section, field)) = rest.split_once("__") else {
                continue;
            };
            match (section, field) {
                ("SERVER", "HOST") => self.server.host = v,
                ("SERVER", "PORT") => {
                    self.server.port = parse_env_int("MOGRAB_SERVER__PORT", &v)?;
                }
                ("SERVER", "HEALTH_TIMEOUT_MS") => {
                    self.server.health_timeout_ms =
                        parse_env_int("MOGRAB_SERVER__HEALTH_TIMEOUT_MS", &v)?;
                }
                ("SERVER", "AUTH") => {
                    self.server.auth = parse_env_bool("MOGRAB_SERVER__AUTH", &v)?;
                }
                ("DOWNLOAD", "CONCURRENCY") => {
                    self.download.concurrency = parse_env_int("MOGRAB_DOWNLOAD__CONCURRENCY", &v)?;
                }
                ("DOWNLOAD", "PER_SOURCE_CONCURRENCY") => {
                    self.download.per_source_concurrency =
                        parse_env_int("MOGRAB_DOWNLOAD__PER_SOURCE_CONCURRENCY", &v)?;
                }
                ("DOWNLOAD", "RETRY") => {
                    self.download.retry = parse_env_int("MOGRAB_DOWNLOAD__RETRY", &v)?;
                }
                ("DOWNLOAD", "REQUEST_INTERVAL_MS") => {
                    self.download.request_interval_ms =
                        parse_env_int("MOGRAB_DOWNLOAD__REQUEST_INTERVAL_MS", &v)?;
                }
                ("DOWNLOAD", "TIMEOUT_MS") => {
                    self.download.timeout_ms = parse_env_int("MOGRAB_DOWNLOAD__TIMEOUT_MS", &v)?;
                }
                ("DOWNLOAD", "PROXY") => {
                    self.download.proxy = if v.trim().is_empty() { None } else { Some(v) };
                }
                ("CACHE", "ENABLED") => {
                    self.cache.enabled = parse_env_bool("MOGRAB_CACHE__ENABLED", &v)?;
                }
                ("CACHE", "MAX_SIZE") => self.cache.max_size = v,
                ("CACHE", "TTL_SECONDS") => {
                    self.cache.ttl_seconds = parse_env_int("MOGRAB_CACHE__TTL_SECONDS", &v)?;
                }
                ("CACHE", "CONTENT_TTL_SECONDS") => {
                    self.cache.content_ttl_seconds =
                        parse_env_int("MOGRAB_CACHE__CONTENT_TTL_SECONDS", &v)?;
                }
                ("OUTPUT", "DIRECTORY") => self.output.directory = v,
                ("OUTPUT", "FORMAT") => self.output.format = v,
                ("OUTPUT", "TEMPLATE") => self.output.template = v,
                ("OUTPUT", "CHAPTER_TEMPLATE") => self.output.chapter_template = v,
                ("LOGGING", "LEVEL") => self.logging.level = v,
                ("LOGGING", "JSON_OUTPUT") => {
                    self.logging.json_output = parse_env_bool("MOGRAB_LOGGING__JSON_OUTPUT", &v)?;
                }
                ("LOGGING", "MAX_BYTES") => {
                    self.logging.max_bytes = parse_env_int("MOGRAB_LOGGING__MAX_BYTES", &v)?;
                }
                ("LOGGING", "BACKUP_COUNT") => {
                    self.logging.backup_count = parse_env_int("MOGRAB_LOGGING__BACKUP_COUNT", &v)?;
                }
                _ => {}
            }
        }
        Ok(())
    }
}

fn parse_env_int<T: std::str::FromStr>(name: &str, v: &str) -> MoGrabResult<T> {
    v.trim()
        .parse::<T>()
        .map_err(|_| MoGrabError::config(format!("环境变量 {name} 不是合法整数: {v:?}")))
}

fn parse_env_bool(name: &str, v: &str) -> MoGrabResult<bool> {
    match v.trim().to_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => Err(MoGrabError::config(format!(
            "环境变量 {name} 不是合法布尔值: {v:?}"
        ))),
    }
}

pub fn load_settings(config_path: Option<&Path>) -> MoGrabResult<AppSettings> {
    let paths: Paths = get_paths(None);
    let path = config_path.unwrap_or(&paths.config_file);

    let mut settings = if path.is_file() {
        let text = fs::read_to_string(path).map_err(|e| {
            MoGrabError::config_with(
                format!("读取配置文件失败: {}", path.display()),
                json!({"path": path.display().to_string(), "reason": e.to_string()}),
            )
        })?;
        toml::from_str::<AppSettings>(&text).map_err(|e| {
            MoGrabError::config_with(
                format!("配置文件解析失败: {}", path.display()),
                json!({"path": path.display().to_string(), "reason": e.to_string()}),
            )
        })?
    } else {
        AppSettings::default()
    };

    settings.apply_env_overrides()?;
    settings.validate()?;
    Ok(settings)
}

pub fn write_default_config(path: &Path, overwrite: bool) -> MoGrabResult<PathBuf> {
    if path.exists() && !overwrite {
        return Err(MoGrabError::config_with(
            format!("配置文件已存在: {}", path.display()),
            json!({"path": path.display().to_string()}),
        ));
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| MoGrabError::config(e.to_string()))?;
    }
    fs::write(path, DEFAULT_CONFIG_TOML).map_err(|e| MoGrabError::config(e.to_string()))?;
    Ok(path.to_path_buf())
}

pub const DEFAULT_CONFIG_TOML: &str = r#"# MoGrab 配置文件
# 优先级：CLI 参数 > Task 参数 > Source 配置 > 本文件 > 代码默认值

[server]
host = "127.0.0.1"
port = 48721
# 要求 Authorization: Bearer <token>。令牌在 data/token 里，
# 由程序自动生成，不需要在这里填。
auth = true

[download]
concurrency = 4
per_source_concurrency = 2
retry = 3
request_interval_ms = 500
timeout_ms = 15000

# 代理。留空则读环境变量（HTTP_PROXY / HTTPS_PROXY / ALL_PROXY）。
# 站点在墙外、或本机走了 TUN 模式代理时，这条通常不用填。
# proxy = "http://127.0.0.1:7890"

[cache]
enabled = true
max_size = "5GB"
ttl_seconds = 1800

[output]
directory = "exports"
format = "epub"
template = "{{author}} - {{title}}"
chapter_template = "{{index}}. {{title}}"

# EPUB 元数据补充。键是 Dublin Core 元素名，值支持 {{title}} {{author}} 等变量。
# 在这里写了就按你写的来（和书籍自带数据冲突时以配置为准）。
[output.metadata]
# publisher = "个人整理"
# subject = "{{author}} 作品"

[logging]
level = "INFO"
json_output = false
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_size() {
        assert_eq!(parse_size("5GB").unwrap(), 5 * 1024 * 1024 * 1024);
        assert_eq!(parse_size("512mb").unwrap(), 512 * 1024 * 1024);
        assert_eq!(parse_size("1024").unwrap(), 1024);
        assert!(parse_size("5.5GB").is_err());
        assert!(parse_size("").is_err());
    }

    #[test]
    fn test_default_config_parses_cleanly() {
        let s: AppSettings = toml::from_str(DEFAULT_CONFIG_TOML).unwrap();
        s.validate().unwrap();
        assert_eq!(s.server.port, 48721);
        assert_eq!(s.download.concurrency, 4);
    }

    #[test]
    fn test_metadata_key_validation() {
        let mut s = AppSettings::default();
        s.output.metadata.insert("identifier".into(), "x".into());
        assert!(s.validate().is_err());

        s.output.metadata.clear();
        s.output.metadata.insert("publisher".into(), "个人".into());
        assert!(s.validate().is_ok());

        s.output.metadata.insert("Bad Key".into(), "x".into());
        assert!(s.validate().is_err());
    }
}
