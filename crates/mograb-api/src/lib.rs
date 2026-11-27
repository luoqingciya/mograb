// SPDX-License-Identifier: GPL-3.0-only
//! MoGrab 本地 REST API Server（Axum）。

pub mod auth;
pub mod bus;
pub mod errors;
pub mod openapi;
pub mod routers;

use auth::require_token;
use axum::Router;
use axum::http::HeaderValue;
use axum::middleware;
use axum::routing::{get, post};
use bus::EventBus;
use mograb_core::app::Application;
use mograb_core::config::{AppSettings, Paths, ensure_token, get_paths, load_settings};
use mograb_core::domain::task::Task;
use mograb_core::errors::{MoGrabError, MoGrabResult};
use mograb_core::task::runner::StatusListener;
use openapi::ApiDoc;
use serde_json::json;
use std::sync::Arc;
use tokio::net::TcpListener;
use tower_http::cors::{AllowOrigin, Any, CorsLayer};
use tracing::info;
use utoipa::OpenApi;
use utoipa_swagger_ui::SwaggerUi;

pub const API_PREFIX: &str = "/api/v1";

#[derive(Clone)]
pub struct AppState {
    pub app: Arc<Application>,
    pub bus: EventBus,
    pub token: String,
}

struct BusPublisher(EventBus);

#[async_trait::async_trait]
impl StatusListener for BusPublisher {
    async fn on_status_change(&self, task: &Task) {
        self.0.publish(json!({
            "event": "task",
            "task_id": task.id,
            "type": task.task_type.as_str(),
            "status": task.status.as_str(),
            "book_id": task.book_id,
            "total": task.total,
            "completed": task.completed,
            "failed": task.failed,
            "error_code": task.error_code,
            "error_message": task.error_message,
        }));
    }
}

pub async fn build_state(
    settings_opt: Option<AppSettings>,
    paths_opt: Option<Paths>,
    console_logging: bool,
) -> MoGrabResult<AppState> {
    let settings = match settings_opt {
        Some(s) => s,
        None => load_settings(None)?,
    };
    let paths = paths_opt.unwrap_or_else(|| get_paths(None));
    let token = ensure_token(Some(&paths))
        .map_err(|e| MoGrabError::config(format!("初始化 API 令牌失败: {e}")))?;

    let bus = EventBus::new();
    let publisher: Arc<dyn StatusListener> = Arc::new(BusPublisher(bus.clone()));

    let app = Arc::new(
        Application::create(
            Some(settings),
            Some(paths),
            None,
            console_logging,
            Some(publisher),
        )
        .await?,
    );
    app.task_manager.start().await?;

    info!(
        version = mograb_core::VERSION,
        host = %app.settings.server.host,
        port = app.settings.server.port,
        auth = app.settings.server.auth,
        "api.startup"
    );

    Ok(AppState { app, bus, token })
}

fn is_allowed_origin(origin: &HeaderValue) -> bool {
    let Ok(s) = origin.to_str() else {
        return false;
    };
    if s == "null" || s.starts_with("file://") {
        return true;
    }
    let rest = s
        .strip_prefix("http://")
        .or_else(|| s.strip_prefix("https://"));
    let Some(authority) = rest else {
        return false;
    };
    let host = authority.split(':').next().unwrap_or("");
    matches!(host, "127.0.0.1" | "localhost")
}

pub fn create_router(state: AppState) -> Router {
    let guarded = Router::new()
        // events 必须在 tasks/{task_id} 之前
        .route("/tasks/events", get(routers::events::all_task_events))
        .route("/tasks/{task_id}/events", get(routers::events::task_events))
        // sources
        .route(
            "/sources",
            get(routers::sources::list_sources).post(routers::sources::create_source),
        )
        .route("/sources/rescan", post(routers::sources::rescan_sources))
        .route(
            "/sources/{source_id}",
            get(routers::sources::get_source).delete(routers::sources::delete_source),
        )
        .route(
            "/sources/{source_id}/enable",
            post(routers::sources::enable_source),
        )
        .route(
            "/sources/{source_id}/disable",
            post(routers::sources::disable_source),
        )
        .route(
            "/sources/{source_id}/doctor",
            post(routers::sources::doctor_source),
        )
        // search
        .route("/search", get(routers::search::search))
        .route("/search/local", get(routers::search::search_local))
        // books
        .route("/books", get(routers::books::list_books))
        .route("/books/{book_id}", get(routers::books::get_book))
        .route(
            "/books/{book_id}/chapters",
            get(routers::books::list_chapters),
        )
        .route(
            "/books/{book_id}/chapters/{chapter_id}",
            get(routers::books::get_chapter),
        )
        .route("/books/{book_id}/update", post(routers::books::update_book))
        // tasks
        .route(
            "/tasks",
            post(routers::tasks::create_task).get(routers::tasks::list_tasks),
        )
        .route("/tasks/{task_id}", get(routers::tasks::get_task))
        .route("/tasks/{task_id}/pause", post(routers::tasks::pause_task))
        .route("/tasks/{task_id}/resume", post(routers::tasks::resume_task))
        .route("/tasks/{task_id}/cancel", post(routers::tasks::cancel_task))
        .route("/tasks/{task_id}/retry", post(routers::tasks::retry_task))
        // exports
        .route(
            "/exports",
            post(routers::exports::create_export).get(routers::exports::list_exports),
        )
        .route("/exports/{export_id}", get(routers::exports::get_export))
        .layer(middleware::from_fn_with_state(state.clone(), require_token));

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::predicate(|origin, _| {
            is_allowed_origin(origin)
        }))
        .allow_methods(Any)
        .allow_headers(Any);

    Router::new()
        .route("/health", get(routers::health::health))
        .nest(API_PREFIX, guarded)
        .merge(SwaggerUi::new("/docs").url("/openapi.json", ApiDoc::openapi()))
        .layer(cors)
        .with_state(state)
}

