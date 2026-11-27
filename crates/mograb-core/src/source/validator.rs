// SPDX-License-Identifier: GPL-3.0-only
//! Source Validator / Linter —— 语义校验。

use super::extractor::validate_xpath_syntax;
use super::request::find_variables;
use crate::domain::source::{ExtractRule, RuleType, SourceSpec};
use regex::Regex;
use scraper::Selector;
use serde::Serialize;
use serde_json::{Value, json};
use std::collections::BTreeSet;
use std::sync::LazyLock;

static HOST_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[a-zA-Z]+://([^/?#]+)").expect("valid HOST_RE"));

const KNOWN_VARIABLES: &[&str] = &[
    "keyword",
    "page",
    "user_agent",
    "book.url",
    "book.id",
    "book.title",
    "chapter.url",
    "chapter.index",
    "chapter.id",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Error,
    Warning,
    Info,
}

impl Severity {
    pub fn as_upper(&self) -> &'static str {
        match self {
            Self::Error => "ERROR",
            Self::Warning => "WARNING",
            Self::Info => "INFO",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Diagnostic {
    pub severity: Severity,
    pub path: String,
    pub message: String,
    pub hint: Option<String>,
}

impl Diagnostic {
    pub fn format(&self) -> String {
        let head = format!(
            "[{}] {}: {}",
            self.severity.as_upper(),
            self.path,
            self.message
        );
        match &self.hint {
            Some(h) => format!("{head}\n    → {h}"),
            None => head,
        }
    }
}

#[derive(Debug, Clone)]
pub struct LintReport {
    pub source_id: String,
    pub diagnostics: Vec<Diagnostic>,
}

impl LintReport {
    pub fn errors(&self) -> Vec<&Diagnostic> {
        self.diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Error)
            .collect()
    }

    pub fn warnings(&self) -> Vec<&Diagnostic> {
        self.diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Warning)
            .collect()
    }

    pub fn is_ready(&self) -> bool {
        !self
            .diagnostics
            .iter()
            .any(|d| d.severity == Severity::Error)
    }

    pub fn to_json_value(&self) -> Value {
        let ready = self.is_ready();
        json!({
            "source_id": self.source_id,
            "schema": if ready { "PASS" } else { "FAIL" },
            "errors": self.errors().into_iter().map(|d| d.format()).collect::<Vec<_>>(),
            "warnings": self.warnings().into_iter().map(|d| d.format()).collect::<Vec<_>>(),
            "result": if ready { "READY" } else { "BROKEN" },
        })
    }
}

pub fn lint(source: &SourceSpec) -> LintReport {
    let mut report = LintReport {
        source_id: source.id.clone(),
        diagnostics: Vec::new(),
    };

    check_selectors(source, &mut report);
    check_templates(source, &mut report);
    check_permissions(source, &mut report);
    check_clean_rules(source, &mut report);
    check_optional_fields(source, &mut report);

    report
}

fn iter_rules(source: &SourceSpec) -> Vec<(String, &ExtractRule)> {
    let mut rules = Vec::new();
    if let Some(ref s) = source.search {
        rules.push(("search.result.list".to_string(), &s.result.list));
        for (name, rule) in &s.result.fields {
            rules.push((format!("search.result.fields.{name}"), rule));
        }
        if let Some(ref p) = s.result.paginate {
            rules.push(("search.result.paginate.next".to_string(), &p.next));
        }
    }
    if let Some(ref b) = source.book {
        for (name, rule) in &b.fields {
            rules.push((format!("book.fields.{name}"), rule));
        }
    }
    if let Some(ref c) = source.chapters {
        rules.push(("chapters.result.list".to_string(), &c.result.list));
        for (name, rule) in &c.result.fields {
            rules.push((format!("chapters.result.fields.{name}"), rule));
        }
        if let Some(ref p) = c.result.paginate {
            rules.push(("chapters.result.paginate.next".to_string(), &p.next));
        }
    }
    if let Some(ref c) = source.content {
        rules.push(("content.body".to_string(), &c.body));
    }
    rules
}

fn check_selectors(source: &SourceSpec, report: &mut LintReport) {
    for (path, rule) in iter_rules(source) {
        match rule.rule_type {
            RuleType::Css => {
                if let Err(e) = Selector::parse(&rule.expression) {
                    report.diagnostics.push(Diagnostic {
                        severity: Severity::Error,
                        path,
                        message: format!("非法 CSS 选择器: {:?} ({e:?})", rule.expression),
                        hint: Some("检查括号/引号是否闭合，或改用 xpath: 前缀".to_string()),
                    });
                }
            }
            RuleType::Xpath => {
                if let Err(e) = validate_xpath_syntax(&rule.expression) {
                    report.diagnostics.push(Diagnostic {
                        severity: Severity::Error,
                        path,
                        message: format!("非法 XPath: {:?} ({e})", rule.expression),
                        hint: Some("检查 xpath 表达式语法".to_string()),
                    });
                }
            }
            _ => {}
        }
    }
}

