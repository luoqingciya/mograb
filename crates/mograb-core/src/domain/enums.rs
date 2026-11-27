// SPDX-License-Identifier: GPL-3.0-only
//! 领域枚举与任务状态机转移表。

use serde::{Deserialize, Serialize};
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceCapability {
    Search,
    Book,
    Chapters,
    Content,
    // 保留能力（v1 引擎遇到时应报 SourceUnsupportedError）
    Discover,
    Image,
    Login,
    Cookie,
    Update,
}

impl SourceCapability {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Search => "search",
            Self::Book => "book",
            Self::Chapters => "chapters",
            Self::Content => "content",
            Self::Discover => "discover",
            Self::Image => "image",
            Self::Login => "login",
            Self::Cookie => "cookie",
            Self::Update => "update",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s {
            "search" => Some(Self::Search),
            "book" => Some(Self::Book),
            "chapters" => Some(Self::Chapters),
            "content" => Some(Self::Content),
            "discover" => Some(Self::Discover),
            "image" => Some(Self::Image),
            "login" => Some(Self::Login),
            "cookie" => Some(Self::Cookie),
            "update" => Some(Self::Update),
            _ => None,
        }
    }

    pub fn is_v1_supported(&self) -> bool {
        matches!(
            self,
            Self::Search | Self::Book | Self::Chapters | Self::Content
        )
    }
}

impl fmt::Display for SourceCapability {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum BookStatus {
    #[default]
    Unknown,
    Ongoing,
    Completed,
}

impl BookStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Unknown => "unknown",
            Self::Ongoing => "ongoing",
            Self::Completed => "completed",
        }
    }

    pub fn from_db_str(s: &str) -> Self {
        match s {
            "ongoing" => Self::Ongoing,
            "completed" => Self::Completed,
            _ => Self::Unknown,
        }
    }

    /// 把书源提取到的状态文本映射为枚举值。
    /// 只做整值精确匹配，不接受 "0"/"1"。
    pub fn parse(value: Option<&str>) -> Self {
        let Some(raw) = value else {
            return Self::Unknown;
        };
        let key = raw.trim().to_lowercase();
        if key.is_empty() {
            return Self::Unknown;
        }
        match key.as_str() {
            "unknown" | "未知" => Self::Unknown,
            "ongoing" | "serializing" | "连载" | "连载中" | "連載" | "連載中" => {
                Self::Ongoing
            }
            "completed" | "complete" | "finished" | "完结" | "已完结" | "完本" | "已完本"
            | "全本" => Self::Completed,
            _ => Self::Unknown,
        }
    }
}

impl fmt::Display for BookStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskType {
    DownloadBook,
    UpdateBook,
    ExportBook,
    RefreshSource,
}

impl TaskType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DownloadBook => "download_book",
            Self::UpdateBook => "update_book",
            Self::ExportBook => "export_book",
            Self::RefreshSource => "refresh_source",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s {
            "download_book" => Some(Self::DownloadBook),
            "update_book" => Some(Self::UpdateBook),
            "export_book" => Some(Self::ExportBook),
            "refresh_source" => Some(Self::RefreshSource),
            _ => None,
        }
    }
}

impl fmt::Display for TaskType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    #[default]
    Pending,
    Running,
    Paused,
    Retrying,
    Success,
    Failed,
    Cancelled,
}

impl TaskStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Paused => "paused",
            Self::Retrying => "retrying",
            Self::Success => "success",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "pending" => Some(Self::Pending),
            "running" => Some(Self::Running),
            "paused" => Some(Self::Paused),
            "retrying" => Some(Self::Retrying),
            "success" => Some(Self::Success),
            "failed" => Some(Self::Failed),
            "cancelled" => Some(Self::Cancelled),
            _ => None,
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Success | Self::Failed | Self::Cancelled)
    }
}

impl fmt::Display for TaskStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

