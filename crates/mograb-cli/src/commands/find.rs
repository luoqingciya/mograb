// SPDX-License-Identifier: GPL-3.0-only
//! `mog find` —— 全文检索本地已下载章节正文。

use crate::common::{CliExit, emit_json, fail_err, new_table, open_app, truncate};
use clap::Args;
use serde_json::json;

#[derive(Debug, Args)]
pub struct FindArgs {
    /// 检索关键词
    pub keyword: String,
    /// 限定单本书籍 ID
    #[arg(short = 'b', long)]
    pub book: Option<String>,
    /// 返回上限
    #[arg(short = 'n', long, default_value_t = 50)]
    pub limit: i64,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: FindArgs, verbose: bool) -> Result<(), CliExit> {
    let app = open_app(verbose, args.json).await?;
    let hits = app
        .chapters
        .search_content(
            &args.keyword,
            args.book.as_deref(),
            args.limit.clamp(1, 500),
        )
        .await
        .map_err(|e| fail_err(&e, args.json))?;
    app.aclose().await;

    if args.json {
        let hit_items: Vec<_> = hits
            .iter()
            .map(|h| {
                json!({
                    "book_id": h.book_id,
                    "book_title": h.book_title,
                    "chapter_id": h.chapter_id,
                    "chapter_title": h.chapter_title,
                    "chapter_index": h.chapter_index,
                    "snippet": h.snippet,
                })
            })
            .collect();
        emit_json(&json!({
            "keyword": args.keyword,
            "count": hit_items.len(),
            "hits": hit_items,
        }));
    } else if hits.is_empty() {
        println!("未在本地章节中找到包含 {:?} 的内容", args.keyword);
    } else {
        let mut table = new_table(&["书籍", "章节", "摘要"]);
        for h in &hits {
            table.add_row([
                truncate(&h.book_title, 20),
                format!("#{} {}", h.chapter_index, truncate(&h.chapter_title, 24)),
                truncate(&h.snippet, 48),
            ]);
        }
        println!("{table}");
        println!("共命中 {} 处", hits.len());
    }
    Ok(())
}
