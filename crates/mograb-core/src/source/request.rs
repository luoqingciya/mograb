// SPDX-License-Identifier: GPL-3.0-only
//! Request 构造与模板变量替换。

use crate::domain::source::RequestSpec;
use crate::errors::{MoGrabError, MoGrabResult};
use regex::{Captures, Regex};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::sync::LazyLock;

static VAR_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}").expect("valid VAR_RE"));

pub const DEFAULT_USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 MoGrab/0.1";

#[derive(Debug, Clone, Default)]
pub struct TemplateContext {
    pub values: BTreeMap<String, String>,
}

impl TemplateContext {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn from_pairs<'a>(pairs: impl IntoIterator<Item = (&'a str, String)>) -> Self {
        let mut values = BTreeMap::new();
        for (k, v) in pairs {
            values.insert(k.to_string(), v);
        }
        Self { values }
    }

    pub fn insert(&mut self, key: impl Into<String>, value: impl Into<String>) {
        self.values.insert(key.into(), value.into());
    }

    pub fn get(&self, name: &str) -> Option<&str> {
        if let Some(v) = self.values.get(name) {
            return Some(v.as_str());
        }
        if name == "user_agent" {
            return Some(DEFAULT_USER_AGENT);
        }
        None
    }
}

#[derive(Debug, Clone)]
pub struct RenderedRequest {
    pub method: String,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    pub params: Option<BTreeMap<String, String>>,
    pub data: Option<Value>,
    pub cookies: BTreeMap<String, String>,
    pub encoding: Option<String>,
    pub timeout_ms: Option<u64>,
}

pub fn render(template: &str, context: &TemplateContext, strict: bool) -> MoGrabResult<String> {
    let mut missing: Option<String> = None;
    let out = VAR_RE.replace_all(template, |caps: &Captures<'_>| {
        let name = &caps[1];
        match context.get(name) {
            Some(val) => val.to_string(),
            None => {
                if strict && missing.is_none() {
                    missing = Some(name.to_string());
                }
                caps[0].to_string()
            }
        }
    });

    if let Some(name) = missing {
        return Err(MoGrabError::source_execution_with(
            format!("未定义的模板变量: {{{{{name}}}}}"),
            json!({"variable": name, "template": template}),
        ));
    }
    Ok(out.into_owned())
}

pub fn find_variables(template: &str) -> BTreeSet<String> {
    VAR_RE
        .captures_iter(template)
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

pub fn build_request(
    spec: &RequestSpec,
    context: &TemplateContext,
    default_headers: Option<&HashMap<String, String>>,
) -> MoGrabResult<RenderedRequest> {
    let mut headers = BTreeMap::new();
    if let Some(defaults) = default_headers {
        for (k, v) in defaults {
            headers.insert(k.clone(), render(v, context, true)?);
        }
    }
    for (k, v) in &spec.headers {
        headers.insert(k.clone(), render(v, context, true)?);
    }

    let url = render(&spec.url, context, true)?;

    let params = if spec.query.is_empty() {
        None
    } else {
        let mut map = BTreeMap::new();
        for (k, v) in &spec.query {
            map.insert(k.clone(), render(v, context, true)?);
        }
        Some(map)
    };

    let data = match &spec.body {
        None => None,
        Some(Value::String(s)) => Some(Value::String(render(s, context, true)?)),
        Some(Value::Object(map)) => {
            let mut rendered = serde_json::Map::new();
            for (k, v) in map {
                let val_str = match v {
                    Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                rendered.insert(k.clone(), Value::String(render(&val_str, context, true)?));
            }
            Some(Value::Object(rendered))
        }
        Some(other) => Some(other.clone()),
    };

    let mut cookies = BTreeMap::new();
    for (k, v) in &spec.cookies {
        cookies.insert(k.clone(), render(v, context, true)?);
    }

    Ok(RenderedRequest {
        method: spec.method.clone(),
        url,
        headers,
        params,
        data,
        cookies,
        encoding: spec.encoding.clone(),
        timeout_ms: spec.timeout_ms,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_render_strict_and_builtin() {
        let ctx = TemplateContext::from_pairs([("keyword", "三体".to_string())]);
        assert_eq!(
            render("https://example.com?q={{keyword}}", &ctx, true).unwrap(),
            "https://example.com?q=三体"
        );
        assert!(
            render("{{user_agent}}", &ctx, true)
                .unwrap()
                .contains("MoGrab")
        );
        assert!(render("{{nope}}", &ctx, true).is_err());
        assert_eq!(render("{{nope}}", &ctx, false).unwrap(), "{{nope}}");
    }
}
