// SPDX-License-Identifier: GPL-3.0-only
//! HttpClient —— 集成白名单校验 / 缓存 / 限流 / 重试 / 中文编码探测。

use super::cache::{HttpCache, TTL_DEFAULT, build_cache_key, make_entry, merge_params};
use super::limiter::{GlobalLimiter, SourceLimiterRegistry};
use super::retry::RetryPolicy;
use crate::errors::{MoGrabError, MoGrabResult};
use crate::logging::redact_headers;
use crate::source::engine::{FetchOptions, FetchResponse, Fetcher};
use async_trait::async_trait;
use regex::bytes::Regex as BytesRegex;
use reqwest::{Client, Method, Proxy, redirect::Policy};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashSet};
use std::sync::{Arc, LazyLock};
use std::time::Duration;
use tracing::{debug, warn};
use url::Url;

static META_CHARSET_RE: LazyLock<BytesRegex> = LazyLock::new(|| {
    BytesRegex::new(r#"(?i)<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_\-]+)"#)
        .expect("valid META_CHARSET_RE")
});
static META_HTTP_EQUIV_RE: LazyLock<BytesRegex> = LazyLock::new(|| {
    BytesRegex::new(r#"(?i)<meta[^>]+content\s*=\s*["'][^"']*charset\s*=\s*([a-zA-Z0-9_\-]+)"#)
        .expect("valid META_HTTP_EQUIV_RE")
});

#[derive(Debug, Clone)]
pub struct HttpClientConfig {
    pub timeout_ms: u64,
    pub retry: RetryPolicy,
    pub verify_ssl: bool,
    pub proxy: Option<String>,
    pub user_agent: Option<String>,
    pub max_redirects: usize,
    pub allow_domains: HashSet<String>,
}

impl Default for HttpClientConfig {
    fn default() -> Self {
        Self {
            timeout_ms: 15_000,
            retry: RetryPolicy::default(),
            verify_ssl: true,
            proxy: None,
            user_agent: None,
            max_redirects: 5,
            allow_domains: HashSet::new(),
        }
    }
}

pub struct HttpClient {
    config: HttpClientConfig,
    cache: Option<Arc<dyn HttpCache>>,
    limiters: Arc<SourceLimiterRegistry>,
    client: Client,
}

impl HttpClient {
    pub fn new(
        config: HttpClientConfig,
        cache: Option<Arc<dyn HttpCache>>,
        limiters: Option<Arc<SourceLimiterRegistry>>,
    ) -> MoGrabResult<Self> {
        let mut builder = Client::builder()
            .redirect(Policy::limited(config.max_redirects))
            .timeout(Duration::from_millis(config.timeout_ms))
            .danger_accept_invalid_certs(!config.verify_ssl);

        if let Some(ref proxy_url) = config.proxy {
            let proxy = Proxy::all(proxy_url)
                .map_err(|e| MoGrabError::config(format!("无效代理地址 {proxy_url:?}: {e}")))?;
            builder = builder.proxy(proxy);
        }

        let client = builder
            .build()
            .map_err(|e| MoGrabError::network(format!("构建 HTTP 客户端失败: {e}"), json!({})))?;

        let registry = limiters.unwrap_or_else(|| {
            Arc::new(SourceLimiterRegistry::new(GlobalLimiter::default(), 2, 0.5))
        });

        Ok(Self {
            config,
            cache,
            limiters: registry,
            client,
        })
    }

    pub async fn fetch(&self, opts: FetchOptions<'_>) -> MoGrabResult<FetchResponse> {
        self.assert_domain_allowed(opts.url, opts.source_id, opts.allowed_domains)?;

        let cache_key = if opts.use_cache && self.cache.is_some() {
            let key = build_cache_key(
                opts.source_id,
                opts.method,
                opts.url,
                opts.params,
                opts.data,
                Some(opts.headers),
            );
            if let Some(ref cache) = self.cache
                && let Some(entry) = cache.get(&key).await?
            {
                return Ok(FetchResponse {
                    content: entry.content,
                    encoding: entry.encoding,
                    status_code: entry.status_code,
                    url: opts.url.to_string(),
                    from_cache: true,
                    headers: BTreeMap::new(),
                });
            }
            Some(key)
        } else {
            None
        };

        let result = self.fetch_with_retry(&opts).await?;

        if let (Some(key), Some(cache)) = (cache_key, &self.cache)
            && result.status_code == 200
        {
            let entry = make_entry(
                key,
                opts.source_id.to_string(),
                opts.url.to_string(),
                result.status_code,
                result.content.clone(),
                result.encoding.clone(),
                opts.ttl_seconds.unwrap_or(TTL_DEFAULT),
            );
            cache.put(entry).await?;
        }

        Ok(result)
    }

    async fn fetch_with_retry(&self, opts: &FetchOptions<'_>) -> MoGrabResult<FetchResponse> {
        let mut policy = self.config.retry.clone();
        if let Some(max_retries) = opts.max_retries {
            policy.max_retries = max_retries;
        }

        let limiter = self
            .limiters
            .get(opts.source_id, opts.concurrency, opts.min_interval_secs)
            .await;

        let mut attempt = 0usize;
        loop {
            let outcome = {
                let _global_permit = self.limiters.global_limiter().acquire().await;
                let _source_permit = limiter.acquire().await;
                self.do_request(opts).await
            };

            match outcome {
                Ok(resp) => return Ok(resp),
                Err(err) => {
                    if !policy.should_retry(&err, attempt) {
                        return Err(err);
                    }
                    let delay = policy.delay_for(attempt, err.retry_after());
                    warn!(
                        source_id = opts.source_id,
                        url = opts.url,
                        attempt = attempt + 1,
                        delay = (delay * 100.0).round() / 100.0,
                        error = err.code(),
                        "http.retry"
                    );
                    tokio::time::sleep(Duration::from_secs_f64(delay)).await;
                    attempt += 1;
                }
            }
        }
    }

    async fn do_request(&self, opts: &FetchOptions<'_>) -> MoGrabResult<FetchResponse> {
        let mut headers = opts.headers.clone();
        if let Some(ref ua) = self.config.user_agent
            && !headers.keys().any(|k| k.eq_ignore_ascii_case("user-agent"))
        {
            headers.insert("User-Agent".to_string(), ua.clone());
        }

        debug!(
            method = opts.method,
            url = opts.url,
            source_id = opts.source_id,
            headers = ?redact_headers(&headers),
            "http.request"
        );

        let method = Method::from_bytes(opts.method.as_bytes()).map_err(|e| {
            MoGrabError::source_execution(format!("无效 HTTP 方法 {}: {e}", opts.method))
        })?;

        let effective_url = merge_params(opts.url, opts.params);
        let mut req = self.client.request(method, &effective_url);
        for (k, v) in &headers {
            req = req.header(k.as_str(), v.as_str());
        }
        if !opts.cookies.is_empty() {
            let cookie_str = opts
                .cookies
                .iter()
                .map(|(k, v)| format!("{k}={v}"))
                .collect::<Vec<_>>()
                .join("; ");
            req = req.header("Cookie", cookie_str);
        }
        if let Some(data) = opts.data {
            match data {
                Value::String(s) => {
                    req = req.body(s.clone());
                }
                Value::Object(map) => {
                    let mut ser = url::form_urlencoded::Serializer::new(String::new());
                    for (k, v) in map {
                        let val = match v {
                            Value::String(s) => s.clone(),
                            other => other.to_string(),
                        };
                        ser.append_pair(k, &val);
                    }
                    req = req
                        .header("Content-Type", "application/x-www-form-urlencoded")
                        .body(ser.finish());
                }
                other => {
                    req = req.json(other);
                }
            }
        }
        let timeout_ms = opts.timeout_ms.unwrap_or(self.config.timeout_ms);
        req = req.timeout(Duration::from_millis(timeout_ms));

        let resp = req.send().await.map_err(|e| {
            if e.is_timeout() {
                MoGrabError::timeout(format!("请求超时: {}", opts.url), json!({"url": opts.url}))
            } else {
                MoGrabError::network(
                    format!("网络错误: {} ({e})", opts.url),
                    json!({"url": opts.url}),
                )
            }
        })?;

        let status_code = resp.status().as_u16();
        let final_url = resp.url().to_string();
        let mut resp_headers = BTreeMap::new();
        for (k, v) in resp.headers() {
            if let Ok(val) = v.to_str() {
                resp_headers.insert(k.as_str().to_lowercase(), val.to_string());
            }
        }

        if status_code == 429 {
            let retry_after = resp_headers
                .get("retry-after")
                .and_then(|s| s.trim().parse::<f64>().ok());
            return Err(MoGrabError::rate_limited(
                format!("被限流 (429): {}", opts.url),
                retry_after,
                json!({"url": opts.url}),
            ));
        }

        if status_code >= 400 {
            return Err(MoGrabError::http_status(
                format!("HTTP {status_code}: {}", opts.url),
                status_code,
                json!({"url": opts.url}),
            ));
        }

        let content = resp
            .bytes()
            .await
            .map_err(|e| {
                MoGrabError::network(
                    format!("读取响应失败: {} ({e})", opts.url),
                    json!({"url": opts.url}),
                )
            })?
            .to_vec();

        let encoding = opts
            .encoding
            .map(str::to_string)
            .unwrap_or_else(|| detect_encoding(&resp_headers, &content));

        Ok(FetchResponse {
            content,
            encoding: Some(encoding),
            status_code,
            url: final_url,
            from_cache: false,
            headers: resp_headers,
        })
    }

    fn assert_domain_allowed(
        &self,
        url_str: &str,
        source_id: &str,
        allowed_domains: Option<&[String]>,
    ) -> MoGrabResult<()> {
        let host = Url::parse(url_str)
            .ok()
            .and_then(|u| u.host_str().map(str::to_lowercase))
            .unwrap_or_default();

        if !self.config.allow_domains.is_empty()
            && !domain_matches(&host, self.config.allow_domains.iter().map(String::as_str))
        {
            let mut allowed: Vec<&str> = self
                .config
                .allow_domains
                .iter()
                .map(String::as_str)
                .collect();
            allowed.sort();
            return Err(MoGrabError::source_execution_with(
                format!("域名 {host} 不在允许列表内（source={source_id}）"),
                json!({"host": host, "source_id": source_id, "allowed": allowed}),
            ));
        }

        if let Some(domains) = allowed_domains
            && !domains.is_empty()
            && !domain_matches(&host, domains.iter().map(String::as_str))
        {
            let mut allowed: Vec<&str> = domains.iter().map(String::as_str).collect();
            allowed.sort();
            return Err(MoGrabError::source_execution_with(
                format!("域名 {host} 不在允许列表内（source={source_id}）"),
                json!({"host": host, "source_id": source_id, "allowed": allowed}),
            ));
        }

        Ok(())
    }
}

fn domain_matches<'a>(host: &str, allowed: impl IntoIterator<Item = &'a str>) -> bool {
    allowed
        .into_iter()
        .any(|d| host == d || host.ends_with(&format!(".{d}")))
}

pub fn detect_encoding(headers: &BTreeMap<String, String>, content: &[u8]) -> String {
    let mut candidates = Vec::new();
    if let Some(ct) = headers.get("content-type")
        && let Some(idx) = ct.to_lowercase().find("charset=")
    {
        let rest = &ct[idx + "charset=".len()..];
        let val = rest.split(';').next().unwrap_or("").trim();
        if !val.is_empty() {
            candidates.push(val.to_string());
        }
    }

    let head = &content[..content.len().min(4096)];
    for re in [&*META_CHARSET_RE, &*META_HTTP_EQUIV_RE] {
        if let Some(caps) = re.captures(head)
            && let Some(m) = caps.get(1)
            && let Ok(s) = std::str::from_utf8(m.as_bytes())
        {
            candidates.push(s.to_string());
        }
    }

    for candidate in candidates {
        let norm = candidate
            .trim()
            .trim_matches(|c| c == '"' || c == '\'')
            .to_lowercase();
        if norm.is_empty() {
            continue;
        }
        return match norm.as_str() {
            "gb2312" | "gbk" => "gb18030".to_string(),
            _ => norm,
        };
    }

    "utf-8".to_string()
}

#[async_trait]
impl Fetcher for HttpClient {
    async fn fetch(&self, opts: FetchOptions<'_>) -> MoGrabResult<FetchResponse> {
        HttpClient::fetch(self, opts).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_encoding_gbk_elevated_to_gb18030() {
        let mut hdrs = BTreeMap::new();
        hdrs.insert("content-type".into(), "text/html; charset=gbk".into());
        assert_eq!(detect_encoding(&hdrs, b""), "gb18030");

        let meta_html = br#"<html><head><meta charset="gb2312"></head></html>"#;
        assert_eq!(detect_encoding(&BTreeMap::new(), meta_html), "gb18030");
    }

    #[test]
    fn test_domain_whitelist_blocks_unlisted_host() {
        let client = HttpClient::new(HttpClientConfig::default(), None, None).unwrap();
        let allowed = vec!["example.com".to_string()];
        assert!(
            client
                .assert_domain_allowed("https://sub.example.com/a", "s1", Some(&allowed))
                .is_ok()
        );
        assert!(
            client
                .assert_domain_allowed("https://evil.org/a", "s1", Some(&allowed))
                .is_err()
        );
    }
}
