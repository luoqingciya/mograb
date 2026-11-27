// SPDX-License-Identifier: GPL-3.0-only
//! 正文清洗（文本级）。

use crate::domain::source::CleanSpec;
use regex::Regex;
use std::sync::LazyLock;

static HTML_TAG_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"<[^>]+>").expect("valid HTML_TAG_RE"));
static ZERO_WIDTH_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[\u{200b}-\u{200f}\u{2028}-\u{202f}\u{feff}]").expect("valid ZERO_WIDTH_RE")
});
static CONTROL_CHAR_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]").expect("valid CONTROL_CHAR_RE")
});
static BLANK_LINES_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\n{3,}").expect("valid BLANK_LINES_RE"));
static PSEUDO_SPACE_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[\u{00a0}\u{3000}]").expect("valid PSEUDO_SPACE_RE"));

static DEFAULT_JUNK_LINES: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    vec![
        Regex::new(
            r"^\s*(?:本章未完|请记住本站|手机用户请浏览|天才一秒记住|最新章节|上一章|下一章|返回目录|加入书签|投推荐票)\s*.*$",
        )
        .expect("junk 1"),
        Regex::new(
            r"(?i)^\s*[（(]?\s*(?:www|m)\.[a-z0-9.-]+(?:\.(?:com|net|org|cn|cc|xyz))?\s*[)）]?\s*$",
        )
        .expect("junk 2"),
        Regex::new(r"(?i)^\s*(?:https?://)?[a-z0-9.-]+\.(?:com|net|org|cn|cc|xyz)\s*$")
            .expect("junk 3"),
    ]
});

pub fn clean_text(
    text: &str,
    _spec: Option<&CleanSpec>,
    extra_junk_patterns: Option<&[String]>,
) -> String {
    let mut result = text.to_string();

    if result.contains('<') && result.contains('>') {
        result = HTML_TAG_RE.replace_all(&result, "").into_owned();
    }

    result = result.replace("&nbsp;", " ").replace("&amp;", "&");
    result = PSEUDO_SPACE_RE.replace_all(&result, " ").into_owned();
    result = ZERO_WIDTH_RE.replace_all(&result, "").into_owned();
    result = CONTROL_CHAR_RE.replace_all(&result, "").into_owned();

    let extra_regexes: Vec<Regex> = extra_junk_patterns
        .unwrap_or(&[])
        .iter()
        .filter_map(|raw| Regex::new(raw).ok())
        .collect();

    let kept: Vec<&str> = result
        .split('\n')
        .map(str::trim)
        .filter(|line| {
            !DEFAULT_JUNK_LINES.iter().any(|p| p.is_match(line))
                && !extra_regexes.iter().any(|p| p.is_match(line))
        })
        .collect();

    let joined = kept.join("\n");
    BLANK_LINES_RE
        .replace_all(&joined, "\n\n")
        .trim()
        .to_string()
}
