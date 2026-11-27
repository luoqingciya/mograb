// SPDX-License-Identifier: GPL-3.0-only
//! `/api/v1/tasks` —— 任务控制。

use crate::AppState;
use crate::errors::ApiError;
use axum::Json;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use chrono::{DateTime, Utc};
use mograb_core::domain::enums::{TaskStatus, TaskType};
use mograb_core::domain::task::Task;
use mograb_core::errors::MoGrabError;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use utoipa::ToSchema;

#[derive(Debug, Deserialize, ToSchema)]
pub struct TaskCreate {
    #[serde(rename = "type")]
    pub task_type: String,
    #[serde(default)]
    pub book_id: Option<String>,
    #[serde(default)]
    pub source_id: Option<String>,
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default)]
    pub priority: i64,
    #[serde(default)]
    pub params: Map<String, Value>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct TaskOut {
    pub id: String,
    #[serde(rename = "type")]
    pub task_type: String,
    pub status: String,
    pub priority: i64,
    pub book_id: Option<String>,
    pub source_id: Option<String>,
    pub total: i64,
    pub completed: i64,
    pub failed: i64,
    pub progress: f64,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
    pub params: Map<String, Value>,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub finished_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Deserialize)]
pub struct ListTasksQuery {
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default = "default_limit")]
    pub limit: usize,
}

fn default_limit() -> usize {
    50
}

fn to_out(task: Task) -> TaskOut {
    let progress = (task.progress() * 10000.0).round() / 10000.0;
    TaskOut {
        id: task.id,
        task_type: task.task_type.as_str().to_string(),
        status: task.status.as_str().to_string(),
        priority: task.priority,
        book_id: task.book_id,
        source_id: task.source_id,
        total: task.total,
        completed: task.completed,
        failed: task.failed,
        progress,
        error_code: task.error_code,
        error_message: task.error_message,
        params: task.params,
        created_at: task.created_at,
        started_at: task.started_at,
        finished_at: task.finished_at,
    }
}

#[utoipa::path(
    post,
    path = "/api/v1/tasks",
    tag = "tasks",
    summary = "创建任务",
    request_body = TaskCreate,
    responses((status = 201, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn create_task(
    State(state): State<AppState>,
    Json(payload): Json<TaskCreate>,
) -> Result<(StatusCode, Json<TaskOut>), ApiError> {
    let task_type = TaskType::from_str_opt(&payload.task_type).ok_or_else(|| {
        ApiError(MoGrabError::task_parameter(format!(
            "未知任务类型: {}",
            payload.task_type
        )))
    })?;
    let mut params = payload.params;
    if let Some(url) = payload.url
        && !url.is_empty()
    {
        params.insert("url".to_string(), Value::String(url));
    }
    let priority = payload.priority.clamp(0, 100);
    let task = state
        .app
        .create_task(
            task_type,
            payload.book_id,
            payload.source_id,
            priority,
            params,
            true,
        )
        .await?;
    Ok((StatusCode::CREATED, Json(to_out(task))))
}

#[utoipa::path(
    get,
    path = "/api/v1/tasks",
    tag = "tasks",
    summary = "列出任务",
    params(
        ("status" = Option<String>, Query, description = "按状态过滤"),
        ("limit" = Option<usize>, Query, description = "返回上限")
    ),
    responses((status = 200, body = Vec<TaskOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn list_tasks(
    Query(query): Query<ListTasksQuery>,
    State(state): State<AppState>,
) -> Result<Json<Vec<TaskOut>>, ApiError> {
    let status_filter =
        match query.status.as_deref() {
            Some(s) if !s.is_empty() => Some(TaskStatus::from_str_opt(s).ok_or_else(|| {
                ApiError(MoGrabError::task_parameter(format!("未知任务状态: {s}")))
            })?),
            _ => None,
        };
    let limit = query.limit.clamp(1, 200);
    let tasks = state.app.tasks.list_all(status_filter).await?;
    Ok(Json(tasks.into_iter().take(limit).map(to_out).collect()))
}

#[utoipa::path(
    get,
    path = "/api/v1/tasks/{task_id}",
    tag = "tasks",
    summary = "任务详情",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn get_task(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<TaskOut>, ApiError> {
    let task = state.app.task_manager.get(&task_id).await?;
    Ok(Json(to_out(task)))
}

#[utoipa::path(
    post,
    path = "/api/v1/tasks/{task_id}/pause",
    tag = "tasks",
    summary = "暂停任务",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn pause_task(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<TaskOut>, ApiError> {
    let task = state.app.task_manager.pause(&task_id).await?;
    Ok(Json(to_out(task)))
}

#[utoipa::path(
    post,
    path = "/api/v1/tasks/{task_id}/resume",
    tag = "tasks",
    summary = "继续任务",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn resume_task(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<TaskOut>, ApiError> {
    let task = state.app.task_manager.resume(&task_id).await?;
    Ok(Json(to_out(task)))
}

#[utoipa::path(
    post,
    path = "/api/v1/tasks/{task_id}/cancel",
    tag = "tasks",
    summary = "取消任务",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn cancel_task(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<TaskOut>, ApiError> {
    let task = state.app.task_manager.cancel(&task_id).await?;
    Ok(Json(to_out(task)))
}

#[utoipa::path(
    post,
    path = "/api/v1/tasks/{task_id}/retry",
    tag = "tasks",
    summary = "重试任务",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, body = TaskOut)),
    security(("MoGrabToken" = []))
)]
pub async fn retry_task(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<TaskOut>, ApiError> {
    let task = state.app.task_manager.retry(&task_id).await?;
    Ok(Json(to_out(task)))
}
