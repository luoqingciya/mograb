// SPDX-License-Identifier: GPL-3.0-only
//! 领域模型入口。

pub mod book;
pub mod chapter;
pub mod enums;
pub mod export;
pub mod ids;
pub mod source;
pub mod task;

pub use book::Book;
pub use chapter::{Chapter, ChapterSearchHit, ChapterSummary, compute_content_hash, normalize_url};
pub use enums::{
    BookStatus, ChapterChangeKind, ExportFormat, ExportStatus, HealthStatus, SourceCapability,
    TaskItemStatus, TaskStatus, TaskType, can_transition,
};
pub use export::ExportRecord;
pub use ids::{new_id, new_ulid};
pub use source::{
    BookSpec, ChapterSpec, CleanSpec, ContentSpec, ExtractRule, InstalledSource, NetworkPolicy,
    PaginationSpec, Permissions, RequestSpec, ResponseFormat, ResponseSpec, ResultSpec, RuleType,
    SOURCE_ID_RE, SPEC_VERSION, SearchSpec, SourceSpec, Transform, TransformOp,
};
pub use task::{Task, TaskItem};