fn check_templates(source: &SourceSpec, report: &mut LintReport) {
    let mut templates: Vec<(String, &str)> = Vec::new();
    let specs = [
        ("search", source.search.as_ref().map(|s| &s.request)),
        ("book", source.book.as_ref().map(|b| &b.request)),
        ("chapters", source.chapters.as_ref().map(|c| &c.request)),
        ("content", source.content.as_ref().map(|c| &c.request)),
    ];
    for (name, req_opt) in specs {
        let Some(req) = req_opt else { continue };
        templates.push((format!("{name}.request.url"), &req.url));
        for (k, v) in &req.headers {
            templates.push((format!("{name}.request.headers.{k}"), v));
        }
        for (k, v) in &req.query {
            templates.push((format!("{name}.request.query.{k}"), v));
        }
    }

    let known: BTreeSet<&str> = KNOWN_VARIABLES.iter().copied().collect();
    let hint_vars = KNOWN_VARIABLES.join(", ");

    for (path, tpl) in templates {
        for name in find_variables(tpl) {
            if known.contains(name.as_str()) || name.starts_with("config.") {
                continue;
            }
            report.diagnostics.push(Diagnostic {
                severity: Severity::Error,
                path: path.clone(),
                message: format!("未定义的模板变量: {{{{{name}}}}}"),
                hint: Some(format!("可用变量: {hint_vars}")),
            });
        }
    }
}

fn extract_host(url_template: &str) -> Option<String> {
    if url_template.contains("{{") {
        return None;
    }
    let caps = HOST_RE.captures(url_template)?;
    let authority = caps.get(1)?.as_str();
    let host = authority.split(':').next()?.to_lowercase();
    Some(host)
}

fn check_permissions(source: &SourceSpec, report: &mut LintReport) {
    if source.permissions.network.is_empty() {
        report.diagnostics.push(Diagnostic {
            severity: Severity::Warning,
            path: "permissions.network".to_string(),
            message: "未声明允许访问的域名".to_string(),
            hint: Some("建议显式列出书源访问的域名，便于用户审阅".to_string()),
        });
        return;
    }

    let urls = [
        (
            "search",
            source.search.as_ref().map(|s| s.request.url.as_str()),
        ),
        ("book", source.book.as_ref().map(|b| b.request.url.as_str())),
        (
            "chapters",
            source.chapters.as_ref().map(|c| c.request.url.as_str()),
        ),
        (
            "content",
            source.content.as_ref().map(|c| c.request.url.as_str()),
        ),
    ];

    for (name, url_opt) in urls {
        let Some(url_tpl) = url_opt else { continue };
        if let Some(host) = extract_host(url_tpl) {
            let allowed = source
                .permissions
                .network
                .iter()
                .any(|a| host.ends_with(a.as_str()));
            if !allowed {
                report.diagnostics.push(Diagnostic {
                    severity: Severity::Error,
                    path: format!("{name}.request.url"),
                    message: format!("域名 {host} 不在 permissions.network 白名单中"),
                    hint: Some(format!("将该域名加入 permissions.network: {host}")),
                });
            }
        }
    }
}

fn check_clean_rules(source: &SourceSpec, report: &mut LintReport) {
    let Some(ref content) = source.content else {
        return;
    };
    for noisy in ["script", "style"] {
        if !content.clean.remove.iter().any(|r| r == noisy) {
            report.diagnostics.push(Diagnostic {
                severity: Severity::Warning,
                path: "content.clean.remove".to_string(),
                message: format!("未移除常见的 {noisy} 节点"),
                hint: Some(format!("在 content.clean.remove 中加入 {noisy:?}")),
            });
        }
    }
}

fn check_optional_fields(source: &SourceSpec, report: &mut LintReport) {
    let Some(ref search) = source.search else {
        return;
    };
    for required in ["title", "url"] {
        if !search.result.fields.contains_key(required) {
            report.diagnostics.push(Diagnostic {
                severity: Severity::Error,
                path: "search.result.fields".to_string(),
                message: format!("搜索结果缺少必需字段 {required:?}"),
                hint: Some(format!("补充 search.result.fields.{required}")),
            });
        }
    }
    if !search.result.fields.contains_key("author") {
        report.diagnostics.push(Diagnostic {
            severity: Severity::Warning,
            path: "search.result.fields.author".to_string(),
            message: "搜索结果未提供 author 字段".to_string(),
            hint: Some("作者信息将留空".to_string()),
        });
    }
}
