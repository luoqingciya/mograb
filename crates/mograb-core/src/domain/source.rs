// SPDX-License-Identifier: GPL-3.0-only
//! Source 领域模型 —— MoGrab Source Specification v1。

use super::enums::{HealthStatus, SourceCapability};
use crate::errors::{MoGrabError, MoGrabResult};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::de::{self, MapAccess, Visitor};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::fmt;
use std::sync::LazyLock;

pub const SPEC_VERSION: i64 = 1;

pub static SOURCE_ID_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$").expect("valid SOURCE_ID_RE")
});

pub static SEMVER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
        .expect("valid SEMVER_RE")
});

// ---------------------------------------------------------------------------
// Transform
// ---------------------------------------------------------------------------
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TransformOp {
    Trim,
    Replace,
    RegexReplace,
    Join,
    Prepend,
    Append,
    UrlJoin,
    Default,
    RemoveHtml,
    NormalizeWhitespace,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Transform {
    pub op: TransformOp,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pattern: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replacement: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub separator: Option<String>,
}

impl Transform {
    pub fn simple(op: TransformOp) -> Self {
        Self {
            op,
            pattern: None,
            replacement: None,
            value: None,
            separator: None,
        }
    }

    fn validate_params(&self) -> Result<(), String> {
        if self.op == TransformOp::RegexReplace && self.pattern.as_deref().unwrap_or("").is_empty()
        {
            return Err("regex_replace 需要 pattern 参数".to_string());
        }
        if self.op == TransformOp::Replace && self.pattern.is_none() {
            return Err("replace 需要 pattern 参数".to_string());
        }
        Ok(())
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTransformObj {
    op: TransformOp,
    #[serde(default)]
    pattern: Option<String>,
    #[serde(default)]
    replacement: Option<String>,
    #[serde(default)]
    value: Option<String>,
    #[serde(default)]
    separator: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RawTransformParams {
    #[serde(default)]
    pattern: Option<String>,
    #[serde(default)]
    replacement: Option<String>,
    #[serde(default)]
    value: Option<String>,
    #[serde(default)]
    separator: Option<String>,
}

impl<'de> Deserialize<'de> for Transform {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = Value::deserialize(deserializer)?;
        let transform = match raw {
            Value::String(s) => {
                let op: TransformOp =
                    serde_json::from_value(Value::String(s)).map_err(de::Error::custom)?;
                Transform::simple(op)
            }
            Value::Object(ref map) if !map.contains_key("op") && map.len() == 1 => {
                let (key, params) = map.iter().next().expect("len == 1");
                let op: TransformOp = serde_json::from_value(Value::String(key.clone()))
                    .map_err(de::Error::custom)?;
                match params {
                    Value::Object(_) => {
                        let p: RawTransformParams =
                            serde_json::from_value(params.clone()).map_err(de::Error::custom)?;
                        Transform {
                            op,
                            pattern: p.pattern,
                            replacement: p.replacement,
                            value: p.value,
                            separator: p.separator,
                        }
                    }
                    Value::String(v) => Transform {
                        op,
                        pattern: None,
                        replacement: None,
                        value: Some(v.clone()),
                        separator: None,
                    },
                    Value::Null => Transform::simple(op),
                    other => Transform {
                        op,
                        pattern: None,
                        replacement: None,
                        value: Some(other.to_string()),
                        separator: None,
                    },
                }
            }
            Value::Object(_) => {
                let obj: RawTransformObj =
                    serde_json::from_value(raw).map_err(de::Error::custom)?;
                Transform {
                    op: obj.op,
                    pattern: obj.pattern,
                    replacement: obj.replacement,
                    value: obj.value,
                    separator: obj.separator,
                }
            }
            _ => return Err(de::Error::custom("transform 必须是字符串或映射")),
        };
        transform.validate_params().map_err(de::Error::custom)?;
        Ok(transform)
    }
}

// ---------------------------------------------------------------------------
// ExtractRule
// ---------------------------------------------------------------------------
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuleType {
    Css,
    Xpath,
    Jsonpath,
    Regex,
    Attr,
    Text,
}

impl RuleType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Css => "css",
            Self::Xpath => "xpath",
            Self::Jsonpath => "jsonpath",
            Self::Regex => "regex",
            Self::Attr => "attr",
            Self::Text => "text",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExtractRule {
    pub rule_type: RuleType,
    pub expression: String,
    pub attribute: Option<String>,
}

impl ExtractRule {
    pub fn parse(raw: &str) -> Result<Self, String> {
        let text = raw.trim();
        if text.is_empty() {
            return Err("提取规则不能为空".to_string());
        }

        let lowered = text.to_lowercase();
        for (prefix, rule_type) in [
            ("xpath:", RuleType::Xpath),
            ("jsonpath:", RuleType::Jsonpath),
            ("regex:", RuleType::Regex),
        ] {
            if lowered.starts_with(prefix) {
                return Ok(Self {
                    rule_type,
                    expression: text[prefix.len()..].to_string(),
                    attribute: None,
                });
            }
        }

        if let Some(rest) = text.strip_prefix('@') {
            return Ok(Self {
                rule_type: RuleType::Attr,
                expression: rest.to_string(),
                attribute: None,
            });
        }

        if let Some((selector, attr)) = text.rsplit_once('@')
            && !selector.is_empty()
        {
            return Ok(Self {
                rule_type: RuleType::Css,
                expression: selector.to_string(),
                attribute: Some(attr.to_string()),
            });
        }

        Ok(Self {
            rule_type: RuleType::Css,
            expression: text.to_string(),
            attribute: None,
        })
    }

    pub fn raw(&self) -> String {
        match self.rule_type {
            RuleType::Attr => format!("@{}", self.expression),
            RuleType::Css => match &self.attribute {
                Some(attr) if !attr.is_empty() => format!("{}@{}", self.expression, attr),
                _ => self.expression.clone(),
            },
            _ => format!("{}:{}", self.rule_type.as_str(), self.expression),
        }
    }
}

impl Serialize for ExtractRule {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.raw())
    }
}

impl<'de> Deserialize<'de> for ExtractRule {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct RuleVisitor;

        impl<'de> Visitor<'de> for RuleVisitor {
            type Value = ExtractRule;

            fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str("提取规则字符串或结构化规则对象")
            }

            fn visit_str<E: de::Error>(self, value: &str) -> Result<ExtractRule, E> {
                ExtractRule::parse(value).map_err(de::Error::custom)
            }

            fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<ExtractRule, M::Error> {
                #[derive(Deserialize)]
                #[serde(deny_unknown_fields)]
                struct Obj {
                    #[serde(rename = "type")]
                    rule_type: RuleType,
                    expression: String,
                    #[serde(default)]
                    attribute: Option<String>,
                }
                let val = serde_json::Value::deserialize(de::value::MapAccessDeserializer::new(
                    &mut map,
                ))?;
                let obj: Obj = serde_json::from_value(val).map_err(de::Error::custom)?;
                Ok(ExtractRule {
                    rule_type: obj.rule_type,
                    expression: obj.expression,
                    attribute: obj.attribute,
                })
            }
        }

        deserializer.deserialize_any(RuleVisitor)
    }
}

