// SPDX-License-Identifier: GPL-3.0-only
//! 单个任务的执行与状态维护。

use crate::domain::enums::TaskStatus;
use crate::domain::task::Task;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tokio_util::sync::CancellationToken;
use tracing::error;

#[async_trait]
pub trait TaskHandler: Send + Sync {
    async fn handle(&self, task: &mut Task, cancel: CancellationToken) -> MoGrabResult<()>;
}

#[async_trait]
pub trait StatusListener: Send + Sync {
    async fn on_status_change(&self, task: &Task);
}

pub struct TaskRunner {
    handlers: HashMap<String, Arc<dyn TaskHandler>>,
    listener: Option<Arc<dyn StatusListener>>,
    cancelled: Arc<RwLock<HashSet<String>>>,
    tokens: Arc<Mutex<HashMap<String, CancellationToken>>>,
}

impl TaskRunner {
    pub fn new(
        handlers: HashMap<String, Arc<dyn TaskHandler>>,
        listener: Option<Arc<dyn StatusListener>>,
    ) -> Self {
        Self {
            handlers,
            listener,
            cancelled: Arc::new(RwLock::new(HashSet::new())),
            tokens: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    pub async fn cancel(&self, task_id: &str) {
        self.cancelled.write().await.insert(task_id.to_string());
        if let Some(tok) = self.tokens.lock().await.get(task_id) {
            tok.cancel();
        }
    }

    pub async fn is_cancelled(&self, task_id: &str) -> bool {
        self.cancelled.read().await.contains(task_id)
    }

    pub async fn run(&self, mut task: Task) -> Task {
        let _ = task.transition_to(TaskStatus::Running);
        task.started_at = Some(chrono::Utc::now());
        self.notify(&task).await;

        let type_key = task.task_type.as_str().to_string();
        let Some(handler) = self.handlers.get(&type_key).cloned() else {
            error!(task_id = %task.id, task_type = %type_key, "task.no_handler");
            task.error_code = Some("NO_HANDLER".to_string());
            task.error_message = Some(format!("没有注册处理 {type_key} 的 handler"));
            let _ = task.transition_to(TaskStatus::Failed);
            task.finished_at = Some(chrono::Utc::now());
            self.notify(&task).await;
            return task;
        };

        let token = CancellationToken::new();
        {
            let is_canc = self.cancelled.read().await.contains(&task.id);
            if is_canc {
                token.cancel();
            }
            self.tokens
                .lock()
                .await
                .insert(task.id.clone(), token.clone());
        }

        let res = if token.is_cancelled() {
            Err(MoGrabError::task_cancelled(format!(
                "任务 {} 已取消",
                task.id
            )))
        } else {
            handler.handle(&mut task, token.clone()).await
        };

        self.tokens.lock().await.remove(&task.id);
        self.cancelled.write().await.remove(&task.id);

        match res {
            Ok(()) => {
                let _ = task.transition_to(TaskStatus::Success);
                task.finished_at = Some(chrono::Utc::now());
            }
            Err(MoGrabError::TaskCancelled { message, .. }) => {
                task.error_code = Some("TASK_CANCELLED".to_string());
                task.error_message = Some(message);
                let _ = task.transition_to(TaskStatus::Cancelled);
                task.finished_at = Some(chrono::Utc::now());
            }
            Err(err) => {
                task.error_code = Some(err.code().to_string());
                task.error_message = Some(err.message().to_string());
                let _ = task.transition_to(TaskStatus::Failed);
                task.finished_at = Some(chrono::Utc::now());
                error!(task_id = %task.id, error = %err, "task.failed");
            }
        }

        self.notify(&task).await;
        task
    }

    async fn notify(&self, task: &Task) {
        if let Some(ref listener) = self.listener {
            listener.on_status_change(task).await;
        }
    }
}