pub fn can_transition(src: TaskStatus, dst: TaskStatus) -> bool {
    match src {
        TaskStatus::Pending => {
            matches!(
                dst,
                TaskStatus::Running | TaskStatus::Paused | TaskStatus::Cancelled
            )
        }
        TaskStatus::Running => matches!(
            dst,
            TaskStatus::Paused
                | TaskStatus::Retrying
                | TaskStatus::Success
                | TaskStatus::Failed
                | TaskStatus::Cancelled
        ),
        TaskStatus::Paused => matches!(
            dst,
            TaskStatus::Pending | TaskStatus::Running | TaskStatus::Cancelled | TaskStatus::Failed
        ),
        TaskStatus::Retrying => {
            matches!(
                dst,
                TaskStatus::Running | TaskStatus::Failed | TaskStatus::Cancelled
            )
        }
        TaskStatus::Success | TaskStatus::Failed | TaskStatus::Cancelled => false,
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum TaskItemStatus {
    #[default]
    Pending,
    Running,
    Success,
    Failed,
    Skipped,
    Cancelled,
}

impl TaskItemStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Success => "success",
            Self::Failed => "failed",
            Self::Skipped => "skipped",
            Self::Cancelled => "cancelled",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s {
            "pending" => Some(Self::Pending),
            "running" => Some(Self::Running),
            "success" => Some(Self::Success),
            "failed" => Some(Self::Failed),
            "skipped" => Some(Self::Skipped),
            "cancelled" => Some(Self::Cancelled),
            _ => None,
        }
    }
}

impl fmt::Display for TaskItemStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ExportFormat {
    Txt,
    Markdown,
    Epub,
}

impl ExportFormat {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Txt => "txt",
            Self::Markdown => "markdown",
            Self::Epub => "epub",
        }
    }

    pub fn extension(&self) -> &'static str {
        match self {
            Self::Txt => "txt",
            Self::Markdown => "md",
            Self::Epub => "epub",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s.trim().to_lowercase().as_str() {
            "txt" => Some(Self::Txt),
            "markdown" | "md" => Some(Self::Markdown),
            "epub" => Some(Self::Epub),
            _ => None,
        }
    }
}

impl fmt::Display for ExportFormat {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum ExportStatus {
    #[default]
    Pending,
    Running,
    Success,
    Failed,
}

impl ExportStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::Success => "success",
            Self::Failed => "failed",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s {
            "pending" => Some(Self::Pending),
            "running" => Some(Self::Running),
            "success" => Some(Self::Success),
            "failed" => Some(Self::Failed),
            _ => None,
        }
    }
}

impl fmt::Display for ExportStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum HealthStatus {
    Healthy,
    Degraded,
    Broken,
    Unsupported,
    #[default]
    Unknown,
}

impl HealthStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Healthy => "healthy",
            Self::Degraded => "degraded",
            Self::Broken => "broken",
            Self::Unsupported => "unsupported",
            Self::Unknown => "unknown",
        }
    }

    pub fn from_str_opt(s: &str) -> Option<Self> {
        match s {
            "healthy" => Some(Self::Healthy),
            "degraded" => Some(Self::Degraded),
            "broken" => Some(Self::Broken),
            "unsupported" => Some(Self::Unsupported),
            "unknown" => Some(Self::Unknown),
            _ => None,
        }
    }
}

impl fmt::Display for HealthStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ChapterChangeKind {
    New,
    Changed,
    Missing,
    Unchanged,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_book_status_parse() {
        assert_eq!(BookStatus::parse(None), BookStatus::Unknown);
        assert_eq!(BookStatus::parse(Some("")), BookStatus::Unknown);
        assert_eq!(BookStatus::parse(Some("0")), BookStatus::Unknown);
        assert_eq!(BookStatus::parse(Some("1")), BookStatus::Unknown);
        assert_eq!(BookStatus::parse(Some("非连载")), BookStatus::Unknown);
        assert_eq!(BookStatus::parse(Some(" 连载中 ")), BookStatus::Ongoing);
        assert_eq!(BookStatus::parse(Some("FINISHED")), BookStatus::Completed);
        assert_eq!(BookStatus::parse(Some("完本")), BookStatus::Completed);
    }

    #[test]
    fn test_task_transitions() {
        assert!(can_transition(TaskStatus::Pending, TaskStatus::Running));
        assert!(!can_transition(TaskStatus::Pending, TaskStatus::Success));
        assert!(can_transition(TaskStatus::Running, TaskStatus::Cancelled));
        assert!(!can_transition(TaskStatus::Success, TaskStatus::Pending));
        assert!(!can_transition(TaskStatus::Failed, TaskStatus::Running));
        assert!(!can_transition(TaskStatus::Cancelled, TaskStatus::Pending));
    }
}
