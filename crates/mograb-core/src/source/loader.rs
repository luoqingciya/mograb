// SPDX-License-Identifier: GPL-3.0-only
//! Source Loader —— YAML <-> SourceSpec。

use crate::domain::source::SourceSpec;
use crate::errors::{MoGrabError, MoGrabResult};
use serde_json::json;
use std::fs;
use std::path::Path;

pub fn load_source_str(yaml_text: &str, origin: &str) -> MoGrabResult<SourceSpec> {
    let mut spec: SourceSpec = serde_yaml_ng::from_str(yaml_text).map_err(|e| {
        let path = e
            .location()
            .map(|loc| format!("line {}, col {}", loc.line(), loc.column()))
            .unwrap_or_default();
        MoGrabError::source_schema_with(
            format!("书源 Schema 校验失败 ({origin})"),
            json!({
                "origin": origin,
                "errors": [{
                    "path": path,
                    "message": e.to_string(),
                    "type": "yaml_or_schema",
                }]
            }),
        )
    })?;
    spec.validate().map_err(|err| {
        if matches!(err, MoGrabError::SourceUnsupported { .. }) {
            err
        } else {
            MoGrabError::source_schema_with(
                format!("书源 Schema 校验失败 ({origin})"),
                json!({
                    "origin": origin,
                    "errors": [{
                        "path": "",
                        "message": err.message(),
                        "type": "validation",
                    }]
                }),
            )
        }
    })?;
    Ok(spec)
}

pub fn load_source_file(path: &Path) -> MoGrabResult<SourceSpec> {
    if !path.is_file() {
        return Err(MoGrabError::source_schema_with(
            format!("书源文件不存在: {}", path.display()),
            json!({"path": path.display().to_string()}),
        ));
    }
    let content = fs::read_to_string(path).map_err(|e| {
        MoGrabError::source_schema_with(
            format!("读取书源失败: {}", path.display()),
            json!({"path": path.display().to_string(), "reason": e.to_string()}),
        )
    })?;
    load_source_str(&content, &path.display().to_string())
}

pub fn dump_source_yaml(spec: &SourceSpec) -> MoGrabResult<String> {
    serde_yaml_ng::to_string(spec)
        .map_err(|e| MoGrabError::source_schema(format!("序列化书源 YAML 失败: {e}")))
}

pub fn write_source_file(spec: &SourceSpec, path: &Path) -> MoGrabResult<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| MoGrabError::storage(e.to_string()))?;
    }
    let yaml = dump_source_yaml(spec)?;
    fs::write(path, yaml).map_err(|e| MoGrabError::storage(e.to_string()))
}
