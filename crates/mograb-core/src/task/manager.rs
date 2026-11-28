// SPDX-License-Identifier: GPL-3.0-only
//! TaskManager —— 任务生命周期管理与孤儿恢复。

use super::queue::TaskQueue;
use super::runner::{StatusListener, TaskHandler};
use super::worker::WorkerPool;
use crate::domain::enums::{TaskStatus, TaskType};
use crate::domain::ids::new_id;
use crate::domain::task::{Task, TaskItem};
use crate::errors::{MoGrabError, MoGrabResult};
use crate::storage::repository::TaskRepository;
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{Map, Value, json};
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use tokio::sync::Mutex;
use tracing::{info, warn};

struct PersistAndBroadcast {
    repo: Arc<dyn TaskRepository>,
    downstream: Option<Arc<dyn StatusListener>>,
    state_lock: Arc<Mutex<()>>,
}

#[async_trait]
impl StatusListener for PersistAndBroadcast {
    async fn on_status_change(&self, task: &Task) {
        {
            let _guard = self.state_lock.lock().await;
            if let Ok(Some(existing)) = self.repo.get(&task.id).await {
                // 不允许异步 runner 用过期状态覆写终态或已暂停状态
                if (existing.is_terminal() && task.status != existing.status)
                    || (existing.status == TaskStatus::Paused && task.status == TaskStatus::Running)
                {
                    return;
                }
            }
            let _ = self.repo.save(task).await;
        }
        if let Some(ref listener) = self.downstream {
            listener.on_status_change(task).await;
        }
    }
}

pub struct TaskManager {
    repo: Arc<dyn TaskRepository>,
    queue: Arc<TaskQueue>,
    pool: WorkerPool,
    state_lock: Arc<Mutex<()>>,
    running: AtomicBool,
}

impl TaskManager {
    pub fn new(
        repo: Arc<dyn TaskRepository>,
        handlers: HashMap<String, Arc<dyn TaskHandler>>,
        worker_count: usize,
        on_status_change: Option<Arc<dyn StatusListener>>,
    ) -> Self {
        let queue = Arc::new(TaskQueue::new());
        let state_lock = Arc::new(Mutex::new(()));
        let listener = Arc::new(PersistAndBroadcast {
            repo: Arc::clone(&repo),
            downstream: on_status_change,
            state_lock: Arc::clone(&state_lock),
        });
        let pool = WorkerPool::new(Arc::clone(&queue), handlers, worker_count, Some(listener));
        Self {
            repo,
            queue,
            pool,
            state_lock,
            running: AtomicBool::new(false),
        }
    }

    pub async fn start(&self) -> MoGrabResult<()> {
        if self.running.swap(true, Ordering::SeqCst) {
            return Ok(());
        }
        self.recover_orphans().await?;
        self.pool.start().await;
        info!(workers = self.pool.size(), "task.manager_started");
        Ok(())
    }

    pub async fn stop(&self, graceful: bool) {
        if !self.running.swap(false, Ordering::SeqCst) {
            return;
        }
        self.pool.stop(graceful).await;
        info!("task.manager_stopped");
    }

    #[allow(clippy::too_many_arguments)]
    pub async fn create(
        &self,
        task_type: TaskType,
        book_id: Option<String>,
        source_id: Option<String>,
        priority: i64,
        total: i64,
        max_retries: i64,
        params: Map<String, Value>,
        enqueue: bool,
    ) -> MoGrabResult<Task> {
        let task = Task {
            id: new_id("task"),
            task_type,
            status: TaskStatus::Pending,
            priority,
            source_id,
            book_id,
            total,
            completed: 0,
            failed: 0,
            retry_count: 0,
            max_retries,
            resume_cursor: None,
            params,
            error_code: None,
            error_message: None,
            created_at: Utc::now(),
            started_at: None,
            finished_at: None,
        };
        self.repo.save(&task).await?;
        if enqueue {
            self.queue.put(task.clone()).await;
        }
        Ok(task)
    }

