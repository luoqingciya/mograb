// SPDX-License-Identifier: GPL-3.0-only
//! 指数退避 + 抖动重试策略。

use crate::errors::MoGrabError;
use rand::RngExt;

pub const DEFAULT_MAX_RETRIES: usize = 3;
pub const DEFAULT_BASE_DELAY: f64 = 1.0;
pub const DEFAULT_MAX_DELAY: f64 = 60.0;
pub const DEFAULT_JITTER: f64 = 0.25;

#[derive(Debug, Clone)]
pub struct RetryPolicy {
    pub max_retries: usize,
    pub base_delay: f64,
    pub max_delay: f64,
    pub jitter: f64,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_retries: DEFAULT_MAX_RETRIES,
            base_delay: DEFAULT_BASE_DELAY,
            max_delay: DEFAULT_MAX_DELAY,
            jitter: DEFAULT_JITTER,
        }
    }
}

impl RetryPolicy {
    pub fn with_max_retries(max_retries: usize) -> Self {
        Self {
            max_retries,
            ..Self::default()
        }
    }

    pub fn delay_for(&self, attempt: usize, retry_after: Option<f64>) -> f64 {
        if let Some(ra) = retry_after {
            return ra.min(self.max_delay).max(0.0);
        }
        let exp = 2f64.powi(attempt.min(30) as i32);
        let mut delay = (self.base_delay * exp).min(self.max_delay);
        if self.jitter > 0.0 {
            let spread = delay * self.jitter;
            let delta = rand::rng().random_range(-spread..=spread);
            delay += delta;
        }
        delay.max(0.0)
    }

    pub fn should_retry(&self, error: &MoGrabError, attempt: usize) -> bool {
        if attempt >= self.max_retries {
            return false;
        }
        error.retryable()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_retry_policy() {
        let p = RetryPolicy::default();
        assert!(p.should_retry(&MoGrabError::timeout("t", json!({})), 0));
        assert!(!p.should_retry(&MoGrabError::timeout("t", json!({})), 3));
        assert!(!p.should_retry(&MoGrabError::parse("p"), 0));
        assert_eq!(p.delay_for(0, Some(10.0)), 10.0);
        assert_eq!(p.delay_for(0, Some(120.0)), 60.0);
    }
}
