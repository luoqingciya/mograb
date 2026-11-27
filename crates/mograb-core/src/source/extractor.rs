// SPDX-License-Identifier: GPL-3.0-only
//! Extractor —— 统一的提取接口（CSS / XPath / JSONPath / Regex / Attr / Text）。

use crate::domain::source::{ExtractRule, RuleType};
use crate::errors::{MoGrabError, MoGrabResult};
use ego_tree::{NodeId, NodeRef};
use encoding_rs::Encoding;
use fancy_regex::Regex as FancyRegex;
use regex::Regex;
use scraper::{ElementRef, Html, Node as ScraperNode, Selector};
use serde_json::Value;
use serde_json_path::JsonPath;
use std::collections::{BTreeMap, HashSet};
use std::sync::LazyLock;
use sxd_document::Package;
use sxd_document::dom::{Document as SxdDoc, Element as SxdElement};
use sxd_xpath::{Context as XPathContext, Factory as XPathFactory, Value as XPathValue};

static WS_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s+").expect("valid WS_RE"));

#[derive(Debug, Clone)]
pub struct ExtractResult {
    pub values: Vec<String>,
    pub matched: bool,
}

impl ExtractResult {
    pub fn from_values(values: Vec<String>) -> Self {
        let matched = !values.is_empty();
        Self { values, matched }
    }

    pub fn value(&self) -> Option<&str> {
        self.values.first().map(String::as_str)
    }
}

pub struct Document {
    pub raw: Vec<u8>,
    pub encoding: String,
    pub kind: String,
    decoded: Option<String>,
    html: Option<Html>,
    json: Option<Value>,
}

impl Document {
    pub fn new(raw: Vec<u8>, encoding: impl Into<String>, kind: impl Into<String>) -> Self {
        Self {
            raw,
            encoding: encoding.into(),
            kind: kind.into(),
            decoded: None,
            html: None,
            json: None,
        }
    }

    pub fn text(&mut self) -> &str {
        if self.decoded.is_none() {
            let enc = Encoding::for_label(self.encoding.as_bytes()).unwrap_or(encoding_rs::UTF_8);
            let (cow, _, _) = enc.decode(&self.raw);
            self.decoded = Some(cow.into_owned());
        }
        self.decoded.as_deref().unwrap_or("")
    }

    pub fn html_tree(&mut self) -> &Html {
        if self.html.is_none() {
            let text = self.text().to_string();
            self.html = Some(Html::parse_document(&text));
        }
        self.html.as_ref().expect("html initialized")
    }

    pub fn json_value(&mut self) -> MoGrabResult<&Value> {
        if self.json.is_none() {
            let text = self.text().to_string();
            let parsed: Value = serde_json::from_str(&text)
                .map_err(|e| MoGrabError::parse(format!("JSON 解析失败: {e}")))?;
            self.json = Some(parsed);
        }
        Ok(self.json.as_ref().expect("json initialized"))
    }

    /// DOM 级节点清理（`content.clean.remove`）。
    pub fn clean_remove(&mut self, selectors: &[String]) {
        if selectors.is_empty() {
            return;
        }
        // 确保 html 已解析
        let _ = self.html_tree();
        let Some(ref mut html) = self.html else {
            return;
        };
        for sel_str in selectors {
            let Ok(selector) = Selector::parse(sel_str) else {
                continue;
            };
            let ids: Vec<NodeId> = html.select(&selector).map(|el| el.id()).collect();
            for id in ids {
                if let Some(mut node_mut) = html.tree.get_mut(id)
                    && node_mut.parent().is_some()
                {
                    node_mut.detach();
                }
            }
        }
    }
}

pub fn normalize_text(text: &str) -> String {
    WS_RE.replace_all(text, " ").trim().to_string()
}

fn collect_element_text(el: ElementRef<'_>) -> String {
    let mut buf = String::new();
    for text in el.text() {
        buf.push_str(text);
    }
    normalize_text(&buf)
}

