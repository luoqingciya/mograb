// SPDX-License-Identifier: GPL-3.0-only
//! `/api/v1/sources` —— 书源管理。

use crate::AppState;
use crate::errors::ApiError;
use axum::Json;
use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use mograb_core::domain::enums::HealthStatus;
use mograb_core::domain::source::InstalledSource;
use mograb_core::errors::MoGrabError;
use mograb_core::source::engine::FetchOptions;
use mograb_core::source::{lint, load_source_file, load_source_str};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::path::PathBuf;
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct SourceOut {
    pub id: String,
    pub name: String,
    pub version: String,
    pub spec_version: i64,
    pub homepage: Option<String>,
    pub repository: Option<String>,
    pub description: Option<String>,
    pub capabilities: Vec<String>,
    pub enabled: bool,
    pub health: String,
    pub installed_version: String,
    pub previous_version: Option<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SourceDetail {
    #[serde(flatten)]
    pub base: SourceOut,
    pub permissions: Value,
    pub path: String,
}

#[derive(Debug, Deserialize, ToSchema)]
pub struct SourceInstallRequest {
    #[serde(default = "default_mode")]
    pub mode: String,
    #[serde(default)]
    pub content: Option<String>,
    #[serde(default)]
    pub path: Option<String>,
    #[serde(default)]
    pub force: bool,
}

fn default_mode() -> String {
    "yaml".to_string()
}

#[derive(Debug, Serialize, ToSchema)]
pub struct SourceInstallResult {
    pub id: String,
    pub version: String,
    pub replaced: bool,
    pub path: String,
    pub warnings: Vec<String>,
}

#[derive(Debug, Serialize, ToSchema)]
pub struct RemoveSourceResult {
    pub removed: bool,
}

#[derive(Debug, Deserialize)]
pub struct DoctorQuery {
    #[serde(default)]
    pub live: bool,
}

fn to_out(entry: &InstalledSource) -> SourceOut {
    SourceOut {
        id: entry.spec.id.clone(),
        name: entry.spec.name.clone(),
        version: entry.spec.version.clone(),
        spec_version: entry.spec.spec_version,
        homepage: entry.spec.homepage.clone(),
        repository: entry.spec.repository.clone(),
        description: entry.spec.description.clone(),
        capabilities: entry
            .spec
            .capabilities
            .iter()
            .map(|c| c.as_str().to_string())
            .collect(),
        enabled: entry.enabled,
        health: entry.health.as_str().to_string(),
        installed_version: entry.installed_version.clone(),
        previous_version: entry.previous_version.clone(),
    }
}

fn not_found(source_id: &str) -> ApiError {
    ApiError(MoGrabError::source_not_found(
        format!("书源未安装: {source_id}"),
        json!({"source_id": source_id}),
    ))
}

#[utoipa::path(
    get,
    path = "/api/v1/sources",
    tag = "sources",
    summary = "列出已安装书源",
    responses((status = 200, body = Vec<SourceOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn list_sources(State(state): State<AppState>) -> Result<Json<Vec<SourceOut>>, ApiError> {
    let entries = state.app.sources.list_all().await?;
    Ok(Json(entries.iter().map(to_out).collect()))
}

#[utoipa::path(
    post,
    path = "/api/v1/sources",
    tag = "sources",
    summary = "安装书源",
    request_body = SourceInstallRequest,
    responses((status = 201, body = SourceInstallResult)),
    security(("MoGrabToken" = []))
)]
pub async fn create_source(
    State(state): State<AppState>,
    Json(payload): Json<SourceInstallRequest>,
) -> Result<(StatusCode, Json<SourceInstallResult>), ApiError> {
    let spec = if payload.mode == "file" {
        let path = payload
            .path
            .as_deref()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| ApiError(MoGrabError::source_schema("mode=file 时必须提供 path")))?;
        load_source_file(&PathBuf::from(path))?
    } else {
        let content = payload
            .content
            .as_deref()
            .filter(|s| !s.is_empty())
            .ok_or_else(|| ApiError(MoGrabError::source_schema("mode=yaml 时必须提供 content")))?;
        load_source_str(content, "<api>")?
    };

    let report = lint(&spec);
    if !report.is_ready() && !payload.force {
        let errs: Vec<String> = report.errors().into_iter().map(|d| d.format()).collect();
        return Err(ApiError(MoGrabError::source_schema_with(
            "书源未通过校验",
            json!({"errors": errs}),
        )));
    }

    let existing = state.app.sources.get(&spec.id).await?;
    state.app.sources.save(&spec).await?;

    let result = SourceInstallResult {
        id: spec.id.clone(),
        version: spec.version.clone(),
        replaced: existing.is_some(),
        path: state
            .app
            .sources
            .source_path(&spec.id)
            .display()
            .to_string(),
        warnings: report
            .warnings()
            .into_iter()
            .map(|d| d.message.clone())
            .collect(),
    };
    Ok((StatusCode::CREATED, Json(result)))
}