// ---------------------------------------------------------------------------
// Request / Response
// ---------------------------------------------------------------------------
fn default_method() -> String {
    "GET".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RequestSpec {
    #[serde(default = "default_method")]
    pub method: String,
    pub url: String,
    #[serde(default)]
    pub headers: BTreeMap<String, String>,
    #[serde(default)]
    pub query: BTreeMap<String, String>,
    #[serde(default)]
    pub body: Option<Value>,
    #[serde(default)]
    pub cookies: BTreeMap<String, String>,
    #[serde(default)]
    pub encoding: Option<String>,
    #[serde(default)]
    pub timeout_ms: Option<u64>,
}

impl RequestSpec {
    pub fn validate(&mut self) -> Result<(), String> {
        self.method = self.method.to_uppercase();
        if self.method != "GET" && self.method != "POST" {
            return Err(format!(
                "不支持的请求方法: {}（仅支持 GET | POST）",
                self.method
            ));
        }
        if let Some(t) = self.timeout_ms
            && !(100..=120_000).contains(&t)
        {
            return Err(format!("request.timeout_ms 超出范围 [100, 120000]: {t}"));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ResponseFormat {
    #[default]
    Html,
    Json,
    Text,
}

impl ResponseFormat {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Html => "html",
            Self::Json => "json",
            Self::Text => "text",
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResponseSpec {
    #[serde(default)]
    pub format: ResponseFormat,
}

// ---------------------------------------------------------------------------
// Capability Specs
// ---------------------------------------------------------------------------
fn default_max_pages() -> usize {
    20
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PaginationSpec {
    pub next: ExtractRule,
    #[serde(default = "default_max_pages")]
    pub max_pages: usize,
}

impl PaginationSpec {
    pub fn validate(&self) -> Result<(), String> {
        if !(2..=200).contains(&self.max_pages) {
            return Err(format!(
                "paginate.max_pages 超出范围 [2, 200]: {}",
                self.max_pages
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ResultSpec {
    pub list: ExtractRule,
    #[serde(default)]
    pub fields: BTreeMap<String, ExtractRule>,
    #[serde(default)]
    pub reverse: bool,
    #[serde(default)]
    pub paginate: Option<PaginationSpec>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchSpec {
    pub request: RequestSpec,
    #[serde(default)]
    pub response: ResponseSpec,
    pub result: ResultSpec,
    #[serde(default)]
    pub transform: Vec<Transform>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BookSpec {
    pub request: RequestSpec,
    #[serde(default)]
    pub response: ResponseSpec,
    #[serde(default)]
    pub fields: BTreeMap<String, ExtractRule>,
    #[serde(default)]
    pub transform: Vec<Transform>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChapterSpec {
    pub request: RequestSpec,
    #[serde(default)]
    pub response: ResponseSpec,
    pub result: ResultSpec,
    #[serde(default)]
    pub transform: Vec<Transform>,
}

fn default_clean_remove() -> Vec<String> {
    vec!["script".to_string(), "style".to_string()]
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CleanSpec {
    #[serde(default = "default_clean_remove")]
    pub remove: Vec<String>,
}

impl Default for CleanSpec {
    fn default() -> Self {
        Self {
            remove: default_clean_remove(),
        }
    }
}

fn deserialize_content_body<'de, D>(deserializer: D) -> Result<ExtractRule, D::Error>
where
    D: Deserializer<'de>,
{
    let val = Value::deserialize(deserializer)?;
    match val {
        Value::String(s) => ExtractRule::parse(&s).map_err(de::Error::custom),
        Value::Object(map) => {
            let selector = map
                .get("selector")
                .and_then(|v| v.as_str())
                .ok_or_else(|| de::Error::custom("content.body 使用字典写法时必须提供 selector"))?;
            ExtractRule::parse(selector).map_err(de::Error::custom)
        }
        _ => Err(de::Error::custom(
            "content.body 必须是规则字符串或包含 selector 的映射",
        )),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ContentSpec {
    pub request: RequestSpec,
    #[serde(default)]
    pub response: ResponseSpec,
    #[serde(deserialize_with = "deserialize_content_body")]
    pub body: ExtractRule,
    #[serde(default)]
    pub clean: CleanSpec,
    #[serde(default)]
    pub transform: Vec<Transform>,
}

// ---------------------------------------------------------------------------
// Network & Permissions
// ---------------------------------------------------------------------------
fn default_concurrency() -> usize {
    2
}
fn default_interval_ms() -> u64 {
    500
}
fn default_timeout_ms() -> u64 {
    15_000
}
fn default_retry() -> usize {
    3
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NetworkPolicy {
    #[serde(default = "default_concurrency")]
    pub concurrency: usize,
    #[serde(default = "default_interval_ms")]
    pub request_interval_ms: u64,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
    #[serde(default = "default_retry")]
    pub retry: usize,
    #[serde(default)]
    pub headers: HashMap<String, String>,
}

impl Default for NetworkPolicy {
    fn default() -> Self {
        Self {
            concurrency: default_concurrency(),
            request_interval_ms: default_interval_ms(),
            timeout_ms: default_timeout_ms(),
            retry: default_retry(),
            headers: HashMap::new(),
        }
    }
}

impl NetworkPolicy {
    pub fn validate(&self) -> Result<(), String> {
        if !(1..=32).contains(&self.concurrency) {
            return Err(format!(
                "network.concurrency 超出范围 [1, 32]: {}",
                self.concurrency
            ));
        }
        if self.request_interval_ms > 60_000 {
            return Err(format!(
                "network.request_interval_ms 超出范围 [0, 60000]: {}",
                self.request_interval_ms
            ));
        }
        if !(100..=120_000).contains(&self.timeout_ms) {
            return Err(format!(
                "network.timeout_ms 超出范围 [100, 120000]: {}",
                self.timeout_ms
            ));
        }
        if self.retry > 10 {
            return Err(format!("network.retry 超出范围 [0, 10]: {}", self.retry));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Permissions {
    #[serde(default)]
    pub network: Vec<String>,
    #[serde(default)]
    pub cookies: bool,
    #[serde(default)]
    pub filesystem: bool,
    #[serde(default)]
    pub script: bool,
}

impl Permissions {
    pub fn validate(&self) -> Result<(), String> {
        if self.script {
            return Err("v1 不允许书源声明 script 权限（禁止任意代码执行）".to_string());
        }
        if self.filesystem {
            return Err("v1 不允许书源声明 filesystem 权限".to_string());
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// SourceSpec & InstalledSource
// ---------------------------------------------------------------------------
fn default_spec_version() -> i64 {
    SPEC_VERSION
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceSpec {
    #[serde(default = "default_spec_version")]
    pub spec_version: i64,
    pub id: String,
    pub name: String,
    pub version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub homepage: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repository: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub license: Option<String>,
    #[serde(default)]
    pub authors: Vec<String>,
    #[serde(default)]
    pub capabilities: Vec<SourceCapability>,
    #[serde(default)]
    pub network: NetworkPolicy,
    #[serde(default)]
    pub permissions: Permissions,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub search: Option<SearchSpec>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub book: Option<BookSpec>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub chapters: Option<ChapterSpec>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content: Option<ContentSpec>,
    #[serde(default)]
    pub transforms: Vec<Transform>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub engine_min_version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub engine_max_version: Option<String>,
}

impl SourceSpec {
    pub fn validate(&mut self) -> MoGrabResult<()> {
        if self.spec_version != SPEC_VERSION {
            return Err(MoGrabError::source_unsupported(format!(
                "不支持的 Source Specification 版本: {}（当前引擎支持 {SPEC_VERSION}）",
                self.spec_version
            )));
        }

        self.id = self.id.trim().to_string();
        self.name = self.name.trim().to_string();
        self.version = self.version.trim().to_string();

        if !SOURCE_ID_RE.is_match(&self.id) {
            return Err(MoGrabError::source_schema(format!(
                "非法书源 ID: {:?}（要求小写字母开头，仅含 a-z0-9-_）",
                self.id
            )));
        }
        if !SEMVER_RE.is_match(&self.version) {
            return Err(MoGrabError::source_schema(format!(
                "非法版本号: {:?}（要求语义化版本，如 1.0.0）",
                self.version
            )));
        }

        if let Ok(engine_ver) = semver::Version::parse(env!("CARGO_PKG_VERSION")) {
            if let Some(ref min_s) = self.engine_min_version {
                let min_v = semver::Version::parse(min_s.trim()).map_err(|e| {
                    MoGrabError::source_schema(format!("非法 engine_min_version {min_s:?}: {e}"))
                })?;
                if engine_ver < min_v {
                    return Err(MoGrabError::source_unsupported(format!(
                        "书源要求引擎版本 >= {min_v}，当前为 {engine_ver}"
                    )));
                }
            }
            if let Some(ref max_s) = self.engine_max_version {
                let max_v = semver::Version::parse(max_s.trim()).map_err(|e| {
                    MoGrabError::source_schema(format!("非法 engine_max_version {max_s:?}: {e}"))
                })?;
                if engine_ver >= max_v {
                    return Err(MoGrabError::source_unsupported(format!(
                        "书源兼容最高引擎版本 < {max_v}，当前为 {engine_ver}"
                    )));
                }
            }
        }

        self.network
            .validate()
            .map_err(MoGrabError::source_schema)?;
        self.permissions
            .validate()
            .map_err(MoGrabError::source_schema)?;

        if let Some(ref mut s) = self.search {
            s.request.validate().map_err(MoGrabError::source_schema)?;
            if let Some(ref p) = s.result.paginate {
                p.validate().map_err(MoGrabError::source_schema)?;
            }
        }
        if let Some(ref mut b) = self.book {
            b.request.validate().map_err(MoGrabError::source_schema)?;
        }
        if let Some(ref mut c) = self.chapters {
            c.request.validate().map_err(MoGrabError::source_schema)?;
            if let Some(ref p) = c.result.paginate {
                p.validate().map_err(MoGrabError::source_schema)?;
            }
        }
        if let Some(ref mut c) = self.content {
            c.request.validate().map_err(MoGrabError::source_schema)?;
        }

        let pairs = [
            (SourceCapability::Search, self.search.is_some()),
            (SourceCapability::Book, self.book.is_some()),
            (SourceCapability::Chapters, self.chapters.is_some()),
            (SourceCapability::Content, self.content.is_some()),
        ];
        for (cap, provided) in pairs {
            let declared = self.capabilities.contains(&cap);
            if declared && !provided {
                return Err(MoGrabError::source_schema(format!(
                    "声明了能力 {} 但未提供对应规格",
                    cap.as_str()
                )));
            }
            if provided && !declared {
                return Err(MoGrabError::source_schema(format!(
                    "提供了 {} 规格但未在 capabilities 中声明",
                    cap.as_str()
                )));
            }
        }

        Ok(())
    }

    pub fn supports(&self, capability: SourceCapability) -> bool {
        self.capabilities.contains(&capability)
    }

    pub fn qualified_id(&self) -> String {
        format!("{}@{}", self.id, self.version)
    }
}

#[derive(Debug, Clone)]
pub struct InstalledSource {
    pub spec: SourceSpec,
    pub enabled: bool,
    pub health: HealthStatus,
    pub installed_version: String,
    pub previous_version: Option<String>,
    pub installed_at: Option<DateTime<Utc>>,
    pub updated_at: Option<DateTime<Utc>>,
}

impl InstalledSource {
    pub fn id(&self) -> &str {
        &self.spec.id
    }

    pub fn is_usable(&self) -> bool {
        self.enabled
            && !matches!(
                self.health,
                HealthStatus::Broken | HealthStatus::Unsupported
            )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_rule_parse_roundtrip() {
        let cases = [
            (".book-item", RuleType::Css, ".book-item", None),
            ("a@href", RuleType::Css, "a", Some("href")),
            ("div@html", RuleType::Css, "div", Some("html")),
            ("@text", RuleType::Attr, "text", None),
            ("@href", RuleType::Attr, "href", None),
            (
                "xpath://div[@id='c']",
                RuleType::Xpath,
                "//div[@id='c']",
                None,
            ),
            (
                "jsonpath:$.data[*].title",
                RuleType::Jsonpath,
                "$.data[*].title",
                None,
            ),
            (r"regex:第(\d+)章", RuleType::Regex, r"第(\d+)章", None),
        ];
        for (raw, rt, expr, attr) in cases {
            let parsed = ExtractRule::parse(raw).unwrap();
            assert_eq!(parsed.rule_type, rt);
            assert_eq!(parsed.expression, expr);
            assert_eq!(parsed.attribute.as_deref(), attr);
            assert_eq!(parsed.raw(), raw);
        }
    }

    #[test]
    fn test_transform_deserialization() {
        let yaml = r#"
- trim
- normalize_whitespace
- regex_replace:
    pattern: "\\s+"
    replacement: " "
- default: "N/A"
"#;
        let items: Vec<Transform> = serde_yaml_ng::from_str(yaml).unwrap();
        assert_eq!(items.len(), 4);
        assert_eq!(items[0].op, TransformOp::Trim);
        assert_eq!(items[2].op, TransformOp::RegexReplace);
        assert_eq!(items[2].pattern.as_deref(), Some("\\s+"));
        assert_eq!(items[3].op, TransformOp::Default);
        assert_eq!(items[3].value.as_deref(), Some("N/A"));
    }

    #[test]
    fn test_example_source_deserializes_and_validates() {
        let raw = include_str!("../../../../tests/fixtures/example-source/source.yaml");
        let mut spec: SourceSpec = serde_yaml_ng::from_str(raw).unwrap();
        spec.validate().unwrap();
        assert_eq!(spec.id, "example");
        assert!(spec.supports(SourceCapability::Search));
        assert!(spec.supports(SourceCapability::Content));
    }
}