fn collect_own_text(el: ElementRef<'_>) -> String {
    let mut buf = String::new();
    for child in el.children() {
        if let ScraperNode::Text(t) = child.value() {
            buf.push_str(&t.text);
        }
    }
    normalize_text(&buf)
}

fn extract_css_from_scope(el: ElementRef<'_>, rule: &ExtractRule) -> MoGrabResult<ExtractResult> {
    let selector = Selector::parse(&rule.expression)
        .map_err(|e| MoGrabError::parse(format!("非法 CSS 选择器 {:?}: {e:?}", rule.expression)))?;

    let mut values = Vec::new();
    for node in el.select(&selector) {
        append_css_node_value(node, rule.attribute.as_deref(), &mut values);
    }
    Ok(ExtractResult::from_values(values))
}

fn extract_css_from_doc(html: &Html, rule: &ExtractRule) -> MoGrabResult<ExtractResult> {
    let selector = Selector::parse(&rule.expression)
        .map_err(|e| MoGrabError::parse(format!("非法 CSS 选择器 {:?}: {e:?}", rule.expression)))?;

    let mut values = Vec::new();
    for node in html.select(&selector) {
        append_css_node_value(node, rule.attribute.as_deref(), &mut values);
    }
    Ok(ExtractResult::from_values(values))
}

fn append_css_node_value(node: ElementRef<'_>, attr: Option<&str>, values: &mut Vec<String>) {
    match attr {
        None | Some("text") => values.push(collect_element_text(node)),
        Some("html") | Some("inner_html") => values.push(node.html()),
        Some("own_text") => values.push(collect_own_text(node)),
        Some(name) => {
            if let Some(val) = node.value().attr(name) {
                values.push(val.to_string());
            }
        }
    }
}

fn extract_attr_from_element(el: ElementRef<'_>, rule: &ExtractRule) -> ExtractResult {
    let values = match rule.expression.as_str() {
        "text" => vec![collect_element_text(el)],
        "own_text" => vec![collect_own_text(el)],
        "html" | "inner_html" => vec![el.html()],
        attr_name => match el.value().attr(attr_name) {
            Some(v) => vec![v.to_string()],
            None => Vec::new(),
        },
    };
    ExtractResult::from_values(values)
}

fn extract_regex_on_str(text: &str, rule: &ExtractRule) -> MoGrabResult<ExtractResult> {
    let re = FancyRegex::new(&rule.expression)
        .map_err(|e| MoGrabError::parse(format!("非法正则 {:?}: {e}", rule.expression)))?;
    let mut values = Vec::new();
    for cap_res in re.captures_iter(text) {
        let caps = cap_res
            .map_err(|e| MoGrabError::parse(format!("正则执行失败 {:?}: {e}", rule.expression)))?;
        if let Some(m) = caps.get(1) {
            values.push(m.as_str().to_string());
        } else if let Some(m) = caps.get(0) {
            values.push(m.as_str().to_string());
        }
    }
    Ok(ExtractResult::from_values(values))
}

fn json_value_to_string(v: &Value) -> Option<String> {
    match v {
        Value::Null => None,
        Value::String(s) => Some(s.clone()),
        Value::Bool(b) => Some(if *b { "True" } else { "False" }.to_string()),
        Value::Number(n) => Some(n.to_string()),
        other => Some(other.to_string()),
    }
}

fn extract_jsonpath_from_value(root: &Value, rule: &ExtractRule) -> MoGrabResult<ExtractResult> {
    let path = JsonPath::parse(&rule.expression)
        .map_err(|e| MoGrabError::parse(format!("非法 JSONPath {:?}: {e}", rule.expression)))?;
    let nodes = path.query(root);
    let values: Vec<String> = nodes
        .iter()
        .filter_map(|v| json_value_to_string(v))
        .collect();
    Ok(ExtractResult::from_values(values))
}

