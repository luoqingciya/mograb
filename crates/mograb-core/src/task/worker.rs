// SPDX-License-Identifier: GPL-3.0-only
//! Worker 池。

use super::queue::TaskQueue;
use super::runner::{StatusListener, TaskHandler, TaskRunner};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

pub struct WorkerPool {
    queue: Arc<TaskQueue>,
    runner: Arc<TaskRunner>,
    size: usize,
    shutdown: Mutex<CancellationToken>,
    handles: Mutex<Vec<JoinHandle<()>>>,
}

impl WorkerPool {
    pub fn new(
        queue: Arc<TaskQueue>,
        handlers: HashMap<String, Arc<dyn TaskHandler>>,
        size: usize,
        listener: Option<Arc<dyn StatusListener>>,
    ) -> Self {
        Self {
            queue,
            runner: Arc::new(TaskRunner::new(handlers, listener)),
            size: size.max(1),
            shutdown: Mutex::new(CancellationToken::new()),
            handles: Mutex::new(Vec::new()),
        }
    }

    pub fn size(&self) -> usize {
        self.size
    }

    pub async fn start(&self) {
        let mut handles = self.handles.lock().await;
        if !handles.is_empty() {
            return;
        }
        let token = CancellationToken::new();
        *self.shutdown.lock().await = token.clone();

        for _ in 0..self.size {
            let q = Arc::clone(&self.queue);
            let runner = Arc::clone(&self.runner);
            let stop = token.clone();
            let h = tokio::spawn(async move {
                loop {
                    tokio::select! {
                        _ = stop.cancelled() => break,
                        task = q.get() => {
                            let _ = runner.run(task).await;
                        }
                    }
                }
            });
            handles.push(h);
        }
    }

    pub async fn stop(&self, graceful: bool) {
        self.shutdown.lock().await.cancel();
        let mut handles = self.handles.lock().await;
        if !graceful {
            for h in handles.iter() {
                h.abort();
            }
        }
        for h in handles.drain(..) {
            let _ = h.await;
        }
    }

    pub async fn cancel_task(&self, task_id: &str) {
        self.runner.cancel(task_id).await;
    }

    pub async fn is_cancelled(&self, task_id: &str) -> bool {
        self.runner.is_cancelled(task_id).await
    }
}
