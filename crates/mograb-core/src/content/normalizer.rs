// SPDX-License-Identifier: GPL-3.0-only
//! 正文规范化、段落切分与字数统计。

use regex::Regex;
use std::sync::LazyLock;

static CRLF_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\r\n?").expect("valid CRLF_RE"));
static INLINE_WS_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[ \t\x0c\x0b]+").expect("valid INLINE_WS_RE"));
static MULTI_BLANK_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\n{3,}").expect("valid MULTI_BLANK_RE"));
static NON_CJK_WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[A-Za-z0-9]+").expect("valid NON_CJK_WORD_RE"));

pub fn normalize_text(text: &str) -> String {
    if text.is_empty() {
        return String::new();
    }

    let step1 = CRLF_RE.replace_all(text, "\n");
    let step2 = step1.replace('\u{3000}', " ");
    let lines: Vec<String> = step2
        .split('\n')
        .map(|line| INLINE_WS_RE.replace_all(line, " ").trim().to_string())
        .collect();
    let joined = lines.join("\n");
    MULTI_BLANK_RE
        .replace_all(&joined, "\n\n")
        .trim()
        .to_string()
}

pub fn split_paragraphs(text: &str) -> Vec<String> {
    let normalized = normalize_text(text);
    if normalized.is_empty() {
        return Vec::new();
    }
    if normalized.contains("\n\n") {
        normalized
            .split("\n\n")
            .map(|p| p.trim().to_string())
            .filter(|p| !p.is_empty())
            .collect()
    } else {
        normalized
            .split('\n')
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty())
            .collect()
    }
}

pub fn count_words(text: &str) -> usize {
    if text.is_empty() {
        return 0;
    }
    let cjk = text
        .chars()
        .filter(|&ch| ('\u{4e00}'..='\u{9fff}').contains(&ch))
        .count();
    let non_cjk = NON_CJK_WORD_RE.find_iter(text).count();
    cjk + non_cjk
}
