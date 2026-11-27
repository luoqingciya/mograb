// SPDX-License-Identifier: GPL-3.0-only
//! GET /health

use axum::Json;
use serde::Serialize;
use utoipa::ToSchema;

#[derive(Debug, Serialize, ToSchema)]
pub struct HealthOut {
    pub status: String,
    pub version: String,
}

#[utoipa::path(
    get,
    path = "/health",
    tag = "meta",
    summary = "健康检查",
    responses((status = 200, body = HealthOut))
)]
pub async fn health() -> Json<HealthOut> {
    Json(HealthOut {
        status: "ok".to_string(),
        version: mograb_core::VERSION.to_string(),
    })
}
