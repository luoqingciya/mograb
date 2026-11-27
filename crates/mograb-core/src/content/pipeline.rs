// SPDX-License-Identifier: GPL-3.0-only
//! 内容管线与校验。

use super::cleaner::clean_text;
use super::normalizer::{count_words, normalize_text};
use crate::domain::chapter::compute_content_hash;
use crate::errors::{MoGrabError, MoGrabResult};
use serde_json::json;
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct ContentPolicy {
    pub min_length: usize,
    pub max_length: usize,
    pub min_chinese_ratio: f64,
    pub reject_on_empty: bool,
    pub max_repeat_line_ratio: f64,
}

impl Default for ContentPolicy {
    fn default() -> Self {
        Self {
            min_length: 50,
            max_length: 200_000,
            min_chinese_ratio: 0.30,
            reject_on_empty: true,
            max_repeat_line_ratio: 0.60,
        }
    }
}

#[derive(Debug, Clone)]
pub struct ProcessedContent {
    pub text: String,
    pub word_count: i64,
    pub content_hash: String,
}

#[derive(Debug, Clone, Default)]
pub struct ContentPipeline {
    policy: ContentPolicy,
}

impl ContentPipeline {
    pub fn new(policy: Option<ContentPolicy>) -> Self {
        Self {
            policy: policy.unwrap_or_default(),
        }
    }

    pub fn policy(&self) -> &ContentPolicy {
        &self.policy
    }

    pub fn process(
        &self,
        raw: &str,
        extra_junk_patterns: Option<&[String]>,
    ) -> MoGrabResult<ProcessedContent> {
        let cleaned = clean_text(raw, None, extra_junk_patterns);
        let normalized = normalize_text(&cleaned);
        self.validate(&normalized)?;
        Ok(ProcessedContent {
            word_count: count_words(&normalized) as i64,
            content_hash: compute_content_hash(&normalized),
            text: normalized,
        })
    }

    pub fn validate(&self, text: &str) -> MoGrabResult<()> {
        let length = text.chars().count();

        if self.policy.reject_on_empty && text.trim().is_empty() {
            return Err(MoGrabError::content_validation(
                "正文为空",
                json!({"reason": "empty", "length": length}),
            ));
        }

        if length < self.policy.min_length {
            return Err(MoGrabError::content_validation(
                format!("正文过短（{length} < {}）", self.policy.min_length),
                json!({
                    "reason": "too_short",
                    "length": length,
                    "threshold": self.policy.min_length,
                }),
            ));
        }

        if length > self.policy.max_length {
            return Err(MoGrabError::content_validation(
                format!("正文过长（{length} > {}）", self.policy.max_length),
                json!({
                    "reason": "too_long",
                    "length": length,
                    "threshold": self.policy.max_length,
                }),
            ));
        }

        let ch_ratio = chinese_ratio(text);
        if ch_ratio < self.policy.min_chinese_ratio {
            return Err(MoGrabError::content_validation(
                format!(
                    "中文占比过低（{ch_ratio:.2} < {}）",
                    self.policy.min_chinese_ratio
                ),
                json!({
                    "reason": "low_chinese_ratio",
                    "ratio": (ch_ratio * 10000.0).round() / 10000.0,
                    "threshold": self.policy.min_chinese_ratio,
                }),
            ));
        }

        let rep_ratio = max_repeat_ratio(text);
        if rep_ratio > self.policy.max_repeat_line_ratio {
            return Err(MoGrabError::content_validation(
                format!("重复行占比过高（{rep_ratio:.2}），疑似模板页"),
                json!({
                    "reason": "high_repeat_ratio",
                    "ratio": (rep_ratio * 10000.0).round() / 10000.0,
                    "threshold": self.policy.max_repeat_line_ratio,
                }),
            ));
        }

        Ok(())
    }
}

fn chinese_ratio(text: &str) -> f64 {
    let mut total = 0usize;
    let mut cjk = 0usize;
    for ch in text.chars() {
        if ch.is_whitespace() {
            continue;
        }
        total += 1;
        if ('\u{4e00}'..='\u{9fff}').contains(&ch) {
            cjk += 1;
        }
    }
    if total == 0 {
        return 0.0;
    }
    cjk as f64 / total as f64
}

fn max_repeat_ratio(text: &str) -> f64 {
    let lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect();
    if lines.len() < 3 {
        return 0.0;
    }
    let mut counts: HashMap<&str, usize> = HashMap::new();
    for &l in &lines {
        *counts.entry(l).or_insert(0) += 1;
    }
    let repeated: usize = counts.values().filter(|&&c| c > 1).sum();
    repeated as f64 / lines.len() as f64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_content_pipeline_normalizes_and_validates() {
        let pipeline = ContentPipeline::new(None);
        let raw = "  第一段\u{00a0}\u{3000}开始了，这是一段足够长的中文小说正文内容，包含人物对话与场景描写。\n\n请记住本站 www.example.com\n\n  第二段继续展开剧情，字数也足够长，用来验证清洗和规范化管线能够正常通过。";
        let res = pipeline.process(raw, None).unwrap();
        assert!(!res.text.contains("请记住本站"));
        assert!(!res.text.contains('\u{00a0}'));
        assert!(res.word_count > 40);
        assert_eq!(res.content_hash.len(), 32);
    }

    #[test]
    fn test_content_pipeline_rejects_short() {
        let pipeline = ContentPipeline::new(None);
        let err = pipeline.process("太短了", None).unwrap_err();
        assert_eq!(err.code(), "CONTENT_VALIDATION_ERROR");
    }
}