pub async fn serve(host_override: Option<String>, port_override: Option<u16>) -> MoGrabResult<()> {
    let mut settings = load_settings(None)?;
    if let Some(h) = host_override {
        settings.server.host = h;
    }
    if let Some(p) = port_override {
        settings.server.port = p;
    }

    let listen_addr = format!("{}:{}", settings.server.host, settings.server.port);

    // 在 bind 之前确保令牌已落盘，避免 Desktop 启动竞态窗口
    let paths = get_paths(None);
    ensure_token(Some(&paths))
        .map_err(|e| MoGrabError::config(format!("初始化 API 令牌失败: {e}")))?;

    let state = build_state(Some(settings), Some(paths), true).await?;
    let router = create_router(state.clone());

    let listener = TcpListener::bind(&listen_addr)
        .await
        .map_err(|e| MoGrabError::network(format!("监听 {listen_addr} 失败: {e}"), json!({})))?;

    axum::serve(listener, router)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .map_err(|e| MoGrabError::network(format!("服务异常退出: {e}"), json!({})))?;

    info!("api.shutdown");
    state.app.aclose().await;
    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        let _ = tokio::signal::ctrl_c().await;
    };
    #[cfg(unix)]
    let terminate = async {
        use tokio::signal::unix::{SignalKind, signal};
        if let Ok(mut sig) = signal(SignalKind::terminate()) {
            sig.recv().await;
        } else {
            std::future::pending::<()>().await;
        }
    };
    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{Request, StatusCode, header};
    use std::time::Duration;
    use tower::ServiceExt;

    async fn test_app(auth: bool) -> (tempfile::TempDir, AppState, Router) {
        let dir = tempfile::tempdir().unwrap();
        let paths = get_paths(Some(dir.path()));
        let mut settings = AppSettings::default();
        settings.server.auth = auth;
        let state = build_state(Some(settings), Some(paths), false)
            .await
            .unwrap();
        let router = create_router(state.clone());
        (dir, state, router)
    }

    #[tokio::test]
    async fn test_health_auth_and_openapi_paths() {
        let (_dir, state, app) = test_app(true).await;

        // /health 不需要令牌
        let resp = app
            .clone()
            .oneshot(Request::get("/health").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let bytes = axum::body::to_bytes(resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let health_json: serde_json::Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(health_json["status"], "ok");
        assert_eq!(health_json["version"], mograb_core::VERSION);

        // 无令牌访问 /api/v1/sources 返回 401
        let unauth = app
            .clone()
            .oneshot(Request::get("/api/v1/sources").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(unauth.status(), StatusCode::UNAUTHORIZED);
        assert!(unauth.headers().contains_key(header::WWW_AUTHENTICATE));

        // 带令牌访问 /api/v1/sources 返回 200 []
        let ok_resp = app
            .clone()
            .oneshot(
                Request::get("/api/v1/sources")
                    .header(header::AUTHORIZATION, format!("Bearer {}", state.token))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(ok_resp.status(), StatusCode::OK);

        // /openapi.json 包含 24 条路径
        let openapi_resp = app
            .clone()
            .oneshot(Request::get("/openapi.json").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(openapi_resp.status(), StatusCode::OK);
        let oapi_bytes = axum::body::to_bytes(openapi_resp.into_body(), usize::MAX)
            .await
            .unwrap();
        let oapi: serde_json::Value = serde_json::from_slice(&oapi_bytes).unwrap();
        let paths_count = oapi["paths"].as_object().unwrap().len();
        assert_eq!(paths_count, 24);

        // 安装、查看、启用/禁用、卸载书源
        let yaml = include_str!("../../../tests/fixtures/example-source/source.yaml");
        let create_req = Request::post("/api/v1/sources")
            .header(header::AUTHORIZATION, format!("Bearer {}", state.token))
            .header(header::CONTENT_TYPE, "application/json")
            .body(Body::from(
                json!({"mode": "yaml", "content": yaml}).to_string(),
            ))
            .unwrap();
        let created = app.clone().oneshot(create_req).await.unwrap();
        assert_eq!(created.status(), StatusCode::CREATED);

        // 404 错误映射
        let missing = app
            .clone()
            .oneshot(
                Request::get("/api/v1/books/nonexistent")
                    .header(header::AUTHORIZATION, format!("Bearer {}", state.token))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(missing.status(), StatusCode::NOT_FOUND);

        state.app.aclose().await;
    }

    #[tokio::test]
    async fn test_sse_task_event_stream() {
        let (_dir, state, app) = test_app(true).await;
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let client = reqwest::Client::builder().no_proxy().build().unwrap();
        let mut resp = client
            .get(format!("http://{addr}/api/v1/tasks/events"))
            .header("Authorization", format!("Bearer {}", state.token))
            .send()
            .await
            .unwrap();
        assert_eq!(resp.status(), reqwest::StatusCode::OK);

        // 广播一条任务事件
        state.bus.publish(json!({
            "event": "task",
            "task_id": "task_test1",
            "type": "refresh_source",
            "status": "running",
            "total": 1,
            "completed": 0,
            "failed": 0
        }));

        let chunk = tokio::time::timeout(Duration::from_secs(3), resp.chunk())
            .await
            .unwrap()
            .unwrap()
            .unwrap();
        let text = String::from_utf8_lossy(&chunk);
        assert!(text.contains("event: task"));
        assert!(text.contains("task_test1"));

        server.abort();
        state.app.aclose().await;
    }

    #[tokio::test]
    async fn test_task_lifecycle_and_error_mapping() {
        let (_dir, state, app) = test_app(true).await;
        let auth = format!("Bearer {}", state.token);

        // 1. 422 SourceSchemaError: 提交非法 YAML 书源
        let bad_src = app
            .clone()
            .oneshot(
                Request::post("/api/v1/sources")
                    .header(header::AUTHORIZATION, &auth)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"mode": "yaml", "content": "id: BAD_ID\nname: x"}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(bad_src.status(), StatusCode::UNPROCESSABLE_ENTITY);

        // 2. 400 TaskParameterError: 缺少必要参数
        let bad_task = app
            .clone()
            .oneshot(
                Request::post("/api/v1/tasks")
                    .header(header::AUTHORIZATION, &auth)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(json!({"type": "download_book"}).to_string()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(bad_task.status(), StatusCode::BAD_REQUEST);

        // 3. 404 EntityNotFoundError: 未知 book_id / source_id
        let missing_book = app
            .clone()
            .oneshot(
                Request::post("/api/v1/tasks")
                    .header(header::AUTHORIZATION, &auth)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"type": "update_book", "book_id": "missing_book"}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(missing_book.status(), StatusCode::NOT_FOUND);

        // 安装示例书源以便创建 refresh_source 任务
        let yaml = include_str!("../../../tests/fixtures/example-source/source.yaml");
        let installed = app
            .clone()
            .oneshot(
                Request::post("/api/v1/sources")
                    .header(header::AUTHORIZATION, &auth)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"mode": "yaml", "content": yaml}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(installed.status(), StatusCode::CREATED);

        // 4. 201 refresh_source 任务创建 + GET 列表 + cancel/retry/409 状态转换
        let created = app
            .clone()
            .oneshot(
                Request::post("/api/v1/tasks")
                    .header(header::AUTHORIZATION, &auth)
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        json!({"type": "refresh_source", "source_id": "example_novel"}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(created.status(), StatusCode::CREATED);
        let created_bytes = axum::body::to_bytes(created.into_body(), usize::MAX)
            .await
            .unwrap();
        let created_task: serde_json::Value = serde_json::from_slice(&created_bytes).unwrap();
        let task_id = created_task["id"].as_str().unwrap().to_string();

        let listed = app
            .clone()
            .oneshot(
                Request::get("/api/v1/tasks")
                    .header(header::AUTHORIZATION, &auth)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(listed.status(), StatusCode::OK);
        let listed_bytes = axum::body::to_bytes(listed.into_body(), usize::MAX)
            .await
            .unwrap();
        let tasks: Vec<serde_json::Value> = serde_json::from_slice(&listed_bytes).unwrap();
        assert!(tasks.iter().any(|t| t["id"] == task_id));

        // 取消任务，然后再次取消（或暂停已取消任务）触发 409 Conflict
        let cancel_resp = app
            .clone()
            .oneshot(
                Request::post(format!("/api/v1/tasks/{task_id}/cancel"))
                    .header(header::AUTHORIZATION, &auth)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert!(
            cancel_resp.status() == StatusCode::OK || cancel_resp.status() == StatusCode::CONFLICT
        );

        let pause_terminal = app
            .clone()
            .oneshot(
                Request::post(format!("/api/v1/tasks/{task_id}/pause"))
                    .header(header::AUTHORIZATION, &auth)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(pause_terminal.status(), StatusCode::CONFLICT);

        // 对已终止（cancelled/completed/failed）任务可调用 retry，或对 completed 任务返回 409
        let retry_resp = app
            .clone()
            .oneshot(
                Request::post(format!("/api/v1/tasks/{task_id}/retry"))
                    .header(header::AUTHORIZATION, &auth)
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert!(
            retry_resp.status() == StatusCode::OK
                || retry_resp.status() == StatusCode::CREATED
                || retry_resp.status() == StatusCode::CONFLICT
        );

        state.app.aclose().await;
    }
}
