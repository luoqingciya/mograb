// SPDX-License-Identifier: GPL-3.0-only
//! `mog search` —— 并发检索多个已启用书源。

use crate::common::{
    CliExit, EXIT_ERROR, emit_json, fail_err, fail_msg, new_table, open_app, truncate,
};
use clap::Args;
use futures::future::join_all;
use mograb_core::domain::enums::SourceCapability;
use serde_json::{Map, json};
use std::collections::HashSet;

#[derive(Debug, Args)]
pub struct SearchArgs {
    /// 搜索关键词
    pub keyword: String,
    /// 限定书源 ID（可多次指定）
    #[arg(short = 's', long = "source")]
    pub sources: Vec<String>,
    /// 最多返回结果数
    #[arg(short = 'n', long, default_value_t = 20)]
    pub limit: usize,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: SearchArgs, verbose: bool) -> Result<(), CliExit> {
    let app = open_app(verbose, args.json).await?;
    let enabled = app
        .sources
        .list_enabled()
        .await
        .map_err(|e| fail_err(&e, args.json))?;

    let filter: HashSet<&str> = args.sources.iter().map(String::as_str).collect();
    let targets: Vec<_> = enabled
        .into_iter()
        .filter(|s| s.spec.supports(SourceCapability::Search))
        .filter(|s| filter.is_empty() || filter.contains(s.id()))
        .collect();

    if targets.is_empty() {
        app.aclose().await;
        return Err(fail_msg(
            "NO_SEARCHABLE_SOURCE",
            "没有可用的支持搜索的书源",
            Map::new(),
            EXIT_ERROR,
            args.json,
        ));
    }

    let futs = targets.iter().map(|src| {
        let engine = app.engine.clone();
        let spec = src.spec.clone();
        let kw = args.keyword.clone();
        async move {
            let sid = spec.id.clone();
            let res = engine.search(&spec, &kw, 1).await;
            (sid, res)
        }
    });
    let results = join_all(futs).await;
    app.aclose().await;

    let mut hits = Vec::new();
    let mut errors = Vec::new();
    for (sid, res) in results {
        match res {
            Ok(list) => hits.extend(list),
            Err(err) => errors.push(json!({
                "source_id": sid,
                "code": err.code(),
                "message": err.message(),
            })),
        }
    }
    hits.truncate(args.limit.max(1));

    if args.json {
        let hit_items: Vec<_> = hits
            .iter()
            .map(|h| {
                json!({
                    "source_id": h.source_id,
                    "title": h.title,
                    "author": h.author,
                    "url": h.url,
                    "cover_url": h.cover_url,
                    "intro": h.intro,
                })
            })
            .collect();
        emit_json(&json!({
            "keyword": args.keyword,
            "hits": hit_items,
            "errors": errors,
        }));
    } else {
        if hits.is_empty() {
            println!("未搜索到与 {:?} 相关的结果", args.keyword);
        } else {
            let mut table = new_table(&["书源", "书名", "作者", "URL"]);
            for h in &hits {
                table.add_row([
                    h.source_id.clone(),
                    truncate(&h.title, 24),
                    truncate(h.author.as_deref().unwrap_or("-"), 14),
                    truncate(&h.url, 48),
                ]);
            }
            println!("{table}");
            println!("共 {} 条结果", hits.len());
        }
        for err in &errors {
            eprintln!(
                "警告 [{}] {}: {}",
                err["source_id"].as_str().unwrap_or("-"),
                err["code"].as_str().unwrap_or("ERR"),
                err["message"].as_str().unwrap_or("")
            );
        }
    }
    Ok(())
}
