// SPDX-License-Identifier: GPL-3.0-only
//! 本地 REST API 与 SSE 客户端（供 `task` / `server` 等命令调用）。

use crate::common::{
    CliExit, EXIT_ERROR, EXIT_NETWORK, EXIT_NOT_FOUND, EXIT_USAGE, EXIT_VALIDATION, fail_msg,
};
use futures::StreamExt;
use mograb_core::config::{AppSettings, ensure_token, get_paths, load_settings};
use reqwest::Method;
use serde_json::{Map, Value};
use std::time::Duration;

pub struct LocalApiClient {
    pub base_url: String,
    pub token: String,
    client: reqwest::Client,
}

impl LocalApiClient {
    pub fn from_config(json_mode: bool) -> Result<Self, CliExit> {
        let paths = get_paths(None);
        let settings: AppSettings = load_settings(Some(&paths.config_file)).unwrap_or_default();
        let host = match settings.server.host.as_str() {
            "0.0.0.0" => "127.0.0.1",
            "::" | "[::]" => "[::1]",
            other => other,
        };
        let base_url = format!("http://{host}:{}", settings.server.port);
        let token = ensure_token(Some(&paths)).unwrap_or_default();
        let client = reqwest::Client::builder()
            .no_proxy()
            .timeout(Duration::from_secs(15))
            .build()
            .map_err(|e| {
                fail_msg(
                    "HTTP_CLIENT_ERROR",
                    &format!("创建本地 HTTP 客户端失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    json_mode,
                )
            })?;
        Ok(Self {
            base_url,
            token,
            client,
        })
    }

    pub async fn health(&self) -> Option<Value> {
        let url = format!("{}/health", self.base_url);
        let resp = self
            .client
            .get(&url)
            .timeout(Duration::from_secs(2))
            .send()
            .await
            .ok()?;
        if !resp.status().is_success() {
            return None;
        }
        resp.json::<Value>().await.ok()
    }

    pub async fn request_json(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
        json_mode: bool,
    ) -> Result<Value, CliExit> {
        let url = format!("{}{}", self.base_url, path);
        let mut req = self
            .client
            .request(method, &url)
            .header("Authorization", format!("Bearer {}", self.token));
        if let Some(b) = body {
            req = req.json(&b);
        }
        let resp = req.send().await.map_err(|e| {
            let msg = if e.is_connect() {
                "本地服务未运行，请先执行 'mog server start'".to_string()
            } else {
                format!("请求本地服务失败: {e}")
            };
            fail_msg("NETWORK_ERROR", &msg, Map::new(), EXIT_NETWORK, json_mode)
        })?;

        let status = resp.status();
        let text = resp.text().await.unwrap_or_default();
        if status.is_success() {
            if text.trim().is_empty() {
                return Ok(Value::Null);
            }
            return serde_json::from_str::<Value>(&text).map_err(|e| {
                fail_msg(
                    "API_RESPONSE_ERROR",
                    &format!("解析响应 JSON 失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    json_mode,
                )
            });
        }

        // 解析标准 API 错误体 {"error": {"code", "message", "details"}}
        let exit_code = match status.as_u16() {
            404 => EXIT_NOT_FOUND,
            400 => EXIT_USAGE,
            422 => EXIT_VALIDATION,
            _ => EXIT_ERROR,
        };
        if let Ok(val) = serde_json::from_str::<Value>(&text)
            && let Some(err_obj) = val.get("error").and_then(|v| v.as_object())
        {
            let code = err_obj
                .get("code")
                .and_then(|v| v.as_str())
                .unwrap_or("API_ERROR");
            let message = err_obj
                .get("message")
                .and_then(|v| v.as_str())
                .unwrap_or("接口返回错误");
            let details = err_obj
                .get("details")
                .and_then(|v| v.as_object())
                .cloned()
                .unwrap_or_default();
            return Err(fail_msg(code, message, details, exit_code, json_mode));
        }
        Err(fail_msg(
            &format!("HTTP_{}", status.as_u16()),
            if text.is_empty() {
                status.canonical_reason().unwrap_or("请求失败")
            } else {
                text.trim()
            },
            Map::new(),
            exit_code,
            json_mode,
        ))
    }

    pub async fn post_json(
        &self,
        path: &str,
        body: Option<Value>,
        json_mode: bool,
    ) -> Result<Value, CliExit> {
        self.request_json(Method::POST, path, body, json_mode).await
    }

    /// 订阅 SSE 事件流，将包含 `status` 字段的任务事件回调给调用方。
    /// 若回调返回 `true`，则结束监听。
    pub async fn stream_task_events<F>(
        &self,
        task_id: Option<&str>,
        json_mode: bool,
        mut on_event: F,
    ) -> Result<(), CliExit>
    where
        F: FnMut(&Value) -> bool,
    {
        let mut url = format!("{}/api/v1/tasks/events", self.base_url);
        if let Some(id) = task_id {
            let encoded: String = url::form_urlencoded::byte_serialize(id.as_bytes()).collect();
            url.push_str(&format!("?task_id={encoded}"));
        }
        // 流式连接不设置整体响应超时
        let stream_client = reqwest::Client::builder().no_proxy().build().map_err(|e| {
            fail_msg(
                "HTTP_CLIENT_ERROR",
                &format!("创建 SSE 客户端失败: {e}"),
                Map::new(),
                EXIT_ERROR,
                json_mode,
            )
        })?;
        let resp = stream_client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token))
            .header("Accept", "text/event-stream")
            .send()
            .await
            .map_err(|e| {
                let msg = if e.is_connect() {
                    "本地服务未运行，请先执行 'mog server start'".to_string()
                } else {
                    format!("连接事件流失败: {e}")
                };
                fail_msg("NETWORK_ERROR", &msg, Map::new(), EXIT_NETWORK, json_mode)
            })?;

        if !resp.status().is_success() {
            return Err(fail_msg(
                &format!("HTTP_{}", resp.status().as_u16()),
                "无法订阅任务事件流",
                Map::new(),
                EXIT_ERROR,
                json_mode,
            ));
        }

        let mut stream = resp.bytes_stream();
        let mut buf = String::new();
        let mut current_event: Option<String> = None;
        let mut data_lines: Vec<String> = Vec::new();

        while let Some(chunk_res) = stream.next().await {
            let chunk = chunk_res.map_err(|e| {
                fail_msg(
                    "SSE_STREAM_ERROR",
                    &format!("读取事件流中断: {e}"),
                    Map::new(),
                    EXIT_NETWORK,
                    json_mode,
                )
            })?;
            buf.push_str(&String::from_utf8_lossy(&chunk));

            while let Some(pos) = buf.find('\n') {
                let mut line = buf[..pos].to_string();
                buf.drain(..=pos);
                if line.ends_with('\r') {
                    line.pop();
                }

                if line.is_empty() {
                    if !data_lines.is_empty() {
                        let raw = data_lines.join("\n");
                        let is_heartbeat = current_event.as_deref() == Some("heartbeat");
                        if !is_heartbeat
                            && let Ok(val) = serde_json::from_str::<Value>(&raw)
                            && val.get("status").is_some()
                            && on_event(&val)
                        {
                            return Ok(());
                        }
                    }
                    current_event = None;
                    data_lines.clear();
                    continue;
                }

                if line.starts_with(':') {
                    continue;
                }
                if let Some(rest) = line.strip_prefix("event:") {
                    current_event = Some(rest.trim().to_string());
                } else if let Some(rest) = line.strip_prefix("data:") {
                    data_lines.push(rest.trim_start().to_string());
                }
            }
        }
        Ok(())
    }
}