    pub async fn get(&self, task_id: &str) -> MoGrabResult<Task> {
        self.repo.get(task_id).await?.ok_or_else(|| {
            MoGrabError::task_not_found(
                format!("任务不存在: {task_id}"),
                json!({"task_id": task_id}),
            )
        })
    }

    pub async fn list(&self, status: Option<TaskStatus>) -> MoGrabResult<Vec<Task>> {
        self.repo.list_all(status).await
    }

    pub async fn list_items(&self, task_id: &str) -> MoGrabResult<Vec<TaskItem>> {
        self.repo.list_items(task_id).await
    }

    pub async fn pause(&self, task_id: &str) -> MoGrabResult<Task> {
        let _guard = self.state_lock.lock().await;
        let mut task = self.get(task_id).await?;
        task.transition_to(TaskStatus::Paused)?;
        self.pool.pause_task(task_id).await;
        self.queue.cancel(task_id).await;
        self.repo.save(&task).await?;
        Ok(task)
    }

    pub async fn resume(&self, task_id: &str) -> MoGrabResult<Task> {
        let _guard = self.state_lock.lock().await;
        let mut task = self.get(task_id).await?;
        if task.status != TaskStatus::Paused {
            return Err(MoGrabError::invalid_transition(
                format!("只有 PAUSED 任务可继续，当前为 {}", task.status.as_str()),
                json!({"task_id": task_id, "status": task.status.as_str()}),
            ));
        }
        task.transition_to(TaskStatus::Pending)?;
        self.pool.clear_task_control(task_id).await;
        self.repo.save(&task).await?;
        self.queue.put(task.clone()).await;
        Ok(task)
    }

    pub async fn is_cancelled(&self, task_id: &str) -> bool {
        self.pool.is_cancelled(task_id).await
    }

    pub async fn cancel(&self, task_id: &str) -> MoGrabResult<Task> {
        let _guard = self.state_lock.lock().await;
        self.pool.cancel_task(task_id).await;
        self.queue.cancel(task_id).await;
        let mut task = self.get(task_id).await?;
        if !task.is_terminal() {
            task.transition_to(TaskStatus::Cancelled)?;
            task.finished_at = Some(Utc::now());
            self.repo.save(&task).await?;
        }
        Ok(task)
    }

    pub async fn retry(&self, task_id: &str) -> MoGrabResult<Task> {
        let task = self.get(task_id).await?;
        if !matches!(task.status, TaskStatus::Failed | TaskStatus::Cancelled) {
            return Err(MoGrabError::invalid_transition(
                format!(
                    "只有 FAILED/CANCELLED 任务可重试，当前为 {}",
                    task.status.as_str()
                ),
                json!({"task_id": task_id, "status": task.status.as_str()}),
            ));
        }
        self.create(
            task.task_type,
            task.book_id,
            task.source_id,
            task.priority,
            task.total,
            task.max_retries,
            task.params,
            true,
        )
        .await
    }

