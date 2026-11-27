// SPDX-License-Identifier: GPL-3.0-only
//! Fixture 测试运行器（`mog source test`）。

use super::engine::{FetchOptions, FetchResponse, Fetcher, SourceEngine};
use crate::domain::enums::SourceCapability;
use crate::domain::source::SourceSpec;
use crate::errors::{MoGrabError, MoGrabResult};
use async_trait::async_trait;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};

pub const CASES_FILENAME: &str = "cases.yaml";
pub const FIXTURES_DIRNAME: &str = "fixtures";

#[derive(Debug, Clone)]
pub struct FixtureCase {
    pub capability: SourceCapability,
    pub url: String,
    pub files: Vec<String>,
    pub keyword: Option<String>,
}

#[derive(Debug, Clone)]
pub struct CaseResult {
    pub case: FixtureCase,
    pub ok: bool,
    pub summary: String,
}

pub fn cases_path(source_dir: &Path) -> PathBuf {
    source_dir.join(FIXTURES_DIRNAME).join(CASES_FILENAME)
}

#[derive(Debug, Deserialize)]
struct RawCase {
    capability: Option<String>,
    url: Option<String>,
    files: Option<serde_yaml_ng::Value>,
    keyword: Option<String>,
}

pub fn load_cases(source_dir: &Path) -> MoGrabResult<Vec<FixtureCase>> {
    let path = cases_path(source_dir);
    if !path.is_file() {
        return Err(MoGrabError::source_schema(format!(
            "找不到用例文件 {}。\n先写一份 fixtures/cases.yaml，声明每个能力用哪个快照：\n\n  - capability: book\n    url: https://example.com/book/1\n    files: [book.html]\n",
            path.display()
        )));
    }

    let text = fs::read_to_string(&path)
        .map_err(|e| MoGrabError::source_schema(format!("读取 {} 失败: {e}", path.display())))?;
    let raw_list: Vec<RawCase> = serde_yaml_ng::from_str(&text)
        .map_err(|e| MoGrabError::source_schema(format!("{} 解析失败: {e}", path.display())))?;

    let fixtures_dir = source_dir.join(FIXTURES_DIRNAME);
    let mut cases = Vec::with_capacity(raw_list.len());

    for (idx, item) in raw_list.into_iter().enumerate() {
        let where_str = format!("{}: 第 {} 条", path.display(), idx + 1);
        let cap_str = item
            .capability
            .ok_or_else(|| MoGrabError::source_schema(format!("{where_str} 缺少 capability")))?;
        let capability = SourceCapability::from_str_opt(&cap_str).ok_or_else(|| {
            MoGrabError::source_schema(format!("{where_str} 的能力名非法: {cap_str:?}"))
        })?;

        let url = item
            .url
            .filter(|u| !u.trim().is_empty())
            .ok_or_else(|| MoGrabError::source_schema(format!("{where_str} 缺少 url")))?;

        let files: Vec<String> = match item.files {
            None => Vec::new(),
            Some(serde_yaml_ng::Value::String(s)) => vec![s],
            Some(serde_yaml_ng::Value::Sequence(seq)) => seq
                .into_iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect(),
            _ => {
                return Err(MoGrabError::source_schema(format!(
                    "{where_str} 的 files 必须是字符串或列表"
                )));
            }
        };

        if files.is_empty() {
            return Err(MoGrabError::source_schema(format!(
                "{where_str} 没有声明 files"
            )));
        }

        for name in &files {
            let p = fixtures_dir.join(name);
            if !p.is_file() {
                return Err(MoGrabError::source_schema(format!(
                    "{where_str} 引用的快照不存在: {}",
                    p.display()
                )));
            }
        }

        cases.push(FixtureCase {
            capability,
            url,
            files,
            keyword: item.keyword,
        });
    }

    Ok(cases)
}

struct SnapshotFetcher {
    files: Vec<PathBuf>,
    calls: Mutex<Vec<String>>,
}

impl SnapshotFetcher {
    fn new(files: Vec<PathBuf>) -> Self {
        Self {
            files,
            calls: Mutex::new(Vec::new()),
        }
    }
}

