// SPDX-License-Identifier: GPL-3.0-only
//! 应用装配（composition root）—— CLI 与 API 共用的唯一装配入口。

use crate::config::{AppSettings, Paths, get_paths, load_settings};
use crate::content::pipeline::ContentPipeline;
use crate::covers::CoverStore;
use crate::domain::book::Book;
use crate::domain::enums::{ExportStatus, TaskType};
use crate::domain::export::ExportRecord;
use crate::domain::ids::new_id;
use crate::domain::task::Task;
use crate::errors::{MoGrabError, MoGrabResult};
use crate::export::base::render_filename;
use crate::export::get_exporter;
use crate::logging::configure_logging;
use crate::network::{
    GlobalLimiter, HttpCache, HttpClient, HttpClientConfig, RetryPolicy, SourceLimiterRegistry,
};
use crate::source::engine::{Fetcher, SourceEngine};
use crate::source::request::DEFAULT_USER_AGENT;
use crate::storage::{
    BookRepository, ChapterRepository, Database, ExportRepository, SettingsRepository,
    SourceRepository, SqliteBookRepository, SqliteChapterRepository, SqliteExportRepository,
    SqliteHttpCache, SqliteSettingsRepository, SqliteSourceRepository, SqliteTaskRepository,
    TaskRepository,
};
use crate::task::manager::TaskManager;
use crate::task::runner::{StatusListener, TaskHandler, TaskRunner};
use crate::task::scheduler::{DownloadScheduler, ProgressHook};
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tokio::sync::RwLock;
use tokio_util::sync::CancellationToken;
use tracing::debug;

pub const PROGRESS_NOTIFY_INTERVAL: Duration = Duration::from_secs(1);

struct SharedAppState {
    settings: AppSettings,
    paths: Paths,
    books: Arc<dyn BookRepository>,
    chapters: Arc<dyn ChapterRepository>,
    sources: Arc<dyn SourceRepository>,
    exports: Arc<dyn ExportRepository>,
    scheduler: Arc<DownloadScheduler>,
    progress_listener: RwLock<Option<Arc<dyn StatusListener>>>,
}

impl SharedAppState {
    fn resolve_export_target(
        &self,
        book: &Book,
        explicit: Option<&str>,
        fmt: Option<&str>,
    ) -> PathBuf {
        if let Some(raw) = explicit
            && !raw.trim().is_empty()
        {
            return crate::config::paths::expand_tilde(raw);
        }
        let configured = PathBuf::from(&self.settings.output.directory);
        let dir = if configured.is_absolute() {
            configured
        } else {
            self.paths.root.join(configured)
        };
        let name = render_filename(&self.settings.output.template, book, None);
        let ext = crate::domain::enums::ExportFormat::from_str_opt(
            fmt.unwrap_or(&self.settings.output.format),
        )
        .map(|f| f.extension())
        .unwrap_or("epub");
        dir.join(format!("{name}.{ext}"))
    }
}

struct ThrottledProgress {
    task: Arc<tokio::sync::Mutex<Task>>,
    shared: Arc<SharedAppState>,
    last_notified: Mutex<Option<Instant>>,
}

#[async_trait]
impl ProgressHook for ThrottledProgress {
    async fn on_progress(&self, done: usize, total: usize) {
        let snapshot = {
            let mut guard = self.task.lock().await;
            guard.completed = done as i64;
            guard.total = total as i64;
            guard.clone()
        };

        let listener = self.shared.progress_listener.read().await.clone();
        let Some(listener) = listener else {
            return;
        };

        let should_send = if done >= total {
            true
        } else {
            let mut last = self.last_notified.lock().expect("last_notified mutex");
            match *last {
                Some(t) if t.elapsed() < PROGRESS_NOTIFY_INTERVAL => false,
                _ => {
                    *last = Some(Instant::now());
                    true
                }
            }
        };

        if should_send {
            listener.on_status_change(&snapshot).await;
        }
    }
}

struct DownloadHandler {
    shared: Arc<SharedAppState>,
    cli_hook: Option<Arc<dyn ProgressHook>>,
}

