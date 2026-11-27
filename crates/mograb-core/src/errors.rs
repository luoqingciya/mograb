// SPDX-License-Identifier: GPL-3.0-only
//! MoGrab 核心错误体系。
//!
//! 所有可预期失败必须落到本模块的 :enum:`MoGrabError` 层次中：
//! - 每个变体携带稳定的机器可读错误码（大写下划线）；
//! - `retryable()` 显式声明是否适合自动重试；
//! - `to_api_body()` 直接生成 REST API 统一错误体 `{code, message, details}`。

use serde::Serialize;
use serde_json::{Map, Value};
use std::fmt;

pub type MoGrabResult<T> = Result<T, MoGrabError>;

#[derive(Debug, Clone, Serialize)]
pub struct ApiErrorBody {
    pub code: String,
    pub message: String,
    pub details: Value,
}

#[derive(Debug, Clone)]
pub enum MoGrabError {
    Other {
        code: String,
        message: String,
        details: Value,
        retryable: bool,
    },
    Config {
        message: String,
        details: Value,
    },
    Auth {
        message: String,
        details: Value,
    },
    Source {
        message: String,
        details: Value,
    },
    SourceSchema {
        message: String,
        details: Value,
    },
    SourceExecution {
        message: String,
        details: Value,
    },
    SourceUnsupported {
        message: String,
        details: Value,
    },
    SourceNotFound {
        message: String,
        details: Value,
    },
    Network {
        message: String,
        details: Value,
    },
    Timeout {
        message: String,
        details: Value,
    },
    RateLimited {
        message: String,
        retry_after: Option<f64>,
        details: Value,
    },
    HttpStatus {
        message: String,
        status_code: u16,
        details: Value,
    },
    Parse {
        message: String,
        details: Value,
    },
    ContentValidation {
        message: String,
        details: Value,
    },
    Task {
        message: String,
        details: Value,
    },
    TaskNotFound {
        message: String,
        details: Value,
    },
    TaskParameter {
        message: String,
        details: Value,
    },
    InvalidTaskTransition {
        message: String,
        details: Value,
    },
    TaskCancelled {
        message: String,
        details: Value,
    },
    Storage {
        message: String,
        details: Value,
    },
    EntityNotFound {
        message: String,
        details: Value,
    },
    Export {
        message: String,
        details: Value,
    },
    UnsafePath {
        message: String,
        details: Value,
    },
}

fn empty_details() -> Value {
    Value::Object(Map::new())
}

impl MoGrabError {
    pub fn code(&self) -> &str {
        match self {
            Self::Other { code, .. } => code,
            Self::Config { .. } => "CONFIG_ERROR",
            Self::Auth { .. } => "AUTH_REQUIRED",
            Self::Source { .. } => "SOURCE_ERROR",
            Self::SourceSchema { .. } => "SOURCE_SCHEMA_ERROR",
            Self::SourceExecution { .. } => "SOURCE_EXECUTION_ERROR",
            Self::SourceUnsupported { .. } => "SOURCE_UNSUPPORTED_ERROR",
            Self::SourceNotFound { .. } => "SOURCE_NOT_FOUND",
            Self::Network { .. } => "NETWORK_ERROR",
            Self::Timeout { .. } => "NETWORK_TIMEOUT",
            Self::RateLimited { .. } => "NETWORK_RATE_LIMITED",
            Self::HttpStatus { .. } => "NETWORK_HTTP_STATUS",
            Self::Parse { .. } => "PARSE_ERROR",
            Self::ContentValidation { .. } => "CONTENT_VALIDATION_ERROR",
            Self::Task { .. } => "TASK_ERROR",
            Self::TaskNotFound { .. } => "TASK_NOT_FOUND",
            Self::TaskParameter { .. } => "TASK_PARAMETER_ERROR",
            Self::InvalidTaskTransition { .. } => "TASK_INVALID_TRANSITION",
            Self::TaskCancelled { .. } => "TASK_CANCELLED",
            Self::Storage { .. } => "STORAGE_ERROR",
            Self::EntityNotFound { .. } => "STORAGE_NOT_FOUND",
            Self::Export { .. } => "EXPORT_ERROR",
            Self::UnsafePath { .. } => "EXPORT_UNSAFE_PATH",
        }
    }