#[async_trait]
impl Fetcher for SnapshotFetcher {
    async fn fetch(&self, opts: FetchOptions<'_>) -> MoGrabResult<FetchResponse> {
        let index = {
            let mut guard = self.calls.lock().expect("snapshot calls mutex");
            let idx = guard.len();
            guard.push(opts.url.to_string());
            idx
        };
        if index >= self.files.len() {
            return Err(MoGrabError::source_execution(format!(
                "引擎请求了第 {} 个页面（{}），但用例只给了 {} 个快照",
                index + 1,
                opts.url,
                self.files.len()
            )));
        }
        let content = fs::read(&self.files[index]).map_err(|e| {
            MoGrabError::source_execution(format!(
                "读取快照失败 {}: {e}",
                self.files[index].display()
            ))
        })?;
        Ok(FetchResponse {
            content,
            encoding: Some("utf-8".to_string()),
            status_code: 200,
            url: opts.url.to_string(),
            from_cache: false,
            headers: BTreeMap::new(),
        })
    }
}

pub async fn run_cases(
    spec: &SourceSpec,
    cases: &[FixtureCase],
    source_dir: &Path,
) -> Vec<CaseResult> {
    let fixtures_dir = source_dir.join(FIXTURES_DIRNAME);
    let mut results = Vec::with_capacity(cases.len());

    for case in cases {
        let files: Vec<PathBuf> = case.files.iter().map(|f| fixtures_dir.join(f)).collect();
        let fetcher = Arc::new(SnapshotFetcher::new(files));
        let engine = SourceEngine::new(fetcher);

        match run_one(&engine, spec, case).await {
            Ok(summary) => results.push(CaseResult {
                case: case.clone(),
                ok: true,
                summary,
            }),
            Err(err) => results.push(CaseResult {
                case: case.clone(),
                ok: false,
                summary: err.to_string(),
            }),
        }
    }

    results
}

async fn run_one(
    engine: &SourceEngine,
    spec: &SourceSpec,
    case: &FixtureCase,
) -> MoGrabResult<String> {
    match case.capability {
        SourceCapability::Search => {
            let keyword = case.keyword.as_deref().unwrap_or("test");
            let hits = engine.search(spec, keyword, 1).await?;
            if hits.is_empty() {
                return Err(MoGrabError::source_execution(format!(
                    "搜索「{keyword}」没有命中任何结果"
                )));
            }
            Ok(format!("{} 条结果，首条 {:?}", hits.len(), hits[0].title))
        }
        SourceCapability::Book => {
            let draft = engine.fetch_book(spec, &case.url).await?;
            Ok(format!(
                "书名 {:?}，作者 {}",
                draft.title,
                draft.author.as_deref().unwrap_or("（无）")
            ))
        }
        SourceCapability::Chapters => {
            let chapters = engine.fetch_chapters(spec, &case.url).await?;
            if chapters.is_empty() {
                return Err(MoGrabError::source_execution("目录里没有任何章节"));
            }
            Ok(format!(
                "{} 章，首章 {:?}",
                chapters.len(),
                chapters[0].title
            ))
        }
        SourceCapability::Content => {
            let content = engine.fetch_content(spec, &case.url, None).await?;
            if content.trim().is_empty() {
                return Err(MoGrabError::source_execution("正文为空"));
            }
            let char_count = content.chars().count();
            let para_count = content.lines().filter(|l| !l.trim().is_empty()).count();
            Ok(format!("{char_count} 字符，段落 {para_count} 段"))
        }
        other => Err(MoGrabError::source_execution(format!(
            "暂不支持测试能力 {}",
            other.as_str()
        ))),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::source::loader::load_source_file;
    use crate::source::validator::lint;

    #[tokio::test]
    async fn test_example_source_fixtures_all_pass() {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/example-source");
        let spec = load_source_file(&dir.join("source.yaml")).unwrap();
        let report = lint(&spec);
        assert!(report.is_ready(), "lint errors: {:?}", report.errors());

        let cases = load_cases(&dir).unwrap();
        assert_eq!(cases.len(), 4);

        let results = run_cases(&spec, &cases, &dir).await;
        for res in &results {
            assert!(
                res.ok,
                "case {:?} failed: {}",
                res.case.capability, res.summary
            );
        }
    }
}