#[async_trait]
impl TaskHandler for DownloadHandler {
    async fn handle(&self, task: &mut Task, cancel: CancellationToken) -> MoGrabResult<()> {
        let book_id = if let Some(ref bid) = task.book_id {
            bid.clone()
        } else {
            let url = task
                .params
                .get("url")
                .and_then(|v| v.as_str())
                .map(str::to_string);
            let Some(url) = url else {
                return Err(MoGrabError::task_parameter_with(
                    "下载任务需要 book_id，或者 source_id + params.url",
                    json!({"task_id": task.id}),
                ));
            };
            let Some(ref sid) = task.source_id else {
                return Err(MoGrabError::task_parameter_with(
                    "下载任务需要 book_id，或者 source_id + params.url",
                    json!({"task_id": task.id}),
                ));
            };
            let book = self.shared.scheduler.ensure_book(sid, &url).await?;
            task.book_id = Some(book.id.clone());
            book.id
        };

        let progress_hook: Arc<dyn ProgressHook> = match &self.cli_hook {
            Some(h) => Arc::clone(h),
            None => Arc::new(ThrottledProgress {
                task: Arc::new(tokio::sync::Mutex::new(task.clone())),
                shared: Arc::clone(&self.shared),
                last_notified: Mutex::new(None),
            }),
        };

        let report = self
            .shared
            .scheduler
            .run(&book_id, Some(progress_hook), Some(cancel), None)
            .await?;

        task.total = report.plan.total as i64;
        task.completed = report.downloaded as i64;
        task.failed = report.failed as i64;
        if !report.plan.missing.is_empty() {
            let missing_vals: Vec<Value> = report
                .plan
                .missing
                .iter()
                .map(|m| Value::String(m.clone()))
                .collect();
            task.params
                .insert("missing".to_string(), Value::Array(missing_vals));
        }

        if report.downloaded == 0 && report.failed > 0 {
            let first = &report.failures[0];
            return Err(MoGrabError::task(
                format!("所有章节都下载失败：{}", first.message),
                json!({"code": first.code, "failed": report.failed}),
            ));
        }

        Ok(())
    }
}

struct ExportHandler {
    shared: Arc<SharedAppState>,
}

#[async_trait]
impl TaskHandler for ExportHandler {
    async fn handle(&self, task: &mut Task, _cancel: CancellationToken) -> MoGrabResult<()> {
        let Some(ref book_id) = task.book_id else {
            return Err(MoGrabError::task_parameter_with(
                "导出任务缺少 book_id",
                json!({"task_id": task.id}),
            ));
        };

        let book = self.shared.books.get(book_id).await?.ok_or_else(|| {
            MoGrabError::entity_not_found(
                format!("书籍不存在: {book_id}"),
                json!({"book_id": book_id}),
            )
        })?;

        let fmt = task
            .params
            .get("format")
            .and_then(|v| v.as_str())
            .filter(|s| !s.is_empty())
            .unwrap_or(&self.shared.settings.output.format)
            .to_string();

        let exporter = get_exporter(
            &fmt,
            Some(self.shared.paths.covers_dir.clone()),
            self.shared.settings.output.metadata.clone(),
        )?;

        let explicit_target = task.params.get("target").and_then(|v| v.as_str());
        let target = self.shared.resolve_export_target(
            &book,
            explicit_target,
            Some(exporter.format().as_str()),
        );

        let export_id = task
            .params
            .get("export_id")
            .and_then(|v| v.as_str())
            .map(str::to_string)
            .unwrap_or_else(|| new_id("export"));

        let mut record = ExportRecord {
            id: export_id,
            book_id: book.id.clone(),
            format: exporter.format(),
            status: ExportStatus::Running,
            path: None,
            size_bytes: 0,
            error_message: None,
            created_at: Utc::now(),
            finished_at: None,
        };
        self.shared.exports.save(&record).await?;

        let chapters = self.shared.chapters.list_by_book(&book.id).await?;
        match exporter.export(&book, &chapters, &target).await {
            Ok(result) => {
                record.status = ExportStatus::Success;
                record.path = Some(result.path.display().to_string());
                record.size_bytes = result.size_bytes as i64;
                record.finished_at = Some(Utc::now());
                self.shared.exports.save(&record).await?;
                task.params
                    .insert("export_id".to_string(), Value::String(record.id));
                task.params.insert(
                    "path".to_string(),
                    Value::String(result.path.display().to_string()),
                );
                task.total = 1;
                task.completed = 1;
                Ok(())
            }
            Err(err) => {
                record.status = ExportStatus::Failed;
                record.error_message = Some(err.message().to_string());
                record.finished_at = Some(Utc::now());
                let _ = self.shared.exports.save(&record).await;
                Err(err)
            }
        }
    }
}

