// SPDX-License-Identifier: GPL-3.0-only
//! Bearer 令牌鉴权中间件。

use crate::AppState;
use crate::errors::ApiError;
use axum::extract::{Request, State};
use axum::http::header;
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use mograb_core::errors::MoGrabError;
use serde_json::json;
use subtle::ConstantTimeEq;

fn constant_time_str_eq(a: &str, b: &str) -> bool {
    let ab = a.as_bytes();
    let bb = b.as_bytes();
    ab.len() == bb.len() && bool::from(ab.ct_eq(bb))
}

pub async fn require_token(
    State(state): State<AppState>,
    request: Request,
    next: Next,
) -> Response {
    if !state.app.settings.server.auth {
        return next.run(request).await;
    }

    let provided = request
        .headers()
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| {
            s.strip_prefix("Bearer ")
                .or_else(|| s.strip_prefix("bearer "))
        });

    match provided {
        Some(tok) if constant_time_str_eq(tok.trim(), &state.token) => next.run(request).await,
        _ => ApiError(MoGrabError::auth(
            "缺少或无效的 API 令牌",
            json!({"scheme": "Bearer", "hint": "用 `mog server token` 查看令牌"}),
        ))
        .into_response(),
    }
}