// ---------------------------------------------------------------------------
// HTML5 -> SXD XML 桥接（供 XPath 1.0 求值）
// ---------------------------------------------------------------------------
fn is_valid_xml_char(c: char) -> bool {
    matches!(
        c as u32,
        0x9 | 0xA | 0xD | 0x20..=0xD7FF | 0xE000..=0xFFFD | 0x10000..=0x10FFFF
    )
}

fn sanitize_xml_text(s: &str) -> String {
    if s.chars().all(is_valid_xml_char) {
        s.to_string()
    } else {
        s.chars().filter(|&c| is_valid_xml_char(c)).collect()
    }
}

fn sanitize_xml_name(raw: &str) -> String {
    // 去掉前缀冒号，确保不带命名空间前缀导致 XPath 未绑定前缀报错
    let local = raw.rsplit(':').next().unwrap_or(raw);
    let mut out = String::with_capacity(local.len());
    for (idx, ch) in local.chars().enumerate() {
        let ok = if idx == 0 {
            ch.is_ascii_alphabetic() || ch == '_'
        } else {
            ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.')
        };
        if ok {
            out.push(ch);
        } else {
            if idx == 0 {
                out.push('n');
            }
            out.push('_');
        }
    }
    if out.is_empty() {
        "node".to_string()
    } else {
        out
    }
}

fn create_sxd_element<'d>(doc: &'d SxdDoc<'d>, el: &scraper::node::Element) -> SxdElement<'d> {
    let tag = sanitize_xml_name(el.name());
    let sxd_el = doc.create_element(tag.as_str());
    let mut seen_attrs = HashSet::new();
    for (attr_name, attr_val) in el.attrs() {
        let lower = attr_name.to_lowercase();
        if lower == "xmlns" || lower.starts_with("xmlns:") {
            continue;
        }
        let clean_name = sanitize_xml_name(attr_name);
        if seen_attrs.insert(clean_name.clone()) {
            let clean_val = sanitize_xml_text(attr_val);
            sxd_el.set_attribute_value(clean_name.as_str(), &clean_val);
        }
    }
    sxd_el
}

fn copy_node_to_sxd<'d>(
    src: NodeRef<'_, ScraperNode>,
    doc: &'d SxdDoc<'d>,
    parent: SxdElement<'d>,
) {
    for child in src.children() {
        match child.value() {
            ScraperNode::Element(el) => {
                let sxd_el = create_sxd_element(doc, el);
                parent.append_child(sxd_el);
                copy_node_to_sxd(child, doc, sxd_el);
            }
            ScraperNode::Text(text) => {
                let clean = sanitize_xml_text(&text.text);
                if !clean.is_empty() {
                    let t = doc.create_text(&clean);
                    parent.append_child(t);
                }
            }
            _ => {}
        }
    }
}

fn html_to_sxd_package(html: &Html, scope: Option<NodeId>) -> Package {
    let pkg = Package::new();
    let doc = pkg.as_document();
    match scope.and_then(|id| html.tree.get(id)) {
        Some(node_ref) => {
            if let ScraperNode::Element(el) = node_ref.value() {
                let root_el = create_sxd_element(&doc, el);
                doc.root().append_child(root_el);
                copy_node_to_sxd(node_ref, &doc, root_el);
            } else {
                let root_el = doc.create_element("fragment");
                doc.root().append_child(root_el);
                copy_node_to_sxd(node_ref, &doc, root_el);
            }
        }
        None => {
            for child in html.tree.root().children() {
                if let ScraperNode::Element(el) = child.value() {
                    let root_el = create_sxd_element(&doc, el);
                    doc.root().append_child(root_el);
                    copy_node_to_sxd(child, &doc, root_el);
                }
            }
        }
    }
    pkg
}

fn collect_sxd_element_text(el: SxdElement<'_>, buf: &mut String) {
    for child in el.children() {
        match child {
            sxd_document::dom::ChildOfElement::Element(sub) => collect_sxd_element_text(sub, buf),
            sxd_document::dom::ChildOfElement::Text(t) => buf.push_str(t.text()),
            _ => {}
        }
    }
}