struct RefreshSourceHandler {
    shared: Arc<SharedAppState>,
}

#[async_trait]
impl TaskHandler for RefreshSourceHandler {
    async fn handle(&self, task: &mut Task, _cancel: CancellationToken) -> MoGrabResult<()> {
        let entries = self.shared.sources.rescan().await?;
        task.total = entries.len() as i64;
        task.completed = entries.len() as i64;
        Ok(())
    }
}

pub struct Application {
    pub settings: AppSettings,
    pub paths: Paths,
    pub database: Database,
    pub sources: Arc<dyn SourceRepository>,
    pub books: Arc<dyn BookRepository>,
    pub chapters: Arc<dyn ChapterRepository>,
    pub tasks: Arc<dyn TaskRepository>,
    pub exports: Arc<dyn ExportRepository>,
    pub cache: Arc<SqliteHttpCache>,
    pub preferences: Arc<dyn SettingsRepository>,
    pub http: Arc<HttpClient>,
    pub engine: Arc<SourceEngine>,
    pub pipeline: Arc<ContentPipeline>,
    pub scheduler: Arc<DownloadScheduler>,
    pub task_manager: Arc<TaskManager>,
    shared: Arc<SharedAppState>,
}

impl Application {
    pub async fn create_default() -> MoGrabResult<Self> {
        Self::create(None, None, None, false, None).await
    }

    pub async fn create(
        settings_opt: Option<AppSettings>,
        paths_opt: Option<Paths>,
        log_level: Option<&str>,
        console_logging: bool,
        status_listener: Option<Arc<dyn StatusListener>>,
    ) -> MoGrabResult<Self> {
        let settings = match settings_opt {
            Some(s) => s,
            None => load_settings(None)?,
        };
        let paths = paths_opt.unwrap_or_else(|| get_paths(None));
        paths
            .ensure()
            .map_err(|e| MoGrabError::storage(format!("创建数据目录失败: {e}")))?;

        configure_logging(
            log_level.unwrap_or(&settings.logging.level),
            Some(&paths.logs_dir),
            settings.logging.json_output,
            console_logging,
        );

        let database = Database::open(&paths.database).await?;
        database.init_schema().await?;

        let sources: Arc<dyn SourceRepository> = Arc::new(SqliteSourceRepository::new(
            database.clone(),
            &paths.sources_dir,
        ));
        let books: Arc<dyn BookRepository> = Arc::new(SqliteBookRepository::new(database.clone()));
        let chapters: Arc<dyn ChapterRepository> =
            Arc::new(SqliteChapterRepository::new(database.clone()));
        let tasks: Arc<dyn TaskRepository> = Arc::new(SqliteTaskRepository::new(database.clone()));
        let exports: Arc<dyn ExportRepository> =
            Arc::new(SqliteExportRepository::new(database.clone()));
        let preferences: Arc<dyn SettingsRepository> =
            Arc::new(SqliteSettingsRepository::new(database.clone()));

        let max_cache_bytes = if settings.cache.enabled {
            settings.cache.max_size_bytes()?
        } else {
            0
        };
        let cache = Arc::new(SqliteHttpCache::new(database.clone(), max_cache_bytes));
        let cache_trait: Option<Arc<dyn HttpCache>> = if settings.cache.enabled {
            Some(Arc::clone(&cache) as Arc<dyn HttpCache>)
        } else {
            None
        };

        let limiters = Arc::new(SourceLimiterRegistry::new(
            GlobalLimiter::new(settings.download.concurrency),
            settings.download.per_source_concurrency,
            settings.download.request_interval_ms as f64 / 1000.0,
        ));
        let http = Arc::new(HttpClient::new(
            HttpClientConfig {
                timeout_ms: settings.download.timeout_ms,
                retry: RetryPolicy::with_max_retries(settings.download.retry),
                verify_ssl: true,
                proxy: settings.download.proxy.clone(),
                user_agent: Some(DEFAULT_USER_AGENT.to_string()),
                max_redirects: 5,
                allow_domains: Default::default(),
            },
            cache_trait,
            Some(limiters),
        )?);

        let fetcher: Arc<dyn Fetcher> = Arc::clone(&http) as Arc<dyn Fetcher>;
        let engine = Arc::new(SourceEngine::new(Arc::clone(&fetcher)));
        let pipeline = Arc::new(ContentPipeline::new(None));
        let covers = Arc::new(CoverStore::new(fetcher, paths.clone()));
        let scheduler = Arc::new(DownloadScheduler::new(
            Arc::clone(&engine),
            Arc::clone(&sources),
            Arc::clone(&books),
            Arc::clone(&chapters),
            Some(Arc::clone(&pipeline)),
            None,
            Some(covers),
        ));

        let shared = Arc::new(SharedAppState {
            settings: settings.clone(),
            paths: paths.clone(),
            books: Arc::clone(&books),
            chapters: Arc::clone(&chapters),
            sources: Arc::clone(&sources),
            exports: Arc::clone(&exports),
            scheduler: Arc::clone(&scheduler),
            progress_listener: RwLock::new(status_listener.clone()),
        });

        let handlers = build_handlers(Arc::clone(&shared), None);
        let worker_count = settings.download.concurrency.max(2);
        let task_manager = Arc::new(TaskManager::new(
            Arc::clone(&tasks),
            handlers,
            worker_count,
            status_listener,
        ));

        debug!(root = %paths.root.display(), "app.ready");
        Ok(Self {
            settings,
            paths,
            database,
            sources,
            books,
            chapters,
            tasks,
            exports,
            cache,
            preferences,
            http,
            engine,
            pipeline,
            scheduler,
            task_manager,
            shared,
        })
    }

