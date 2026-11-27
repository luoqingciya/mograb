// SPDX-License-Identifier: GPL-3.0-only
//! ExportRecord 领域模型。

use super::enums::{ExportFormat, ExportStatus};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportRecord {
    pub id: String,
    pub book_id: String,
    pub format: ExportFormat,
    pub status: ExportStatus,
    pub path: Option<String>,
    pub size_bytes: i64,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
    pub finished_at: Option<DateTime<Utc>>,
}

impl ExportRecord {
    pub fn is_terminal(&self) -> bool {
        matches!(self.status, ExportStatus::Success | ExportStatus::Failed)
    }
}
