// SPDX-License-Identifier: GPL-3.0-only
//! MoGrab Desktop (Tauri v2) 宿主入口 —— 进程内拉起并管理 `mograb-api`。

use mograb_api::AppState;
use mograb_core::config::{AppSettings, ensure_token, get_paths, is_frozen, load_settings};
use mograb_core::network::HttpCache;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;
use tauri::window::Color;
use tauri::{RunEvent, WebviewUrl, WebviewWindowBuilder};
use tokio::net::TcpListener;
use tokio::sync::{Mutex, OnceCell, oneshot};
use tokio::task::JoinHandle;
use tracing::{info, warn};

const HOST: &str = "127.0.0.1";
const PORT: u16 = 48721;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendInfo {
    pub base_url: String,
    pub token: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CacheStatsDto {
    pub entries: i64,
    pub size_bytes: i64,
    pub max_size_bytes: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AppInfoDto {
    pub version: String,
    pub data_dir: String,
    pub config_file: String,
    pub database: String,
    pub covers_dir: String,
    pub exports_dir: String,
    pub logs_dir: String,
    pub sources_dir: String,
    pub in_process: bool,
    pub settings: AppSettings,
    pub cache_stats: Option<CacheStatsDto>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ClearCacheResult {
    pub removed: u64,
    pub stats: CacheStatsDto,
}

#[derive(Debug, Clone, Default, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SettingsPatch {
    pub concurrency: Option<usize>,
    pub per_source_concurrency: Option<usize>,
    pub request_interval_ms: Option<u64>,
    pub timeout_ms: Option<u64>,
    pub retry: Option<usize>,
    pub proxy: Option<String>,
    pub cache_enabled: Option<bool>,
    pub cache_max_size: Option<String>,
    pub output_format: Option<String>,
    pub output_template: Option<String>,
    pub logging_level: Option<String>,
}

struct BackendServerHandle {
    state: AppState,
    shutdown_tx: Option<oneshot::Sender<()>>,
    join: Option<JoinHandle<()>>,
}

struct AppRuntime {
    ready: OnceCell<Result<BackendInfo, String>>,
    server: Mutex<Option<BackendServerHandle>>,
}

impl AppRuntime {
    fn new() -> Self {
        Self {
            ready: OnceCell::new(),
            server: Mutex::new(None),
        }
    }
}

fn api_base_url() -> String {
    format!("http://{HOST}:{PORT}/api/v1")
}

fn health_url() -> String {
    format!("http://{HOST}:{PORT}/health")
}

fn find_repo_root(start: &Path) -> Option<PathBuf> {
    let mut cur = Some(start);
    while let Some(dir) = cur {
        if dir.join("Cargo.toml").is_file() && dir.join("crates").join("mograb-core").is_dir() {
            return Some(dir.to_path_buf());
        }
        cur = dir.parent();
    }
    None
}

fn resolve_data_dir() -> PathBuf {
    if let Ok(override_dir) = std::env::var("MOGRAB_HOME")
        && !override_dir.trim().is_empty()
    {
        return PathBuf::from(override_dir.trim());
    }

    if is_frozen() {
        #[cfg(target_os = "linux")]
        {
            if let Ok(xdg) = std::env::var("XDG_DATA_HOME")
                && !xdg.trim().is_empty()
            {
                return PathBuf::from(xdg.trim()).join("mograb");
            }
            if let Some(home) = std::env::var_os("HOME") {
                return PathBuf::from(home)
                    .join(".local")
                    .join("share")
                    .join("mograb");
            }
        }
        return mograb_core::config::paths::data_dir();
    }

    if let Ok(cwd) = std::env::current_dir()
        && let Some(repo) = find_repo_root(&cwd)
    {
        return repo.join("data");
    }
    if let Ok(exe) = std::env::current_exe()
        && let Some(repo) = find_repo_root(&exe)
    {
        return repo.join("data");
    }

    mograb_core::config::paths::data_dir()
}

fn is_allowed_nav(url: &tauri::Url) -> bool {
    match url.scheme() {
        "tauri" => url.host_str() == Some("localhost"),
        "http" => matches!(
            url.host_str(),
            Some("tauri.localhost" | "127.0.0.1" | "localhost")
        ),
        "https" => url.host_str() == Some("tauri.localhost"),
        "about" => url.as_str() == "about:blank",
        _ => false,
    }
}

async fn is_backend_healthy() -> bool {
    let Ok(client) = reqwest::Client::builder()
        .no_proxy()
        .timeout(Duration::from_secs(2))
        .build()
    else {
        return false;
    };
    client
        .get(health_url())
        .send()
        .await
        .is_ok_and(|r| r.status().is_success())
}

async fn ensure_backend(runtime: &Arc<AppRuntime>) -> Result<BackendInfo, String> {
    runtime
        .ready
        .get_or_init(|| async { start_or_attach_backend(runtime).await })
        .await
        .clone()
}

async fn start_or_attach_backend(runtime: &Arc<AppRuntime>) -> Result<BackendInfo, String> {
    let data_dir = resolve_data_dir();
    let paths = get_paths(Some(&data_dir));

    if is_backend_healthy().await {
        info!("已有 mograb-api 实例在运行，直接复用");
        let token =
            ensure_token(Some(&paths)).map_err(|e| format!("读取现有服务 API 令牌失败: {e}"))?;
        return Ok(BackendInfo {
            base_url: api_base_url(),
            token,
        });
    }

    let mut settings: AppSettings = load_settings(Some(&paths.config_file))
        .map_err(|e| format!("加载配置失败: {}", e.message()))?;
    settings.server.host = HOST.to_string();
    settings.server.port = PORT;

    let state = mograb_api::build_state(Some(settings), Some(paths), true)
        .await
        .map_err(|e| format!("初始化本地服务失败: {}", e.message()))?;

    let token = state.token.clone();
    let listen_addr = format!("{HOST}:{PORT}");
    let listener = TcpListener::bind(&listen_addr)
        .await
        .map_err(|e| format!("监听 {listen_addr} 失败: {e}"))?;

    let router = mograb_api::create_router(state.clone());
    let (tx, rx) = oneshot::channel::<()>();
    let state_for_close = state.clone();

    let join = tokio::spawn(async move {
        let serve_res = axum::serve(listener, router)
            .with_graceful_shutdown(async move {
                let _ = rx.await;
            })
            .await;
        if let Err(err) = serve_res {
            warn!("mograb-api 异常退出: {err}");
        }
        state_for_close.app.aclose().await;
    });

    *runtime.server.lock().await = Some(BackendServerHandle {
        state,
        shutdown_tx: Some(tx),
        join: Some(join),
    });

    Ok(BackendInfo {
        base_url: api_base_url(),
        token,
    })
}

fn apply_settings_patch(settings: &mut AppSettings, patch: SettingsPatch) -> Result<(), String> {
    if let Some(v) = patch.concurrency {
        settings.download.concurrency = v;
    }
    if let Some(v) = patch.per_source_concurrency {
        settings.download.per_source_concurrency = v;
    }
    if let Some(v) = patch.request_interval_ms {
        settings.download.request_interval_ms = v;
    }
    if let Some(v) = patch.timeout_ms {
        settings.download.timeout_ms = v;
    }
    if let Some(v) = patch.retry {
        settings.download.retry = v;
    }
    if let Some(v) = patch.proxy {
        let trimmed = v.trim();
        settings.download.proxy = if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        };
    }
    if let Some(v) = patch.cache_enabled {
        settings.cache.enabled = v;
    }
    if let Some(v) = patch.cache_max_size {
        settings.cache.max_size = v.trim().to_string();
    }
    if let Some(v) = patch.output_format {
        let fmt = v.trim().to_lowercase();
        if !matches!(fmt.as_str(), "epub" | "txt" | "markdown") {
            return Err(format!(
                "不支持的默认导出格式: {v}（可选 epub / txt / markdown）"
            ));
        }
        settings.output.format = fmt;
    }
    if let Some(v) = patch.output_template {
        let trimmed = v.trim();
        if trimmed.is_empty() {
            return Err("输出文件名模板不能为空".to_string());
        }
        settings.output.template = trimmed.to_string();
    }
    if let Some(v) = patch.logging_level {
        let upper = v.trim().to_uppercase();
        if !matches!(upper.as_str(), "DEBUG" | "INFO" | "WARNING" | "ERROR") {
            return Err(format!(
                "不支持的日志级别: {v}（可选 DEBUG / INFO / WARNING / ERROR）"
            ));
        }
        settings.logging.level = upper;
    }
    settings.validate().map_err(|e| e.message().to_string())
}

#[tauri::command]
async fn backend_wait(runtime: tauri::State<'_, Arc<AppRuntime>>) -> Result<BackendInfo, String> {
    ensure_backend(runtime.inner()).await
}

#[tauri::command]
async fn get_app_info(runtime: tauri::State<'_, Arc<AppRuntime>>) -> Result<AppInfoDto, String> {
    let data_dir = resolve_data_dir();
    let paths = get_paths(Some(&data_dir));
    let settings = load_settings(Some(&paths.config_file))
        .map_err(|e| format!("读取配置失败: {}", e.message()))?;

    let app_opt = {
        let guard = runtime.server.lock().await;
        guard.as_ref().map(|h| Arc::clone(&h.state.app))
    };

    let (in_process, cache_stats) = if let Some(app) = app_opt {
        let stats = app
            .cache
            .stats()
            .await
            .map_err(|e| format!("读取缓存统计失败: {}", e.message()))?;
        (
            true,
            Some(CacheStatsDto {
                entries: stats.entries,
                size_bytes: stats.size_bytes,
                max_size_bytes: stats.max_size_bytes,
            }),
        )
    } else {
        (false, None)
    };

    Ok(AppInfoDto {
        version: mograb_core::VERSION.to_string(),
        data_dir: paths.root.display().to_string(),
        config_file: paths.config_file.display().to_string(),
        database: paths.database.display().to_string(),
        covers_dir: paths.covers_dir.display().to_string(),
        exports_dir: paths.exports_dir.display().to_string(),
        logs_dir: paths.logs_dir.display().to_string(),
        sources_dir: paths.sources_dir.display().to_string(),
        in_process,
        settings,
        cache_stats,
    })
}

#[tauri::command]
async fn save_settings(patch: SettingsPatch) -> Result<AppSettings, String> {
    let data_dir = resolve_data_dir();
    let paths = get_paths(Some(&data_dir));
    paths
        .ensure()
        .map_err(|e| format!("创建数据目录失败: {e}"))?;

    let mut settings = load_settings(Some(&paths.config_file))
        .map_err(|e| format!("读取现有配置失败: {}", e.message()))?;
    apply_settings_patch(&mut settings, patch)?;

    let body = toml::to_string_pretty(&settings).map_err(|e| format!("序列化配置失败: {e}"))?;
    fs::write(&paths.config_file, body).map_err(|e| format!("写入配置文件失败: {e}"))?;
    Ok(settings)
}

#[tauri::command]
async fn clear_http_cache(
    runtime: tauri::State<'_, Arc<AppRuntime>>,
    expired_only: bool,
) -> Result<ClearCacheResult, String> {
    let app = {
        let guard = runtime.server.lock().await;
        guard.as_ref().map(|h| Arc::clone(&h.state.app))
    }
    .ok_or_else(|| "当前连接的是外部独立服务，请改用命令行 `mog cache clear`".to_string())?;

    let removed = if expired_only {
        app.cache
            .purge_expired()
            .await
            .map_err(|e| format!("清理过期缓存失败: {}", e.message()))?
    } else {
        app.cache
            .clear()
            .await
            .map_err(|e| format!("清空缓存失败: {}", e.message()))?
    };

    let stats = app
        .cache
        .stats()
        .await
        .map_err(|e| format!("刷新缓存统计失败: {}", e.message()))?;

    Ok(ClearCacheResult {
        removed,
        stats: CacheStatsDto {
            entries: stats.entries,
            size_bytes: stats.size_bytes,
            max_size_bytes: stats.max_size_bytes,
        },
    })
}

async fn shutdown_backend(runtime: &Arc<AppRuntime>) {
    let handle = runtime.server.lock().await.take();
    let Some(mut handle) = handle else {
        return;
    };
    if let Some(tx) = handle.shutdown_tx.take() {
        let _ = tx.send(());
    }
    if let Some(join) = handle.join.take() {
        let _ = tokio::time::timeout(Duration::from_secs(3), join).await;
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let runtime = Arc::new(AppRuntime::new());
    let runtime_for_setup = Arc::clone(&runtime);
    let runtime_for_exit = Arc::clone(&runtime);

    let app = tauri::Builder::default()
        .manage(runtime)
        .invoke_handler(tauri::generate_handler![
            backend_wait,
            get_app_info,
            save_settings,
            clear_http_cache
        ])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("MoGrab")
                .inner_size(1180.0, 780.0)
                .min_inner_size(900.0, 600.0)
                .background_color(Color(0x1b, 0x1d, 0x23, 0xff))
                .on_navigation(is_allowed_nav)
                .build()?;

            let rt = Arc::clone(&runtime_for_setup);
            tauri::async_runtime::spawn(async move {
                let _ = ensure_backend(&rt).await;
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("构建 Tauri 应用失败");

    app.run(move |_app_handle, event| {
        if matches!(event, RunEvent::Exit) {
            tauri::async_runtime::block_on(shutdown_backend(&runtime_for_exit));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::{SettingsPatch, apply_settings_patch, is_allowed_nav};
    use mograb_core::config::AppSettings;

    #[test]
    fn test_allowed_navigation_urls() {
        for ok_url in [
            "tauri://localhost/index.html",
            "http://tauri.localhost/index.html",
            "https://tauri.localhost/index.html",
            "http://127.0.0.1:48721/health",
            "http://localhost:1420/",
            "about:blank",
        ] {
            let parsed = tauri::Url::parse(ok_url).unwrap();
            assert!(is_allowed_nav(&parsed), "expected allowed url: {ok_url}");
        }

        for bad_url in [
            "https://example.com/",
            "http://evil.localhost/",
            "file:///etc/passwd",
        ] {
            let parsed = tauri::Url::parse(bad_url).unwrap();
            assert!(!is_allowed_nav(&parsed), "expected blocked url: {bad_url}");
        }
    }

    #[test]
    fn test_settings_patch_validation() {
        let mut settings = AppSettings::default();
        let valid = SettingsPatch {
            concurrency: Some(8),
            per_source_concurrency: Some(3),
            proxy: Some("  ".to_string()),
            output_format: Some("markdown".to_string()),
            logging_level: Some("debug".to_string()),
            ..SettingsPatch::default()
        };
        apply_settings_patch(&mut settings, valid).unwrap();
        assert_eq!(settings.download.concurrency, 8);
        assert_eq!(settings.download.proxy, None);
        assert_eq!(settings.output.format, "markdown");
        assert_eq!(settings.logging.level, "DEBUG");

        let invalid = SettingsPatch {
            output_format: Some("pdf".to_string()),
            ..SettingsPatch::default()
        };
        assert!(apply_settings_patch(&mut settings, invalid).is_err());
    }
}