    async fn recover_orphans(&self) -> MoGrabResult<()> {
        for status in [TaskStatus::Running, TaskStatus::Retrying] {
            for mut task in self.repo.list_by_status(status).await? {
                task.status = TaskStatus::Failed;
                task.error_code = Some("INTERRUPTED".to_string());
                task.error_message = Some("进程在任务执行期间退出，任务已中断".to_string());
                task.finished_at = Some(Utc::now());
                self.repo.save(&task).await?;
                warn!(task_id = %task.id, was = status.as_str(), "task.orphan_recovered");
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::{Database, SqliteTaskRepository};
    use std::sync::atomic::AtomicUsize;
    use std::time::Duration;
    use tokio::sync::Notify;
    use tokio_util::sync::CancellationToken;

    struct YieldOrCancelHandler;

    #[async_trait]
    impl TaskHandler for YieldOrCancelHandler {
        async fn handle(&self, _task: &mut Task, cancel: CancellationToken) -> MoGrabResult<()> {
            tokio::select! {
                _ = cancel.cancelled() => Err(MoGrabError::task_cancelled("测试取消")),
                _ = tokio::time::sleep(Duration::from_millis(5)) => Ok(()),
            }
        }
    }

    struct PauseThenCompleteHandler {
        calls: AtomicUsize,
        started: Arc<Notify>,
    }

    #[async_trait]
    impl TaskHandler for PauseThenCompleteHandler {
        async fn handle(&self, _task: &mut Task, cancel: CancellationToken) -> MoGrabResult<()> {
            let attempt = self.calls.fetch_add(1, Ordering::SeqCst);
            if attempt == 0 {
                self.started.notify_one();
                cancel.cancelled().await;
                return Err(MoGrabError::task_cancelled("暂停退出"));
            }
            Ok(())
        }
    }

    async fn setup_manager(
        handler: Arc<dyn TaskHandler>,
        workers: usize,
    ) -> (tempfile::TempDir, Database, TaskManager) {
        let dir = tempfile::tempdir().unwrap();
        let db = Database::open(dir.path().join("test.db")).await.unwrap();
        db.init_schema().await.unwrap();
        let repo: Arc<dyn TaskRepository> = Arc::new(SqliteTaskRepository::new(db.clone()));
        let mut handlers = HashMap::new();
        handlers.insert(TaskType::RefreshSource.as_str().to_string(), handler);
        let mgr = TaskManager::new(repo, handlers, workers, None);
        mgr.start().await.unwrap();
        (dir, db, mgr)
    }

    #[tokio::test]
    async fn test_cancel_race_never_reverts_to_running() {
        let (_dir, db, mgr) = setup_manager(Arc::new(YieldOrCancelHandler), 4).await;

        let mut ids = Vec::new();
        for _ in 0..30 {
            let task = mgr
                .create(
                    TaskType::RefreshSource,
                    None,
                    Some("src_1".into()),
                    0,
                    0,
                    0,
                    Map::new(),
                    true,
                )
                .await
                .unwrap();
            let cancelled = mgr.cancel(&task.id).await.unwrap();
            assert!(cancelled.is_terminal());

            let pause_err = mgr.pause(&task.id).await.unwrap_err();
            assert_eq!(pause_err.code(), "TASK_INVALID_TRANSITION");
            ids.push(task.id);
        }

        tokio::time::sleep(Duration::from_millis(60)).await;
        for id in ids {
            let latest = mgr.get(&id).await.unwrap();
            assert!(
                latest.is_terminal(),
                "任务 {} 不应回到非终态 {:?}",
                id,
                latest.status
            );
        }

        mgr.stop(true).await;
        db.dispose().await;
    }

    #[tokio::test]
    async fn test_pause_and_resume_preserves_paused_status() {
        let started = Arc::new(Notify::new());
        let handler = Arc::new(PauseThenCompleteHandler {
            calls: AtomicUsize::new(0),
            started: Arc::clone(&started),
        });
        let (_dir, db, mgr) = setup_manager(handler, 2).await;

        let task = mgr
            .create(
                TaskType::RefreshSource,
                None,
                Some("src_1".into()),
                0,
                0,
                0,
                Map::new(),
                true,
            )
            .await
            .unwrap();

        started.notified().await;
        let paused = mgr.pause(&task.id).await.unwrap();
        assert_eq!(paused.status, TaskStatus::Paused);

        // 等待首次运行因 CancellationToken 退出并完成状态通知
        tokio::time::sleep(Duration::from_millis(40)).await;
        let after_abort = mgr.get(&task.id).await.unwrap();
        assert_eq!(after_abort.status, TaskStatus::Paused);

        let resumed = mgr.resume(&task.id).await.unwrap();
        assert_eq!(resumed.status, TaskStatus::Pending);

        for _ in 0..40 {
            let latest = mgr.get(&task.id).await.unwrap();
            if latest.status == TaskStatus::Success {
                mgr.stop(true).await;
                db.dispose().await;
                return;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
        panic!("恢复后的任务未能在预期时间内完成");
    }
}
