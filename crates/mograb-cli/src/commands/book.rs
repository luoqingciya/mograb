// SPDX-License-Identifier: GPL-3.0-only
//! `mog book` —— 书架列表、书籍详情与章节查看。

use crate::common::{
    CliExit, EXIT_NOT_FOUND, EXIT_USAGE, emit_json, fail_err, fail_msg, new_table, open_app,
    truncate,
};
use clap::Args;
use serde_json::{Map, json};

#[derive(Debug, Args)]
pub struct BookArgs {
    /// 书籍 ID（省略则列出书架）
    pub book_id: Option<String>,
    /// 列出全部章节摘要
    #[arg(short = 'c', long)]
    pub chapters: bool,
    /// 查看指定序号（从 1 开始，或按数据库 index）章节正文
    #[arg(long)]
    pub chapter: Option<i64>,
    /// 列出书架时的数量上限
    #[arg(short = 'n', long, default_value_t = 50)]
    pub limit: i64,
    /// 输出 JSON 格式
    #[arg(long)]
    pub json: bool,
}

pub async fn run(args: BookArgs, verbose: bool) -> Result<(), CliExit> {
    if args.chapters && args.chapter.is_some() {
        return Err(fail_msg(
            "USAGE_ERROR",
            "--chapters 与 --chapter 不能同时使用",
            Map::new(),
            EXIT_USAGE,
            args.json,
        ));
    }

    let app = open_app(verbose, args.json).await?;

    let Some(ref book_id) = args.book_id else {
        let books = app
            .books
            .list_all(args.limit.clamp(1, 500), 0)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        app.aclose().await;

        if args.json {
            let items: Vec<_> = books
                .iter()
                .map(|b| {
                    json!({
                        "id": b.id,
                        "source_id": b.source_id,
                        "title": b.title,
                        "author": b.author,
                        "status": b.status.as_str(),
                        "chapter_count": b.chapter_count,
                        "word_count": b.word_count,
                        "url": b.url,
                        "latest_chapter": b.latest_chapter,
                        "updated_at": b.updated_at,
                    })
                })
                .collect();
            emit_json(&items);
        } else if books.is_empty() {
            println!("书架为空");
        } else {
            let mut table = new_table(&["ID", "书名", "作者", "章节", "字数", "书源"]);
            for b in &books {
                table.add_row([
                    b.id.clone(),
                    truncate(&b.title, 24),
                    truncate(b.author.as_deref().unwrap_or("-"), 14),
                    b.chapter_count.to_string(),
                    b.word_count.to_string(),
                    b.source_id.clone(),
                ]);
            }
            println!("{table}");
            println!("共 {} 本书籍", books.len());
        }
        return Ok(());
    };

    let book = match app
        .books
        .get(book_id)
        .await
        .map_err(|e| fail_err(&e, args.json))?
    {
        Some(b) => b,
        None => {
            app.aclose().await;
            return Err(fail_msg(
                "ENTITY_NOT_FOUND",
                &format!("书籍不存在: {book_id}"),
                Map::new(),
                EXIT_NOT_FOUND,
                args.json,
            ));
        }
    };

    if args.chapters {
        let summaries = app
            .chapters
            .list_summaries(&book.id)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        app.aclose().await;
        if args.json {
            emit_json(&summaries);
        } else if summaries.is_empty() {
            println!("《{}》暂无章节", book.title);
        } else {
            let mut table = new_table(&["序号", "标题", "字数", "状态"]);
            for ch in &summaries {
                table.add_row([
                    ch.index.to_string(),
                    truncate(&ch.title, 36),
                    ch.word_count.to_string(),
                    if ch.has_content {
                        "已下载"
                    } else {
                        "待下载"
                    }
                    .to_string(),
                ]);
            }
            println!("{table}");
            println!("《{}》共 {} 章", book.title, summaries.len());
        }
        return Ok(());
    }

    if let Some(index) = args.chapter {
        let ch = app
            .chapters
            .get_by_index(&book.id, index)
            .await
            .map_err(|e| fail_err(&e, args.json))?;
        app.aclose().await;
        let Some(ch) = ch else {
            return Err(fail_msg(
                "ENTITY_NOT_FOUND",
                &format!("章节不存在: book_id={book_id}, index={index}"),
                Map::new(),
                EXIT_NOT_FOUND,
                args.json,
            ));
        };
        if args.json {
            emit_json(&ch);
        } else {
            println!("{} — #{} {}\n", book.title, ch.index, ch.title);
            println!("{}", ch.content.as_deref().unwrap_or("(无正文)"));
        }
        return Ok(());
    }

    app.aclose().await;
    if args.json {
        emit_json(&book);
    } else {
        println!("ID:       {}", book.id);
        println!("书名:     {}", book.title);
        println!("作者:     {}", book.author.as_deref().unwrap_or("-"));
        println!("书源:     {}", book.source_id);
        println!("状态:     {}", book.status.as_str());
        println!("章节数:   {}", book.chapter_count);
        println!("总字数:   {}", book.word_count);
        println!(
            "最新章节: {}",
            book.latest_chapter.as_deref().unwrap_or("-")
        );
        println!("来源 URL: {}", book.url);
        if let Some(intro) = &book.intro
            && !intro.is_empty()
        {
            println!("简介:\n  {intro}");
        }
    }
    Ok(())
}