    pub fn message(&self) -> &str {
        match self {
            Self::Other { message, .. }
            | Self::Config { message, .. }
            | Self::Auth { message, .. }
            | Self::Source { message, .. }
            | Self::SourceSchema { message, .. }
            | Self::SourceExecution { message, .. }
            | Self::SourceUnsupported { message, .. }
            | Self::SourceNotFound { message, .. }
            | Self::Network { message, .. }
            | Self::Timeout { message, .. }
            | Self::RateLimited { message, .. }
            | Self::HttpStatus { message, .. }
            | Self::Parse { message, .. }
            | Self::ContentValidation { message, .. }
            | Self::Task { message, .. }
            | Self::TaskNotFound { message, .. }
            | Self::TaskParameter { message, .. }
            | Self::InvalidTaskTransition { message, .. }
            | Self::TaskCancelled { message, .. }
            | Self::Storage { message, .. }
            | Self::EntityNotFound { message, .. }
            | Self::Export { message, .. }
            | Self::UnsafePath { message, .. } => message,
        }
    }

    pub fn details(&self) -> &Value {
        match self {
            Self::Other { details, .. }
            | Self::Config { details, .. }
            | Self::Auth { details, .. }
            | Self::Source { details, .. }
            | Self::SourceSchema { details, .. }
            | Self::SourceExecution { details, .. }
            | Self::SourceUnsupported { details, .. }
            | Self::SourceNotFound { details, .. }
            | Self::Network { details, .. }
            | Self::Timeout { details, .. }
            | Self::RateLimited { details, .. }
            | Self::HttpStatus { details, .. }
            | Self::Parse { details, .. }
            | Self::ContentValidation { details, .. }
            | Self::Task { details, .. }
            | Self::TaskNotFound { details, .. }
            | Self::TaskParameter { details, .. }
            | Self::InvalidTaskTransition { details, .. }
            | Self::TaskCancelled { details, .. }
            | Self::Storage { details, .. }
            | Self::EntityNotFound { details, .. }
            | Self::Export { details, .. }
            | Self::UnsafePath { details, .. } => details,
        }
    }

    pub fn retryable(&self) -> bool {
        match self {
            Self::Other { retryable, .. } => *retryable,
            Self::Network { .. } | Self::Timeout { .. } | Self::RateLimited { .. } => true,
            Self::HttpStatus { status_code, .. } => *status_code >= 500 || *status_code == 429,
            _ => false,
        }
    }

    pub fn retry_after(&self) -> Option<f64> {
        match self {
            Self::RateLimited { retry_after, .. } => *retry_after,
            _ => None,
        }
    }

    pub fn to_api_body(&self) -> ApiErrorBody {
        ApiErrorBody {
            code: self.code().to_string(),
            message: self.message().to_string(),
            details: self.details().clone(),
        }
    }

    // ---- 便捷构造函数 ----
    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn config_with(msg: impl Into<String>, details: Value) -> Self {
        Self::Config {
            message: msg.into(),
            details,
        }
    }

    pub fn auth(msg: impl Into<String>, details: Value) -> Self {
        Self::Auth {
            message: msg.into(),
            details,
        }
    }