    pub async fn aclose(&self) {
        self.task_manager.stop(true).await;
        self.database.dispose().await;
    }

    pub async fn create_task(
        &self,
        task_type: TaskType,
        book_id: Option<String>,
        source_id: Option<String>,
        priority: i64,
        params: Map<String, Value>,
        enqueue: bool,
    ) -> MoGrabResult<Task> {
        self.require_task_target(task_type, book_id.as_deref(), source_id.as_deref(), &params)
            .await?;
        self.task_manager
            .create(
                task_type,
                book_id,
                source_id,
                priority,
                0,
                self.settings.download.retry as i64,
                params,
                enqueue,
            )
            .await
    }

    async fn require_task_target(
        &self,
        task_type: TaskType,
        book_id: Option<&str>,
        source_id: Option<&str>,
        params: &Map<String, Value>,
    ) -> MoGrabResult<()> {
        match task_type {
            TaskType::RefreshSource => Ok(()),
            TaskType::ExportBook => {
                let Some(bid) = book_id else {
                    return Err(MoGrabError::task_parameter("导出任务缺少 book_id"));
                };
                self.require_book(bid).await
            }
            TaskType::DownloadBook | TaskType::UpdateBook => {
                if let Some(bid) = book_id {
                    return self.require_book(bid).await;
                }
                let url = params.get("url").and_then(|v| v.as_str()).unwrap_or("");
                let Some(sid) = source_id else {
                    return Err(MoGrabError::task_parameter(
                        "下载任务需要 book_id，或者 source_id + params.url",
                    ));
                };
                if url.is_empty() {
                    return Err(MoGrabError::task_parameter(
                        "下载任务需要 book_id，或者 source_id + params.url",
                    ));
                }
                if self.sources.get(sid).await?.is_none() {
                    return Err(MoGrabError::source_not_found(
                        format!("书源不存在: {sid}"),
                        json!({"source_id": sid}),
                    ));
                }
                Ok(())
            }
        }
    }

    async fn require_book(&self, book_id: &str) -> MoGrabResult<()> {
        if self.books.get(book_id).await?.is_none() {
            return Err(MoGrabError::entity_not_found(
                format!("书籍不存在: {book_id}"),
                json!({"book_id": book_id}),
            ));
        }
        Ok(())
    }

    pub async fn run_task(
        &self,
        task_type: TaskType,
        book_id: Option<String>,
        source_id: Option<String>,
        params: Map<String, Value>,
        on_progress: Option<Arc<dyn ProgressHook>>,
    ) -> MoGrabResult<Task> {
        let task = self
            .create_task(task_type, book_id, source_id, 0, params, false)
            .await?;

        struct SaveListener(Arc<dyn TaskRepository>);
        #[async_trait]
        impl StatusListener for SaveListener {
            async fn on_status_change(&self, task: &Task) {
                let _ = self.0.save(task).await;
            }
        }

        let handlers = build_handlers(Arc::clone(&self.shared), on_progress);
        let runner = TaskRunner::new(
            handlers,
            Some(Arc::new(SaveListener(Arc::clone(&self.tasks)))),
        );
        Ok(runner.run(task).await)
    }

