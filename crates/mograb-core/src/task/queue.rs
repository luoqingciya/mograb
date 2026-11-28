// SPDX-License-Identifier: GPL-3.0-only
//! 异步优先级任务队列。

use crate::domain::task::Task;
use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashSet};
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering as AtomicOrdering};
use tokio::sync::{Mutex, Notify};

#[derive(Debug)]
struct QueueItem {
    priority: i64,
    seq: u64,
    task: Task,
}

impl PartialEq for QueueItem {
    fn eq(&self, other: &Self) -> bool {
        self.priority == other.priority && self.seq == other.seq
    }
}

impl Eq for QueueItem {}

impl PartialOrd for QueueItem {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for QueueItem {
    fn cmp(&self, other: &Self) -> Ordering {
        self.priority
            .cmp(&other.priority)
            .then_with(|| other.seq.cmp(&self.seq))
    }
}

pub struct TaskQueue {
    heap: Mutex<BinaryHeap<QueueItem>>,
    cancelled: Mutex<HashSet<String>>,
    seq: AtomicU64,
    notify: Notify,
}

impl Default for TaskQueue {
    fn default() -> Self {
        Self::new()
    }
}

impl TaskQueue {
    pub fn new() -> Self {
        Self {
            heap: Mutex::new(BinaryHeap::new()),
            cancelled: Mutex::new(HashSet::new()),
            seq: AtomicU64::new(0),
            notify: Notify::new(),
        }
    }

    pub async fn put(&self, task: Task) {
        self.cancelled.lock().await.remove(&task.id);
        let seq = self.seq.fetch_add(1, AtomicOrdering::Relaxed);
        let item = QueueItem {
            priority: task.priority,
            seq,
            task,
        };
        self.heap.lock().await.push(item);
        self.notify.notify_one();
    }

    pub async fn get(&self) -> Task {
        loop {
            let notified = self.notify.notified();
            {
                let mut heap = self.heap.lock().await;
                while let Some(item) = heap.pop() {
                    let mut cancelled = self.cancelled.lock().await;
                    if cancelled.remove(&item.task.id) {
                        continue;
                    }
                    return item.task;
                }
            }
            notified.await;
        }
    }

    pub async fn cancel(&self, task_id: &str) {
        self.cancelled.lock().await.insert(task_id.to_string());
    }

    pub async fn pending(&self) -> usize {
        self.heap.lock().await.len()
    }
}

pub type SharedTaskQueue = Arc<TaskQueue>;
