// SPDX-License-Identifier: GPL-3.0-only
//! Transformer —— 字段值的声明式变换流水线。

use crate::domain::source::{Transform, TransformOp};
use crate::errors::{MoGrabError, MoGrabResult};
use fancy_regex::Regex as FancyRegex;
use regex::Regex;
use std::collections::BTreeMap;
use std::sync::LazyLock;
use url::Url;

static TAG_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"<[^>]+>").expect("valid TAG_RE"));
static WS_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").expect("valid WS_RE"));
static BR_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)<\s*br\s*/?\s*>").expect("valid BR_RE"));
static BLOCK_END_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)</\s*(?:p|div|li|tr|h[1-6]|blockquote|section|article)\s*>")
        .expect("valid BLOCK_END_RE")
});
static URL_SCHEME_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://").expect("valid URL_SCHEME_RE"));
static FILENAME_LIKE_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)^[\w\-.%]+\.(?:x?html?|php\d?|aspx?|jsp|json|xml|txt)$")
        .expect("valid FILENAME_LIKE_RE")
});

fn looks_like_url_ref(value: &str) -> bool {
    let text = value.trim();
    if text.is_empty() || text.chars().any(char::is_whitespace) {
        return false;
    }
    if text.starts_with("//")
        || text.starts_with('/')
        || text.starts_with("./")
        || text.starts_with("../")
    {
        return true;
    }
    if URL_SCHEME_RE.is_match(text) {
        return true;
    }
    if text.contains('/') {
        return true;
    }
    FILENAME_LIKE_RE.is_match(text)
}

fn strip_html(value: &str) -> String {
    let step1 = BR_RE.replace_all(value, "\n");
    let step2 = BLOCK_END_RE.replace_all(&step1, "\n");
    let stripped = TAG_RE.replace_all(&step2, "");
    html_escape::decode_html_entities(&stripped).into_owned()
}

pub fn url_join(base_url: &str, relative: &str) -> MoGrabResult<String> {
    let base = Url::parse(base_url).map_err(|e| {
        MoGrabError::source_execution(format!("url_join base_url 无效 ({base_url:?}): {e}"))
    })?;
    base.join(relative.trim())
        .map(|u| u.to_string())
        .map_err(|e| {
            MoGrabError::source_execution(format!("url_join 拼接失败 ({relative:?}): {e}"))
        })
}

pub fn apply_transforms(
    value: Option<&str>,
    transforms: &[Transform],
    base_url: Option<&str>,
) -> MoGrabResult<Option<String>> {
    let mut current: Option<String> = value.map(str::to_string);
    for t in transforms {
        current = apply_one(current, t, base_url)?;
    }
    Ok(current)
}

pub fn apply_transforms_many(
    rows: Vec<BTreeMap<String, Option<String>>>,
    transforms: &[Transform],
    base_url: Option<&str>,
) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
    if transforms.is_empty() {
        return Ok(rows);
    }
    let mut out = Vec::with_capacity(rows.len());
    for row in rows {
        let mut new_row = BTreeMap::new();
        for (k, v) in row {
            let transformed = apply_transforms(v.as_deref(), transforms, base_url)?;
            new_row.insert(k, transformed);
        }
        out.push(new_row);
    }
    Ok(out)
}

fn apply_one(
    value: Option<String>,
    t: &Transform,
    base_url: Option<&str>,
) -> MoGrabResult<Option<String>> {
    match t.op {
        TransformOp::Trim => Ok(value.map(|v| {
            if v.is_empty() {
                v
            } else {
                v.trim().to_string()
            }
        })),
        TransformOp::NormalizeWhitespace => Ok(value.map(|v| {
            if v.is_empty() {
                v
            } else {
                WS_RE.replace_all(&v, " ").trim().to_string()
            }
        })),
        TransformOp::RemoveHtml => Ok(value.map(|v| if v.is_empty() { v } else { strip_html(&v) })),
        TransformOp::Replace => {
            let (Some(v), Some(pat)) = (&value, &t.pattern) else {
                return Ok(value);
            };
            let rep = t.replacement.as_deref().unwrap_or("");
            Ok(Some(v.replace(pat, rep)))
        }
        TransformOp::RegexReplace => {
            let (Some(v), Some(pat)) = (&value, &t.pattern) else {
                return Ok(value);
            };
            let rep = t.replacement.as_deref().unwrap_or("");
            let re = FancyRegex::new(pat).map_err(|e| {
                MoGrabError::source_execution(format!("regex_replace 正则无效: {e}"))
            })?;
            Ok(Some(re.replace_all(v, rep).into_owned()))
        }
        TransformOp::Prepend => {
            let prefix = t.value.as_deref().unwrap_or("");
            let body = value.as_deref().unwrap_or("");
            Ok(Some(format!("{prefix}{body}")))
        }
        TransformOp::Append => {
            let suffix = t.value.as_deref().unwrap_or("");
            let body = value.as_deref().unwrap_or("");
            Ok(Some(format!("{body}{suffix}")))
        }
        TransformOp::UrlJoin => {
            let Some(ref v) = value else {
                return Ok(value);
            };
            if v.is_empty() || !looks_like_url_ref(v) {
                return Ok(value);
            }
            let base = base_url
                .ok_or_else(|| MoGrabError::source_execution("url_join 需要 base_url 上下文"))?;
            Ok(Some(url_join(base, v)?))
        }
        TransformOp::Default => match value {
            None => Ok(t.value.clone()),
            Some(ref s) if s.is_empty() => Ok(t.value.clone()),
            other => Ok(other),
        },
        TransformOp::Join => Ok(value),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_remove_html_preserves_br_and_block_newlines() {
        let html = "<p>第一段</p><p>第二段<br>第三段<br />第四段</p>";
        let out = apply_transforms(
            Some(html),
            &[Transform::simple(TransformOp::RemoveHtml)],
            None,
        )
        .unwrap()
        .unwrap();
        assert_eq!(out, "第一段\n第二段\n第三段\n第四段\n");
    }

    #[test]
    fn test_url_join_is_conservative() {
        let t = [Transform::simple(TransformOp::UrlJoin)];
        let title = apply_transforms(Some("三体"), &t, Some("https://example.com/search"))
            .unwrap()
            .unwrap();
        assert_eq!(title, "三体");

        let link = apply_transforms(
            Some("/book/1001"),
            &t,
            Some("https://example.com/search?q=x"),
        )
        .unwrap()
        .unwrap();
        assert_eq!(link, "https://example.com/book/1001");
    }
}