pub fn validate_xpath_syntax(expr: &str) -> Result<(), String> {
    let factory = XPathFactory::new();
    factory
        .build(expr)
        .map(|_| ())
        .map_err(|e| format!("{e:?}"))
}

fn evaluate_xpath_on_package(pkg: &Package, expr: &str) -> MoGrabResult<Vec<String>> {
    let factory = XPathFactory::new();
    let xpath = factory
        .build(expr)
        .map_err(|e| MoGrabError::parse(format!("非法 XPath {:?}: {e:?}", expr)))?
        .ok_or_else(|| MoGrabError::parse(format!("XPath 为空: {expr:?}")))?;

    let context = XPathContext::new();
    let doc = pkg.as_document();
    let root = doc.root();
    let val = xpath
        .evaluate(&context, root)
        .map_err(|e| MoGrabError::parse(format!("XPath 求值失败 {:?}: {e:?}", expr)))?;

    let values = match val {
        XPathValue::Nodeset(nodeset) => nodeset
            .document_order()
            .into_iter()
            .map(|n| match n {
                sxd_xpath::nodeset::Node::Attribute(a) => a.value().trim().to_string(),
                sxd_xpath::nodeset::Node::Text(t) => t.text().trim().to_string(),
                sxd_xpath::nodeset::Node::Element(e) => {
                    let mut buf = String::new();
                    collect_sxd_element_text(e, &mut buf);
                    normalize_text(&buf)
                }
                other => normalize_text(&other.string_value()),
            })
            .collect(),
        XPathValue::String(s) => {
            let trimmed = s.trim();
            if trimmed.is_empty() {
                Vec::new()
            } else {
                vec![trimmed.to_string()]
            }
        }
        XPathValue::Number(n) => {
            if n.fract() == 0.0 {
                vec![format!("{}", n as i64)]
            } else {
                vec![n.to_string()]
            }
        }
        XPathValue::Boolean(b) => vec![if b { "True" } else { "False" }.to_string()],
    };
    Ok(values)
}

fn sxd_element_to_html_string(el: SxdElement<'_>) -> String {
    let mut out = String::new();
    out.push('<');
    out.push_str(el.name().local_part());
    for attr in el.attributes() {
        out.push(' ');
        out.push_str(attr.name().local_part());
        out.push_str("=\"");
        out.push_str(&html_escape::encode_double_quoted_attribute(attr.value()));
        out.push('"');
    }
    out.push('>');
    for child in el.children() {
        match child {
            sxd_document::dom::ChildOfElement::Element(sub) => {
                out.push_str(&sxd_element_to_html_string(sub));
            }
            sxd_document::dom::ChildOfElement::Text(t) => {
                out.push_str(&html_escape::encode_text(t.text()));
            }
            _ => {}
        }
    }
    out.push_str("</");
    out.push_str(el.name().local_part());
    out.push('>');
    out
}

// ---------------------------------------------------------------------------
// 对外接口：extract / extract_one / extract_many
// ---------------------------------------------------------------------------
pub fn extract(document: &mut Document, rule: &ExtractRule) -> MoGrabResult<ExtractResult> {
    match rule.rule_type {
        RuleType::Css => {
            let html = document.html_tree();
            extract_css_from_doc(html, rule)
        }
        RuleType::Xpath => {
            let html = document.html_tree();
            let pkg = html_to_sxd_package(html, None);
            let values = evaluate_xpath_on_package(&pkg, &rule.expression)?;
            Ok(ExtractResult::from_values(values))
        }
        RuleType::Jsonpath => {
            let data = document.json_value()?;
            extract_jsonpath_from_value(data, rule)
        }
        RuleType::Regex => {
            let text = document.text().to_string();
            extract_regex_on_str(&text, rule)
        }
        RuleType::Attr | RuleType::Text => {
            let html = document.html_tree();
            let root = html.root_element();
            Ok(extract_attr_from_element(root, rule))
        }
    }
}

