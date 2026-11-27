// SPDX-License-Identifier: GPL-3.0-only
//! Task 与 TaskItem 领域模型及状态机转移。

use super::enums::{TaskItemStatus, TaskStatus, TaskType, can_transition};
use crate::errors::{MoGrabError, MoGrabResult};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskItem {
    pub id: String,
    pub task_id: String,
    pub chapter_id: Option<String>,
    pub chapter_index: Option<i64>,
    pub title: Option<String>,
    pub status: TaskItemStatus,
    pub attempts: i64,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    #[serde(rename = "type")]
    pub task_type: TaskType,
    pub status: TaskStatus,
    pub priority: i64,
    pub source_id: Option<String>,
    pub book_id: Option<String>,
    pub total: i64,
    pub completed: i64,
    pub failed: i64,
    pub retry_count: i64,
    pub max_retries: i64,
    pub resume_cursor: Option<i64>,
    pub params: Map<String, Value>,
    pub error_code: Option<String>,
    pub error_message: Option<String>,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub finished_at: Option<DateTime<Utc>>,
}

impl Task {
    pub fn progress(&self) -> f64 {
        if self.total <= 0 {
            return 0.0;
        }
        ((self.completed + self.failed) as f64 / self.total as f64).min(1.0)
    }

    pub fn is_terminal(&self) -> bool {
        self.status.is_terminal()
    }

    pub fn transition_to(&mut self, new_status: TaskStatus) -> MoGrabResult<()> {
        if new_status == self.status {
            return Ok(());
        }
        if !can_transition(self.status, new_status) {
            return Err(MoGrabError::invalid_transition(
                format!(
                    "非法状态转移: {} -> {}",
                    self.status.as_str(),
                    new_status.as_str()
                ),
                json!({
                    "task_id": self.id,
                    "from": self.status.as_str(),
                    "to": new_status.as_str(),
                }),
            ));
        }
        self.status = new_status;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_task() -> Task {
        Task {
            id: "task_1".into(),
            task_type: TaskType::DownloadBook,
            status: TaskStatus::Pending,
            priority: 0,
            source_id: None,
            book_id: None,
            total: 10,
            completed: 5,
            failed: 0,
            retry_count: 0,
            max_retries: 3,
            resume_cursor: None,
            params: Map::new(),
            error_code: None,
            error_message: None,
            created_at: Utc::now(),
            started_at: None,
            finished_at: None,
        }
    }

    #[test]
    fn test_task_state_machine() {
        let mut t = sample_task();
        assert_eq!(t.progress(), 0.5);
        assert!(t.transition_to(TaskStatus::Running).is_ok());
        assert!(t.transition_to(TaskStatus::Success).is_ok());
        assert!(t.is_terminal());
        let err = t.transition_to(TaskStatus::Pending).unwrap_err();
        assert_eq!(err.code(), "TASK_INVALID_TRANSITION");
    }
}
