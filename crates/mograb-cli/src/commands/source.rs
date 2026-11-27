// SPDX-License-Identifier: GPL-3.0-only
//! `mog source` —— 书源管理、静态检验（lint）、离线测试（test）、诊断与脚手架。

use crate::common::{
    CliExit, EXIT_ERROR, EXIT_NOT_FOUND, EXIT_VALIDATION, emit_json, fail_err, fail_msg, new_table,
    open_app, truncate,
};
use clap::{Args, Subcommand};
use futures::future::join_all;
use mograb_core::domain::enums::SourceCapability;
use mograb_core::domain::source::SOURCE_ID_RE;
use mograb_core::source::{LintReport, lint, load_cases, load_source_file, run_cases};
use serde_json::{Map, Value, json};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Args)]
pub struct SourceArgs {
    #[command(subcommand)]
    pub command: SourceCommand,
}

#[derive(Debug, Subcommand)]
pub enum SourceCommand {
    /// 列出已安装的书源
    List {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 查看单个书源详情
    Show {
        /// 书源 ID
        source_id: String,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 校验书源 Schema 与规则（无需联网）
    Lint {
        /// 书源目录或 source.yaml/source.json 路径
        path: PathBuf,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 使用本地 HTML/JSON 快照（fixtures/cases.yaml）离线测试书源
    Test {
        /// 书源目录（或 source.yaml 所在路径）
        target: PathBuf,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 安装书源到本地书源库
    Install {
        /// 书源目录或文件
        target: PathBuf,
        /// 忽略已存在或覆盖安装
        #[arg(long)]
        force: bool,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 卸载已安装书源
    Remove {
        /// 书源 ID
        source_id: String,
        /// 跳过确认提示
        #[arg(short = 'y', long)]
        yes: bool,
    },
    /// 启用书源
    Enable {
        /// 书源 ID
        source_id: String,
    },
    /// 禁用书源
    Disable {
        /// 书源 ID
        source_id: String,
    },
    /// 重新扫描数据目录下的 sources/ 并同步数据库
    Rescan {
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 诊断书源健康状态
    Doctor {
        /// 限定单个书源 ID
        source_id: Option<String>,
        /// 发起在线搜索探测
        #[arg(long)]
        live: bool,
        /// 输出 JSON 格式
        #[arg(long)]
        json: bool,
    },
    /// 在指定目录生成书源开发脚手架
    Init {
        /// 书源 ID（小写字母开头，可含小写字母/数字/-/_）
        name: String,
        /// 父目录（默认当前目录）
        #[arg(short = 'd', long, default_value = ".")]
        dir: PathBuf,
    },
}

fn resolve_source_manifest(target: &Path) -> Result<(PathBuf, PathBuf), String> {
    if target.is_dir() {
        for name in ["source.yaml", "source.yml", "source.json"] {
            let candidate = target.join(name);
            if candidate.is_file() {
                return Ok((candidate, target.to_path_buf()));
            }
        }
        Err(format!(
            "目录 {} 下找不到 source.yaml / source.yml / source.json",
            target.display()
        ))
    } else if target.is_file() {
        let dir = target
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf();
        Ok((target.to_path_buf(), dir))
    } else {
        Err(format!("路径不存在: {}", target.display()))
    }
}

fn print_lint_human(report: &LintReport, origin: &Path) {
    let errors = report.errors();
    let warnings = report.warnings();
    if report.is_ready() {
        println!(
            "PASS: {} ({}) [警告 {} 条]",
            report.source_id,
            origin.display(),
            warnings.len()
        );
    } else {
        eprintln!(
            "FAIL: {} ({}) [错误 {} 条, 警告 {} 条]",
            report.source_id,
            origin.display(),
            errors.len(),
            warnings.len()
        );
    }
    for d in &report.diagnostics {
        println!("  {}", d.format());
    }
}

pub async fn run(args: SourceArgs, verbose: bool) -> Result<(), CliExit> {
    match args.command {
        SourceCommand::List { json } => {
            let app = open_app(verbose, json).await?;
            let sources = app
                .sources
                .list_all()
                .await
                .map_err(|e| fail_err(&e, json))?;
            app.aclose().await;

            if json {
                let items: Vec<_> = sources
                    .iter()
                    .map(|s| {
                        json!({
                            "id": s.spec.id,
                            "name": s.spec.name,
                            "version": s.spec.version,
                            "enabled": s.enabled,
                            "health": s.health.as_str(),
                            "capabilities": s.spec.capabilities.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
                            "homepage": s.spec.homepage,
                        })
                    })
                    .collect();
                emit_json(&items);
            } else if sources.is_empty() {
                println!("暂无已安装书源");
            } else {
                let mut table = new_table(&["ID", "名称", "版本", "启用", "健康度", "能力"]);
                for s in &sources {
                    let caps = s
                        .spec
                        .capabilities
                        .iter()
                        .map(|c| c.as_str())
                        .collect::<Vec<_>>()
                        .join(",");
                    table.add_row([
                        s.spec.id.clone(),
                        truncate(&s.spec.name, 18),
                        s.spec.version.clone(),
                        if s.enabled { "启用" } else { "禁用" }.to_string(),
                        s.health.as_str().to_string(),
                        caps,
                    ]);
                }
                println!("{table}");
            }
            Ok(())
        }
        SourceCommand::Show { source_id, json } => {
            let app = open_app(verbose, json).await?;
            let src = app
                .sources
                .get(&source_id)
                .await
                .map_err(|e| fail_err(&e, json))?;
            app.aclose().await;
            let Some(s) = src else {
                return Err(fail_msg(
                    "SOURCE_NOT_FOUND",
                    &format!("书源不存在: {source_id}"),
                    Map::new(),
                    EXIT_NOT_FOUND,
                    json,
                ));
            };
            if json {
                emit_json(&json!({
                    "id": s.spec.id,
                    "name": s.spec.name,
                    "version": s.spec.version,
                    "authors": s.spec.authors,
                    "description": s.spec.description,
                    "homepage": s.spec.homepage,
                    "enabled": s.enabled,
                    "health": s.health.as_str(),
                    "capabilities": s.spec.capabilities.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
                    "spec": s.spec,
                }));
            } else {
                let authors = if s.spec.authors.is_empty() {
                    "-".to_string()
                } else {
                    s.spec.authors.join(", ")
                };
                println!("ID:       {}", s.spec.id);
                println!("名称:     {}", s.spec.name);
                println!("版本:     {}", s.spec.version);
                println!("作者:     {authors}");
                println!("主页 URL: {}", s.spec.homepage.as_deref().unwrap_or("-"));
                println!(
                    "状态:     {} / {}",
                    if s.enabled { "启用" } else { "禁用" },
                    s.health.as_str()
                );
                println!(
                    "能力:     {}",
                    s.spec
                        .capabilities
                        .iter()
                        .map(|c| c.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                );
            }
            Ok(())
        }
        SourceCommand::Lint { path, json } => {
            let (manifest, _) = resolve_source_manifest(&path).map_err(|msg| {
                fail_msg(
                    "SOURCE_SCHEMA_ERROR",
                    &msg,
                    Map::new(),
                    EXIT_VALIDATION,
                    json,
                )
            })?;
            let spec = load_source_file(&manifest).map_err(|e| fail_err(&e, json))?;
            let report = lint(&spec);
            if json {
                emit_json(&report.to_json_value());
            } else {
                print_lint_human(&report, &manifest);
            }
            if !report.is_ready() {
                return Err(CliExit(EXIT_VALIDATION));
            }
            Ok(())
        }
        SourceCommand::Test { target, json } => {
            let (manifest, source_dir) = resolve_source_manifest(&target).map_err(|msg| {
                fail_msg(
                    "SOURCE_SCHEMA_ERROR",
                    &msg,
                    Map::new(),
                    EXIT_VALIDATION,
                    json,
                )
            })?;
            let spec = load_source_file(&manifest).map_err(|e| fail_err(&e, json))?;
            let report = lint(&spec);
            if !report.is_ready() {
                if json {
                    emit_json(&report.to_json_value());
                } else {
                    print_lint_human(&report, &manifest);
                }
                return Err(CliExit(EXIT_VALIDATION));
            }
            let cases = load_cases(&source_dir).map_err(|e| fail_err(&e, json))?;
            let results = run_cases(&spec, &cases, &source_dir).await;
            let all_ok = results.iter().all(|r| r.ok);

            if json {
                let items: Vec<_> = results
                    .iter()
                    .map(|r| {
                        json!({
                            "capability": r.case.capability.as_str(),
                            "url": r.case.url,
                            "ok": r.ok,
                            "summary": r.summary,
                        })
                    })
                    .collect();
                emit_json(&json!({
                    "source_id": spec.id,
                    "ok": all_ok,
                    "cases": items,
                }));
            } else {
                for r in &results {
                    let badge = if r.ok { "PASS" } else { "FAIL" };
                    println!("[{badge}] {}: {}", r.case.capability.as_str(), r.summary);
                }
            }
            if !all_ok {
                return Err(CliExit(EXIT_VALIDATION));
            }
            Ok(())
        }
        SourceCommand::Install {
            target,
            force,
            json,
        } => {
            let (manifest, _) = resolve_source_manifest(&target).map_err(|msg| {
                fail_msg(
                    "SOURCE_SCHEMA_ERROR",
                    &msg,
                    Map::new(),
                    EXIT_VALIDATION,
                    json,
                )
            })?;
            let spec = load_source_file(&manifest).map_err(|e| fail_err(&e, json))?;
            let report = lint(&spec);
            if !report.is_ready() {
                if json {
                    emit_json(&report.to_json_value());
                } else {
                    print_lint_human(&report, &manifest);
                }
                return Err(CliExit(EXIT_VALIDATION));
            }

            let app = open_app(verbose, json).await?;
            if !force
                && app
                    .sources
                    .get(&spec.id)
                    .await
                    .map_err(|e| fail_err(&e, json))?
                    .is_some()
            {
                app.aclose().await;
                return Err(fail_msg(
                    "SOURCE_EXISTS",
                    &format!("书源 {} 已安装（使用 --force 覆盖）", spec.id),
                    Map::new(),
                    EXIT_ERROR,
                    json,
                ));
            }
            app.sources
                .save(&spec)
                .await
                .map_err(|e| fail_err(&e, json))?;
            app.aclose().await;

            if json {
                emit_json(&json!({
                    "id": spec.id,
                    "name": spec.name,
                    "version": spec.version,
                    "installed": true,
                }));
            } else {
                println!("已安装书源: {} ({}) v{}", spec.name, spec.id, spec.version);
            }
            Ok(())
        }
        SourceCommand::Remove { source_id, yes } => {
            if !yes {
                eprint!("确认卸载书源 {source_id}？[y/N]: ");
                let mut line = String::new();
                if std::io::stdin().read_line(&mut line).is_err()
                    || !matches!(line.trim().to_ascii_lowercase().as_str(), "y" | "yes")
                {
                    println!("已取消");
                    return Ok(());
                }
            }
            let app = open_app(verbose, false).await?;
            let removed = app
                .sources
                .delete(&source_id)
                .await
                .map_err(|e| fail_err(&e, false))?;
            app.aclose().await;
            if !removed {
                return Err(fail_msg(
                    "SOURCE_NOT_FOUND",
                    &format!("书源不存在: {source_id}"),
                    Map::new(),
                    EXIT_NOT_FOUND,
                    false,
                ));
            }
            println!("已卸载书源: {source_id}");
            Ok(())
        }
        SourceCommand::Enable { source_id } => {
            let app = open_app(verbose, false).await?;
            app.sources
                .set_enabled(&source_id, true)
                .await
                .map_err(|e| fail_err(&e, false))?;
            app.aclose().await;
            println!("已启用书源: {source_id}");
            Ok(())
        }
        SourceCommand::Disable { source_id } => {
            let app = open_app(verbose, false).await?;
            app.sources
                .set_enabled(&source_id, false)
                .await
                .map_err(|e| fail_err(&e, false))?;
            app.aclose().await;
            println!("已禁用书源: {source_id}");
            Ok(())
        }
        SourceCommand::Rescan { json } => {
            let app = open_app(verbose, json).await?;
            let list = app.sources.rescan().await.map_err(|e| fail_err(&e, json))?;
            app.aclose().await;
            if json {
                let ids: Vec<_> = list.iter().map(|s| &s.spec.id).collect();
                emit_json(&json!({ "count": ids.len(), "sources": ids }));
            } else {
                println!("重新扫描完成，当前共 {} 个书源", list.len());
            }
            Ok(())
        }
        SourceCommand::Doctor {
            source_id,
            live,
            json,
        } => {
            let app = open_app(verbose, json).await?;
            let targets = if let Some(ref sid) = source_id {
                let s = app
                    .sources
                    .get(sid)
                    .await
                    .map_err(|e| fail_err(&e, json))?
                    .ok_or_else(|| {
                        fail_msg(
                            "SOURCE_NOT_FOUND",
                            &format!("书源不存在: {sid}"),
                            Map::new(),
                            EXIT_NOT_FOUND,
                            json,
                        )
                    })?;
                vec![s]
            } else {
                app.sources
                    .list_all()
                    .await
                    .map_err(|e| fail_err(&e, json))?
            };

            let engine = app.engine.clone();
            let futs = targets.iter().map(|src| {
                let engine = engine.clone();
                let spec = src.spec.clone();
                let enabled = src.enabled;
                async move {
                    let report = lint(&spec);
                    let mut live_status: Option<Value> = None;
                    if live && report.is_ready() && spec.supports(SourceCapability::Search) {
                        match engine.search(&spec, "三体", 1).await {
                            Ok(hits) => {
                                live_status = Some(json!({ "ok": true, "hits": hits.len() }));
                            }
                            Err(e) => {
                                live_status = Some(json!({
                                    "ok": false,
                                    "code": e.code(),
                                    "message": e.message(),
                                }));
                            }
                        }
                    }
                    let mut val = report.to_json_value();
                    if let Some(m) = val.as_object_mut() {
                        m.insert("enabled".into(), json!(enabled));
                        if let Some(ls) = live_status {
                            m.insert("live".into(), ls);
                        }
                    }
                    (spec.id.clone(), report, val)
                }
            });
            let checks = join_all(futs).await;
            app.aclose().await;

            let all_ready = checks.iter().all(|(_, r, _)| r.is_ready());
            if json {
                let items: Vec<_> = checks.into_iter().map(|(_, _, v)| v).collect();
                emit_json(&items);
            } else if checks.is_empty() {
                println!("暂无已安装书源");
            } else {
                for (sid, report, val) in checks {
                    let status = if report.is_ready() { "READY" } else { "BROKEN" };
                    print!(
                        "[{status}] {sid} (错误 {}, 警告 {})",
                        report.errors().len(),
                        report.warnings().len()
                    );
                    if let Some(ls) = val.get("live") {
                        if ls["ok"].as_bool() == Some(true) {
                            print!(" [live: {} hits]", ls["hits"]);
                        } else {
                            print!(" [live FAIL: {}]", ls["message"].as_str().unwrap_or("-"));
                        }
                    }
                    println!();
                }
            }
            if !all_ready {
                return Err(CliExit(EXIT_VALIDATION));
            }
            Ok(())
        }
        SourceCommand::Init { name, dir } => {
            if !SOURCE_ID_RE.is_match(&name) {
                return Err(fail_msg(
                    "SOURCE_SCHEMA_ERROR",
                    &format!("非法书源 ID {name:?}，需以小写字母开头，仅含小写字母/数字/-/_"),
                    Map::new(),
                    EXIT_VALIDATION,
                    false,
                ));
            }
            let target_dir = dir.join(&name);
            let fixtures_dir = target_dir.join("fixtures");
            fs::create_dir_all(&fixtures_dir).map_err(|e| {
                fail_msg(
                    "INIT_ERROR",
                    &format!("创建目录失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;

            let template = format!(
                r###"spec_version: 1
id: {name}
name: {name} 示例书源
version: 0.1.0
homepage: https://example.com
capabilities: [search, book, chapters, content]

network:
  concurrency: 2
  request_interval_ms: 500

permissions:
  network:
    - example.com

search:
  request:
    method: GET
    url: "https://example.com/search"
    query:
      q: "{{{{ keyword }}}}"
  result:
    list: ".book-item"
    fields:
      title: ".title@text"
      url: "a@href"
      author: ".author@text"
  transform:
    - trim

book:
  request:
    method: GET
    url: "{{{{ book.url }}}}"
  fields:
    title: "h1.title@text"
    author: ".author@text"

chapters:
  request:
    method: GET
    url: "{{{{ book.url }}}}"
  result:
    list: "#chapters li"
    fields:
      title: "a@text"
      url: "a@href"

content:
  request:
    method: GET
    url: "{{{{ chapter.url }}}}"
  body: "#content@html"
  transform:
    - trim
    - remove_html
"###
            );
            let cases = r#"- capability: search
  url: "https://example.com/search?q=demo"
  keyword: demo
  files: [search.html]
"#;
            let sample_html = r#"<!doctype html>
<html><body>
<div class="book-item">
  <a href="/book/1"><span class="title">示例书籍</span></a>
  <span class="author">示例作者</span>
</div>
</body></html>
"#;
            fs::write(target_dir.join("source.yaml"), template).map_err(|e| {
                fail_msg(
                    "INIT_ERROR",
                    &format!("写入失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;
            fs::write(fixtures_dir.join("cases.yaml"), cases).map_err(|e| {
                fail_msg(
                    "INIT_ERROR",
                    &format!("写入失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;
            fs::write(fixtures_dir.join("search.html"), sample_html).map_err(|e| {
                fail_msg(
                    "INIT_ERROR",
                    &format!("写入失败: {e}"),
                    Map::new(),
                    EXIT_ERROR,
                    false,
                )
            })?;

            println!("已创建书源脚手架: {}", target_dir.display());
            println!("  下一步: mog source lint {}", target_dir.display());
            println!("          mog source test {}", target_dir.display());
            Ok(())
        }
    }
}