pub fn extract_one(document: &mut Document, rule: &ExtractRule) -> MoGrabResult<Option<String>> {
    let res = extract(document, rule)?;
    Ok(res.value().map(str::to_string))
}

pub fn extract_many(
    document: &mut Document,
    list_rule: &ExtractRule,
    field_rules: &BTreeMap<String, ExtractRule>,
) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
    if list_rule.rule_type == RuleType::Jsonpath {
        return extract_many_json(document, list_rule, field_rules);
    }
    if list_rule.rule_type == RuleType::Xpath {
        return extract_many_xpath(document, list_rule, field_rules);
    }
    extract_many_dom(document, list_rule, field_rules)
}

fn extract_from_scope_element(
    html: &Html,
    el: ElementRef<'_>,
    rule: &ExtractRule,
) -> MoGrabResult<Option<String>> {
    let res = match rule.rule_type {
        RuleType::Css => extract_css_from_scope(el, rule)?,
        RuleType::Attr | RuleType::Text => extract_attr_from_element(el, rule),
        RuleType::Regex => extract_regex_on_str(&el.html(), rule)?,
        RuleType::Xpath => {
            let pkg = html_to_sxd_package(html, Some(el.id()));
            let values = evaluate_xpath_on_package(&pkg, &rule.expression)?;
            ExtractResult::from_values(values)
        }
        RuleType::Jsonpath => {
            let text = collect_element_text(el);
            let val: Value = serde_json::from_str(&text)
                .map_err(|e| MoGrabError::parse(format!("JSON 解析失败: {e}")))?;
            extract_jsonpath_from_value(&val, rule)?
        }
    };
    Ok(res.value().map(str::to_string))
}

fn extract_many_dom(
    document: &mut Document,
    list_rule: &ExtractRule,
    field_rules: &BTreeMap<String, ExtractRule>,
) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
    let selector = Selector::parse(&list_rule.expression).map_err(|e| {
        MoGrabError::parse(format!("非法 CSS 选择器 {:?}: {e:?}", list_rule.expression))
    })?;
    let html = document.html_tree();
    let mut rows = Vec::new();
    for el in html.select(&selector) {
        let mut row = BTreeMap::new();
        for (name, rule) in field_rules {
            let val = extract_from_scope_element(html, el, rule)?;
            row.insert(name.clone(), val);
        }
        rows.push(row);
    }
    Ok(rows)
}

fn extract_many_xpath(
    document: &mut Document,
    list_rule: &ExtractRule,
    field_rules: &BTreeMap<String, ExtractRule>,
) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
    let html = document.html_tree();
    let pkg = html_to_sxd_package(html, None);
    let factory = XPathFactory::new();
    let xpath = factory
        .build(&list_rule.expression)
        .map_err(|e| MoGrabError::parse(format!("非法 XPath {:?}: {e:?}", list_rule.expression)))?
        .ok_or_else(|| MoGrabError::parse(format!("XPath 为空: {:?}", list_rule.expression)))?;
    let context = XPathContext::new();
    let doc = pkg.as_document();
    let val = xpath
        .evaluate(&context, doc.root())
        .map_err(|e| MoGrabError::parse(format!("XPath 求值失败: {e:?}")))?;

    let mut rows = Vec::new();
    if let XPathValue::Nodeset(nodeset) = val {
        for node in nodeset.document_order() {
            if let sxd_xpath::nodeset::Node::Element(el) = node {
                let sub_html = sxd_element_to_html_string(el);
                let mut sub_doc = Html::parse_fragment(&sub_html);
                // parse_fragment wraps in <html>; grab the first element child if present
                let scope_id = sub_doc
                    .root_element()
                    .children()
                    .filter_map(ElementRef::wrap)
                    .next()
                    .map(|e| e.id())
                    .unwrap_or_else(|| sub_doc.root_element().id());
                let _ = &mut sub_doc;
                let scope_el = ElementRef::wrap(sub_doc.tree.get(scope_id).expect("valid scope"))
                    .expect("element");
                let mut row = BTreeMap::new();
                for (name, rule) in field_rules {
                    row.insert(
                        name.clone(),
                        extract_from_scope_element(&sub_doc, scope_el, rule)?,
                    );
                }
                rows.push(row);
            }
        }
    }
    Ok(rows)
}

