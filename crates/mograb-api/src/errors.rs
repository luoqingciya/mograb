// SPDX-License-Identifier: GPL-3.0-only
//! 领域错误 -> HTTP 状态码与统一错误体映射。

use axum::Json;
use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use mograb_core::errors::MoGrabError;

pub struct ApiError(pub MoGrabError);

impl From<MoGrabError> for ApiError {
    fn from(err: MoGrabError) -> Self {
        Self(err)
    }
}

pub fn status_for(error: &MoGrabError) -> StatusCode {
    match error {
        MoGrabError::Auth { .. } => StatusCode::UNAUTHORIZED,
        MoGrabError::EntityNotFound { .. }
        | MoGrabError::SourceNotFound { .. }
        | MoGrabError::TaskNotFound { .. } => StatusCode::NOT_FOUND,
        MoGrabError::SourceSchema { .. }
        | MoGrabError::SourceUnsupported { .. }
        | MoGrabError::ContentValidation { .. }
        | MoGrabError::Export { .. }
        | MoGrabError::UnsafePath { .. } => StatusCode::UNPROCESSABLE_ENTITY,
        MoGrabError::TaskParameter { .. } => StatusCode::BAD_REQUEST,
        MoGrabError::HttpStatus { .. }
        | MoGrabError::Network { .. }
        | MoGrabError::Timeout { .. }
        | MoGrabError::RateLimited { .. } => StatusCode::BAD_GATEWAY,
        MoGrabError::Storage { .. } => StatusCode::INTERNAL_SERVER_ERROR,
        MoGrabError::Task { .. }
        | MoGrabError::InvalidTaskTransition { .. }
        | MoGrabError::TaskCancelled { .. } => StatusCode::CONFLICT,
        _ => StatusCode::INTERNAL_SERVER_ERROR,
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let status = status_for(&self.0);
        let body = self.0.to_api_body();
        let mut resp = (status, Json(body)).into_response();
        if matches!(self.0, MoGrabError::Auth { .. }) {
            resp.headers_mut().insert(
                header::WWW_AUTHENTICATE,
                HeaderValue::from_static(r#"Bearer realm="MoGrab""#),
            );
        }
        resp
    }
}