#[utoipa::path(
    post,
    path = "/api/v1/sources/rescan",
    tag = "sources",
    summary = "重建书源索引",
    responses((status = 200, body = Vec<SourceOut>)),
    security(("MoGrabToken" = []))
)]
pub async fn rescan_sources(
    State(state): State<AppState>,
) -> Result<Json<Vec<SourceOut>>, ApiError> {
    let entries = state.app.sources.rescan().await?;
    Ok(Json(entries.iter().map(to_out).collect()))
}

#[utoipa::path(
    get,
    path = "/api/v1/sources/{source_id}",
    tag = "sources",
    summary = "查看书源详情",
    params(("source_id" = String, Path, description = "书源 ID")),
    responses((status = 200, body = SourceDetail)),
    security(("MoGrabToken" = []))
)]
pub async fn get_source(
    Path(source_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<SourceDetail>, ApiError> {
    let entry = state
        .app
        .sources
        .get(&source_id)
        .await?
        .ok_or_else(|| not_found(&source_id))?;
    let permissions = serde_json::to_value(&entry.spec.permissions).unwrap_or(json!({}));
    Ok(Json(SourceDetail {
        base: to_out(&entry),
        permissions,
        path: state
            .app
            .sources
            .source_path(&source_id)
            .display()
            .to_string(),
    }))
}

#[utoipa::path(
    delete,
    path = "/api/v1/sources/{source_id}",
    tag = "sources",
    summary = "卸载书源",
    params(("source_id" = String, Path, description = "书源 ID")),
    responses((status = 200, body = RemoveSourceResult)),
    security(("MoGrabToken" = []))
)]
pub async fn delete_source(
    Path(source_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<RemoveSourceResult>, ApiError> {
    let removed = state.app.sources.delete(&source_id).await?;
    if !removed {
        return Err(not_found(&source_id));
    }
    Ok(Json(RemoveSourceResult { removed }))
}

#[utoipa::path(
    post,
    path = "/api/v1/sources/{source_id}/enable",
    tag = "sources",
    summary = "启用书源",
    params(("source_id" = String, Path, description = "书源 ID")),
    responses((status = 200, body = SourceOut)),
    security(("MoGrabToken" = []))
)]
pub async fn enable_source(
    Path(source_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<SourceOut>, ApiError> {
    state.app.sources.set_enabled(&source_id, true).await?;
    let entry = state
        .app
        .sources
        .get(&source_id)
        .await?
        .ok_or_else(|| not_found(&source_id))?;
    Ok(Json(to_out(&entry)))
}

#[utoipa::path(
    post,
    path = "/api/v1/sources/{source_id}/disable",
    tag = "sources",
    summary = "禁用书源",
    params(("source_id" = String, Path, description = "书源 ID")),
    responses((status = 200, body = SourceOut)),
    security(("MoGrabToken" = []))
)]
pub async fn disable_source(
    Path(source_id): Path<String>,
    State(state): State<AppState>,
) -> Result<Json<SourceOut>, ApiError> {
    state.app.sources.set_enabled(&source_id, false).await?;
    let entry = state
        .app
        .sources
        .get(&source_id)
        .await?
        .ok_or_else(|| not_found(&source_id))?;
    Ok(Json(to_out(&entry)))
}

#[utoipa::path(
    post,
    path = "/api/v1/sources/{source_id}/doctor",
    tag = "sources",
    summary = "书源体检",
    params(
        ("source_id" = String, Path, description = "书源 ID"),
        ("live" = Option<bool>, Query, description = "是否访问主页确认可达")
    ),
    responses((status = 200, body = SourceOut)),
    security(("MoGrabToken" = []))
)]
pub async fn doctor_source(
    Path(source_id): Path<String>,
    Query(query): Query<DoctorQuery>,
    State(state): State<AppState>,
) -> Result<Json<SourceOut>, ApiError> {
    let entry = state
        .app
        .sources
        .get(&source_id)
        .await?
        .ok_or_else(|| not_found(&source_id))?;

    let mut problems = Vec::new();
    if !lint(&entry.spec).is_ready() {
        problems.push("lint 未通过");
    }

    if query.live
        && let Some(ref homepage) = entry.spec.homepage
    {
        let headers = BTreeMap::new();
        let cookies = BTreeMap::new();
        let res = state
            .app
            .http
            .fetch(FetchOptions {
                method: "GET",
                url: homepage,
                source_id: &entry.spec.id,
                headers: &headers,
                params: None,
                data: None,
                cookies: &cookies,
                encoding: None,
                timeout_ms: None,
                use_cache: false,
                ttl_seconds: None,
                allowed_domains: Some(&entry.spec.permissions.network),
                concurrency: None,
                min_interval_secs: None,
                max_retries: None,
            })
            .await;
        if res.is_err() {
            problems.push("主页不可达");
        }
    }

    let health = if problems.is_empty() {
        HealthStatus::Healthy
    } else if problems.iter().any(|p| p.contains("lint")) {
        HealthStatus::Broken
    } else {
        HealthStatus::Degraded
    };

    state.app.sources.set_health(&source_id, health).await?;
    let updated = state
        .app
        .sources
        .get(&source_id)
        .await?
        .ok_or_else(|| not_found(&source_id))?;
    Ok(Json(to_out(&updated)))
}
