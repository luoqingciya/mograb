// SPDX-License-Identifier: GPL-3.0-only
//! 按书源隔离的两级并发限流器。

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{Mutex, OwnedSemaphorePermit, Semaphore};

#[derive(Debug)]
pub struct SourceLimiter {
    pub concurrency: usize,
    pub min_interval: Duration,
    semaphore: Arc<Semaphore>,
    last_request_at: Mutex<Option<Instant>>,
}

impl SourceLimiter {
    pub fn new(concurrency: usize, min_interval_secs: f64) -> Self {
        let conc = concurrency.max(1);
        let interval = if min_interval_secs > 0.0 {
            Duration::from_secs_f64(min_interval_secs)
        } else {
            Duration::ZERO
        };
        Self {
            concurrency: conc,
            min_interval: interval,
            semaphore: Arc::new(Semaphore::new(conc)),
            last_request_at: Mutex::new(None),
        }
    }

    pub async fn acquire(&self) -> OwnedSemaphorePermit {
        let permit = Arc::clone(&self.semaphore)
            .acquire_owned()
            .await
            .expect("source limiter semaphore closed");

        if !self.min_interval.is_zero() {
            let mut last = self.last_request_at.lock().await;
            if let Some(prev) = *last {
                let elapsed = prev.elapsed();
                if elapsed < self.min_interval {
                    tokio::time::sleep(self.min_interval - elapsed).await;
                }
            }
            *last = Some(Instant::now());
        }

        permit
    }
}

#[derive(Debug, Clone)]
pub struct GlobalLimiter {
    pub concurrency: usize,
    semaphore: Arc<Semaphore>,
}

impl GlobalLimiter {
    pub fn new(concurrency: usize) -> Self {
        let conc = concurrency.max(1);
        Self {
            concurrency: conc,
            semaphore: Arc::new(Semaphore::new(conc)),
        }
    }

    pub async fn acquire(&self) -> OwnedSemaphorePermit {
        Arc::clone(&self.semaphore)
            .acquire_owned()
            .await
            .expect("global limiter semaphore closed")
    }
}

impl Default for GlobalLimiter {
    fn default() -> Self {
        Self::new(8)
    }
}

pub struct SourceLimiterRegistry {
    global: GlobalLimiter,
    limiters: Mutex<HashMap<String, Arc<SourceLimiter>>>,
    default_concurrency: usize,
    default_min_interval_secs: f64,
}

impl SourceLimiterRegistry {
    pub fn new(
        global: GlobalLimiter,
        default_concurrency: usize,
        default_min_interval_secs: f64,
    ) -> Self {
        Self {
            global,
            limiters: Mutex::new(HashMap::new()),
            default_concurrency,
            default_min_interval_secs,
        }
    }

    pub fn global_limiter(&self) -> &GlobalLimiter {
        &self.global
    }

    pub async fn get(
        &self,
        source_id: &str,
        concurrency: Option<usize>,
        min_interval_secs: Option<f64>,
    ) -> Arc<SourceLimiter> {
        let mut guard = self.limiters.lock().await;
        if let Some(existing) = guard.get(source_id) {
            return Arc::clone(existing);
        }
        let limiter = Arc::new(SourceLimiter::new(
            concurrency.unwrap_or(self.default_concurrency),
            min_interval_secs.unwrap_or(self.default_min_interval_secs),
        ));
        guard.insert(source_id.to_string(), Arc::clone(&limiter));
        limiter
    }
}