    pub fn source_schema(msg: impl Into<String>) -> Self {
        Self::SourceSchema {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn source_schema_with(msg: impl Into<String>, details: Value) -> Self {
        Self::SourceSchema {
            message: msg.into(),
            details,
        }
    }

    pub fn source_execution(msg: impl Into<String>) -> Self {
        Self::SourceExecution {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn source_execution_with(msg: impl Into<String>, details: Value) -> Self {
        Self::SourceExecution {
            message: msg.into(),
            details,
        }
    }

    pub fn source_unsupported(msg: impl Into<String>) -> Self {
        Self::SourceUnsupported {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn source_unsupported_with(msg: impl Into<String>, details: Value) -> Self {
        Self::SourceUnsupported {
            message: msg.into(),
            details,
        }
    }

    pub fn source_not_found(msg: impl Into<String>, details: Value) -> Self {
        Self::SourceNotFound {
            message: msg.into(),
            details,
        }
    }

    pub fn network(msg: impl Into<String>, details: Value) -> Self {
        Self::Network {
            message: msg.into(),
            details,
        }
    }

    pub fn timeout(msg: impl Into<String>, details: Value) -> Self {
        Self::Timeout {
            message: msg.into(),
            details,
        }
    }

    pub fn rate_limited(msg: impl Into<String>, retry_after: Option<f64>, details: Value) -> Self {
        Self::RateLimited {
            message: msg.into(),
            retry_after,
            details,
        }
    }

    pub fn http_status(msg: impl Into<String>, status_code: u16, details: Value) -> Self {
        Self::HttpStatus {
            message: msg.into(),
            status_code,
            details,
        }
    }

    pub fn parse(msg: impl Into<String>) -> Self {
        Self::Parse {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn content_validation(msg: impl Into<String>, details: Value) -> Self {
        Self::ContentValidation {
            message: msg.into(),
            details,
        }
    }

    pub fn task(msg: impl Into<String>, details: Value) -> Self {
        Self::Task {
            message: msg.into(),
            details,
        }
    }

    pub fn task_not_found(msg: impl Into<String>, details: Value) -> Self {
        Self::TaskNotFound {
            message: msg.into(),
            details,
        }
    }

    pub fn task_parameter(msg: impl Into<String>) -> Self {
        Self::TaskParameter {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn task_parameter_with(msg: impl Into<String>, details: Value) -> Self {
        Self::TaskParameter {
            message: msg.into(),
            details,
        }
    }

    pub fn invalid_transition(msg: impl Into<String>, details: Value) -> Self {
        Self::InvalidTaskTransition {
            message: msg.into(),
            details,
        }
    }

    pub fn task_cancelled(msg: impl Into<String>) -> Self {
        Self::TaskCancelled {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn storage(msg: impl Into<String>) -> Self {
        Self::Storage {
            message: msg.into(),
            details: empty_details(),
        }
    }

    pub fn storage_with(msg: impl Into<String>, details: Value) -> Self {
        Self::Storage {
            message: msg.into(),
            details,
        }
    }

    pub fn entity_not_found(msg: impl Into<String>, details: Value) -> Self {
        Self::EntityNotFound {
            message: msg.into(),
            details,
        }
    }

    pub fn export(msg: impl Into<String>, details: Value) -> Self {
        Self::Export {
            message: msg.into(),
            details,
        }
    }

    pub fn unsafe_path(msg: impl Into<String>, details: Value) -> Self {
        Self::UnsafePath {
            message: msg.into(),
            details,
        }
    }
}

impl fmt::Display for MoGrabError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let details = self.details();
        let has_details = match details {
            Value::Object(m) => !m.is_empty(),
            Value::Null => false,
            _ => true,
        };
        if has_details {
            write!(f, "[{}] {} | {}", self.code(), self.message(), details)
        } else {
            write!(f, "[{}] {}", self.code(), self.message())
        }
    }
}

impl std::error::Error for MoGrabError {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_retryable_flags() {
        assert!(MoGrabError::network("net", empty_details()).retryable());
        assert!(MoGrabError::timeout("to", empty_details()).retryable());
        assert!(MoGrabError::rate_limited("429", Some(2.0), empty_details()).retryable());
        assert!(MoGrabError::http_status("502", 502, empty_details()).retryable());
        assert!(MoGrabError::http_status("429", 429, empty_details()).retryable());
        assert!(!MoGrabError::http_status("404", 404, empty_details()).retryable());
        assert!(!MoGrabError::parse("bad").retryable());
        assert!(!MoGrabError::source_schema("bad").retryable());
        assert!(!MoGrabError::content_validation("short", json!({})).retryable());
    }

    #[test]
    fn test_to_api_body() {
        let err = MoGrabError::entity_not_found("missing", json!({"book_id": "b1"}));
        let body = err.to_api_body();
        assert_eq!(body.code, "STORAGE_NOT_FOUND");
        assert_eq!(body.message, "missing");
        assert_eq!(body.details["book_id"], "b1");
    }
}
