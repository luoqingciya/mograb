// SPDX-License-Identifier: GPL-3.0-only
//! `/api/v1/exports` —— 导出作业。

use crate::AppState;
use crate::errors::ApiError;
use axum::Json;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use chrono::{DateTime, Utc};
use mograb_core::domain::enums::{ExportFormat, ExportStatus, TaskType};
use mograb_core::domain::export::ExportRecord;
use mograb_core::domain::ids::new_id;
use mograb_core::errors::MoGrabError;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use utoipa::ToSchema;

#[derive(Debug, Deserialize, ToSchema)]
pub struct ExportCreate {
    pub book_id: String,
    #[serde(default = "default_format")]
    pub format: String,
    #[serde(default)]
    pub output: Option<String>,
}

fn default_format() -> String {
    "epub".to_string()
}

#[derive(Debug, Serialize, ToSchema)]
pub struct ExportOut {
    pub id: String,
    pub book_id: String,
    pub format: String,
    pub status: String,
    pub path: Option<String>,
    pub size_bytes: i64,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
}

#[derive(Debug, Deserialize)]
pub struct ListExportsQuery {
    #[serde(default = "default_limit")]
    pub limit: i64,
}

fn default_limit() -> i64 {
    50
}

fn to_out(r: ExportRecord) -> ExportOut {
    ExportOut {
        id: r.id,
        book_id: r.book_id,
        format: r.format.as_str().to_string(),
        status: r.status.as_str().to_string(),
        path: r.path,
        size_bytes: r.size_bytes,
        error_message: r.error_message,
        created_at: r.created_at,
        finished_at: r.finished_at,
    }
}

#[utoipa::path(
    post,
    path = "/api/v1/exports",
    tag = "exports",
    summary = "创建导出作业",
    request_body = ExportCreate,
    responses((status = 201, body = ExportOut)),
    security(("MoGrabToken" = []))
)]
pub async fn create_export(
    State(state): State<AppState>,
    Json(payload): Json<ExportCreate>,
) -> Result<(StatusCode, Json<ExportOut>), ApiError> {
    let fmt = ExportFormat::from_str_opt(&payload.format).ok_or_else(|| {
        ApiError(MoGrabError::export(
            format!("不支持的导出格式: {}", payload.format),
            json!({"format": payload.format}),
        ))
    })?;

    let book = state
        .app
        .books
        .get(&payload.book_id)
        .await?
        .ok_or_else(|| {
            ApiError(MoGrabError::entity_not_found(
                format!("书籍不存在: {}", payload.book_id),
                json!({"book_id": payload.book_id}),
            ))
        })?;

    let record = ExportRecord {
        id: new_id("export"),
        book_id: book.id.clone(),
        format: fmt,
        status: ExportStatus::Pending,
        path: None,
        size_bytes: 0,
        error_message: None,
        created_at: Utc::now(),
        finished_at: None,
    };
    state.app.exports.save(&record).await?;

    let mut params = Map::new();
    params.insert("export_id".to_string(), Value::String(record.id.clone()));
    params.insert(
        "format".to_string(),
        Value::String(fmt.as_str().to_string()),
    );
    params.insert(
        "target".to_string(),
        match payload.output {
            Some(p) => Value::String(p),
            None => Value::Null,
        },
    );

    state
        .app
        .create_task(TaskType::ExportBook, Some(book.id), None, 0, params, true)
        .await?;

    Ok((StatusCode::CREATED, Json(to_out(record))))
}

#[utoipa::path(
    get,
    path = "/api/v1/exports/{export_id}",
    tag = "exports",
    summary = "导出作业状态",
    params(("export_id" = String, Path, description = "导出作业 ID")),
    responses((status = 200, body = ExportOut)),
    security(("MoGrabToken" = []))
)]
pub async fn get_export(
    Path(export_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<ExportOut>, ApiError> {
    let record = state.app.exports.get(&export_id).await?.ok_or_else(|| {
        ApiError(MoGrabError::entity_not_found(
            format!("导出作业不存在: {export_id}"),
            json!({"export_id": export_id}),
        ))
    })?;
    Ok(Json(to_out(record)))
}

#[utoipa::path(
    get,
    path = "/api/v1/exports",
    tag = "exports",
    summary = "最近的导出作业",
    params(("limit" = Option<i64>, Query, description = "返回上限")),
    responses((status = 200, body = Vec<ExportOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn list_exports(
    Query(query): Query<ListExportsQuery>,
    State(state): State<AppState>,
) -> Result<Json<Vec<ExportOut>>, ApiError> {
    let limit = query.limit.clamp(1, 200);
    let list = state.app.exports.list_recent(limit).await?;
    Ok(Json(list.into_iter().map(to_out).collect()))
}
