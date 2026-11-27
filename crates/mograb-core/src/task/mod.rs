// SPDX-License-Identifier: GPL-3.0-only
//! Task 模块入口。

pub mod manager;
pub mod queue;
pub mod runner;
pub mod scheduler;
pub mod worker;

pub use manager::TaskManager;
pub use queue::TaskQueue;
pub use runner::{StatusListener, TaskHandler, TaskRunner};
pub use scheduler::{
    ChapterDiff, ChapterFailure, DownloadPlan, DownloadReport, DownloadScheduler, ProgressHook,
    compute_chapter_diff,
};
pub use worker::WorkerPool;