fn extract_many_json(
    document: &mut Document,
    list_rule: &ExtractRule,
    field_rules: &BTreeMap<String, ExtractRule>,
) -> MoGrabResult<Vec<BTreeMap<String, Option<String>>>> {
    let root = document.json_value()?;
    let path = JsonPath::parse(&list_rule.expression).map_err(|e| {
        MoGrabError::parse(format!("非法 JSONPath {:?}: {e}", list_rule.expression))
    })?;

    let queried = path.query(root);
    let mut items: Vec<&Value> = Vec::new();
    for val in queried.iter() {
        match val {
            Value::Null => continue,
            Value::Array(arr) => items.extend(arr.iter()),
            other => items.push(other),
        }
    }

    let mut rows = Vec::with_capacity(items.len());
    for item in items {
        let mut row = BTreeMap::new();
        let mut raw_cache: Option<String> = None;
        for (name, rule) in field_rules {
            let val = match rule.rule_type {
                RuleType::Jsonpath => extract_jsonpath_from_value(item, rule)?
                    .value()
                    .map(str::to_string),
                RuleType::Regex => {
                    let s = raw_cache.get_or_insert_with(|| item.to_string());
                    extract_regex_on_str(s, rule)?.value().map(str::to_string)
                }
                _ => {
                    let s = raw_cache.get_or_insert_with(|| item.to_string());
                    let mut sub = Document::new(s.as_bytes().to_vec(), "utf-8", "json");
                    extract_one(&mut sub, rule)?
                }
            };
            row.insert(name.clone(), val);
        }
        rows.push(row);
    }
    Ok(rows)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_css_xpath_regex_jsonpath() {
        let html = r#"<html><body><div id="content"><p>第一段</p><p>第二段</p><script>bad()</script></div><a href="/book/1">书名</a></body></html>"#;
        let mut doc = Document::new(html.as_bytes().to_vec(), "utf-8", "html");
        doc.clean_remove(&["script".to_string()]);

        let body_html = extract_one(&mut doc, &ExtractRule::parse("#content@html").unwrap())
            .unwrap()
            .unwrap();
        assert!(!body_html.contains("bad()"));
        assert!(body_html.contains("第一段"));

        let xp = extract_one(&mut doc, &ExtractRule::parse("xpath://a/@href").unwrap())
            .unwrap()
            .unwrap();
        assert_eq!(xp, "/book/1");

        let re_val = extract_one(
            &mut doc,
            &ExtractRule::parse(r#"regex:href="([^"]+)""#).unwrap(),
        )
        .unwrap()
        .unwrap();
        assert_eq!(re_val, "/book/1");
    }

    #[test]
    fn test_jsonpath_list_drilldown() {
        let json_str =
            r#"{"data":{"list":[{"title":"三体","id":101},{"title":"球状闪电","id":102}]}}"#;
        let mut doc = Document::new(json_str.as_bytes().to_vec(), "utf-8", "json");
        let list_rule = ExtractRule::parse("jsonpath:$.data.list").unwrap();
        let mut fields = BTreeMap::new();
        fields.insert(
            "title".into(),
            ExtractRule::parse("jsonpath:$.title").unwrap(),
        );
        fields.insert("id".into(), ExtractRule::parse("jsonpath:$.id").unwrap());
        let rows = extract_many(&mut doc, &list_rule, &fields).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].get("title").unwrap().as_deref(), Some("三体"));
        assert_eq!(rows[1].get("id").unwrap().as_deref(), Some("102"));
    }
}