    pub fn resolve_export_target(
        &self,
        book: &Book,
        explicit: Option<&str>,
        fmt: Option<&str>,
    ) -> PathBuf {
        self.shared.resolve_export_target(book, explicit, fmt)
    }
}

fn build_handlers(
    shared: Arc<SharedAppState>,
    cli_hook: Option<Arc<dyn ProgressHook>>,
) -> HashMap<String, Arc<dyn TaskHandler>> {
    let mut map: HashMap<String, Arc<dyn TaskHandler>> = HashMap::new();
    let dl: Arc<dyn TaskHandler> = Arc::new(DownloadHandler {
        shared: Arc::clone(&shared),
        cli_hook,
    });
    map.insert(TaskType::DownloadBook.as_str().to_string(), Arc::clone(&dl));
    map.insert(TaskType::UpdateBook.as_str().to_string(), dl);
    map.insert(
        TaskType::ExportBook.as_str().to_string(),
        Arc::new(ExportHandler {
            shared: Arc::clone(&shared),
        }),
    );
    map.insert(
        TaskType::RefreshSource.as_str().to_string(),
        Arc::new(RefreshSourceHandler { shared }),
    );
    map
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::enums::TaskStatus;
    use axum::{Router, response::Html, routing::get};
    use std::path::Path;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn test_end_to_end_mock_http_download_and_export() {
        let search_html =
            include_str!("../../../tests/fixtures/example-source/fixtures/search.html");
        let book_html = include_str!("../../../tests/fixtures/example-source/fixtures/book.html");
        let chapter_html =
            include_str!("../../../tests/fixtures/example-source/fixtures/chapter.html");

        let app_router = Router::new()
            .route("/search", get(move || async move { Html(search_html) }))
            .route("/book/1001", get(move || async move { Html(book_html) }))
            .route(
                "/book/1001/chapter/1",
                get(move || async move { Html(chapter_html) }),
            )
            .route(
                "/book/1001/chapter/2",
                get(move || async move { Html(chapter_html) }),
            )
            .route(
                "/book/1001/chapter/3",
                get(move || async move { Html(chapter_html) }),
            );

        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server_task = tokio::spawn(async move {
            axum::serve(listener, app_router).await.unwrap();
        });

        let dir = tempfile::tempdir().unwrap();
        let paths = get_paths(Some(dir.path()));
        let mut settings = AppSettings::default();
        settings.download.request_interval_ms = 0;

        let app = Application::create(Some(settings), Some(paths), Some("error"), false, None)
            .await
            .unwrap();

        let source_yaml = include_str!("../../../tests/fixtures/example-source/source.yaml")
            .replace("https://example.com", &format!("http://{addr}"))
            .replace("- example.com", "- 127.0.0.1");
        let spec = crate::source::load_source_str(&source_yaml, "mock").unwrap();
        app.sources.save(&spec).await.unwrap();

        let hits = app.engine.search(&spec, "三体", 1).await.unwrap();
        assert_eq!(hits.len(), 3);

        let mut params = Map::new();
        params.insert("url".into(), Value::String(hits[0].url.clone()));
        let task = app
            .run_task(
                TaskType::DownloadBook,
                None,
                Some(spec.id.clone()),
                params,
                None,
            )
            .await
            .unwrap();
        assert_eq!(task.status, TaskStatus::Success);
        assert_eq!(task.completed, 3);
        let book_id = task.book_id.unwrap();

        let mut exp_params = Map::new();
        exp_params.insert("format".into(), Value::String("epub".into()));
        let exp_task = app
            .run_task(
                TaskType::ExportBook,
                Some(book_id.clone()),
                None,
                exp_params,
                None,
            )
            .await
            .unwrap();
        assert_eq!(exp_task.status, TaskStatus::Success);
        let epub_path = exp_task.params.get("path").unwrap().as_str().unwrap();
        assert!(Path::new(epub_path).is_file());

        let search_hits = app
            .chapters
            .search_content("汪淼", Some(&book_id), 10)
            .await
            .unwrap();
        assert!(!search_hits.is_empty());

        app.aclose().await;
        server_task.abort();
    }
}
