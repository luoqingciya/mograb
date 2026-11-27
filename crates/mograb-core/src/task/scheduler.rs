// SPDX-License-Identifier: GPL-3.0-only
//! 下载调度与增量更新。

use crate::content::normalizer::count_words;
use crate::content::pipeline::ContentPipeline;
use crate::covers::CoverStore;
use crate::domain::book::Book;
use crate::domain::chapter::{Chapter, compute_content_hash, normalize_url};
use crate::domain::enums::BookStatus;
use crate::domain::ids::new_id;
use crate::domain::source::{InstalledSource, SourceSpec};
use crate::errors::{MoGrabError, MoGrabResult};
use crate::export::base::Exporter;
use crate::source::engine::{ChapterDraft, SourceEngine};
use crate::storage::repository::{BookRepository, ChapterRepository, SourceRepository};
use async_trait::async_trait;
use chrono::Utc;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;
use tracing::{error, info, warn};

#[async_trait]
pub trait ProgressHook: Send + Sync {
    async fn on_progress(&self, done: usize, total: usize);
}

#[derive(Debug, Clone, Default)]
pub struct ChapterDiff {
    pub new: Vec<ChapterDraft>,
    pub changed: Vec<ChapterDraft>,
    pub missing: Vec<String>,
    pub unchanged: Vec<ChapterDraft>,
}

impl ChapterDiff {
    pub fn to_download(&self) -> Vec<ChapterDraft> {
        let mut v = Vec::with_capacity(self.new.len() + self.changed.len());
        v.extend(self.new.iter().cloned());
        v.extend(self.changed.iter().cloned());
        v
    }
}

fn candidate_keys(
    source_chapter_id: Option<&str>,
    url: &str,
    index: i64,
    title: &str,
) -> Vec<String> {
    let mut keys = Vec::new();
    if let Some(sid) = source_chapter_id
        && !sid.is_empty()
    {
        keys.push(format!("sid:{sid}"));
    }
    if !url.is_empty() {
        keys.push(format!("url:{}", normalize_url(url)));
    }
    if keys.is_empty() {
        keys.push(format!("idx:{index}:{title}"));
    }
    keys
}

pub fn compute_chapter_diff(local: &[Chapter], remote: &[ChapterDraft]) -> ChapterDiff {
    let mut local_index: HashMap<String, usize> = HashMap::new();
    for (idx, ch) in local.iter().enumerate() {
        for key in candidate_keys(
            ch.source_chapter_id.as_deref(),
            &ch.url,
            ch.index,
            &ch.title,
        ) {
            local_index.entry(key).or_insert(idx);
        }
    }

    let mut matched_local: HashSet<usize> = HashSet::new();
    let mut diff = ChapterDiff::default();

    for draft in remote {
        let keys = candidate_keys(
            draft.source_chapter_id.as_deref(),
            &draft.url,
            draft.index,
            &draft.title,
        );
        let mut found_idx = None;
        for key in &keys {
            if let Some(&idx) = local_index.get(key)
                && !matched_local.contains(&idx)
            {
                found_idx = Some(idx);
                break;
            }
        }

        let Some(idx) = found_idx else {
            diff.new.push(draft.clone());
            continue;
        };

        matched_local.insert(idx);
        let existing = &local[idx];
        if existing.title != draft.title
            || normalize_url(&existing.url) != normalize_url(&draft.url)
        {
            diff.changed.push(draft.clone());
        } else {
            diff.unchanged.push(draft.clone());
        }
    }

    for (idx, ch) in local.iter().enumerate() {
        if !matched_local.contains(&idx) {
            diff.missing.push(ch.identity_key());
        }
    }

    diff
}

#[derive(Debug, Clone)]
pub struct DownloadPlan {
    pub book_id: String,
    pub total: usize,
    pub to_download: Vec<ChapterDraft>,
    pub skipped: usize,
    pub missing: Vec<String>,
    pub latest_chapter: Option<String>,
}

impl DownloadPlan {
    pub fn is_noop(&self) -> bool {
        self.to_download.is_empty()
    }
}

#[derive(Debug, Clone)]
pub struct ChapterFailure {
    pub title: String,
    pub url: String,
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct DownloadReport {
    pub plan: DownloadPlan,
    pub downloaded: usize,
    pub failed: usize,
    pub failures: Vec<ChapterFailure>,
    pub export_path: Option<PathBuf>,
}

impl DownloadReport {
    pub fn ok(&self) -> bool {
        self.failed == 0
    }

    pub fn is_noop(&self) -> bool {
        self.plan.is_noop()
    }
}

pub struct DownloadScheduler {
    engine: Arc<SourceEngine>,
    sources: Arc<dyn SourceRepository>,
    books: Arc<dyn BookRepository>,
    chapters: Arc<dyn ChapterRepository>,
    pipeline: Option<Arc<ContentPipeline>>,
    exporter: Option<Arc<dyn Exporter>>,
    covers: Option<Arc<CoverStore>>,
}

impl DownloadScheduler {
    pub fn new(
        engine: Arc<SourceEngine>,
        sources: Arc<dyn SourceRepository>,
        books: Arc<dyn BookRepository>,
        chapters: Arc<dyn ChapterRepository>,
        pipeline: Option<Arc<ContentPipeline>>,
        exporter: Option<Arc<dyn Exporter>>,
        covers: Option<Arc<CoverStore>>,
    ) -> Self {
        Self {
            engine,
            sources,
            books,
            chapters,
            pipeline,
            exporter,
            covers,
        }
    }

    pub async fn ensure_book(&self, source_id: &str, book_url: &str) -> MoGrabResult<Book> {
        let source = self.require_source(source_id).await?;
        let draft = self.engine.fetch_book(&source.spec, book_url).await?;
        let now = Utc::now();

        if let Some(mut existing) = self
            .books
            .get_by_identity(source_id, &draft.source_book_id)
            .await?
        {
            existing.url = draft.url;
            existing.title = draft.title;
            existing.author = draft.author;
            existing.intro = draft.intro;
            existing.cover_url = draft.cover_url;
            existing.latest_chapter = draft.latest_chapter;
            existing.status = draft.status;
            for (k, v) in draft.extra {
                let json_val = match v {
                    Some(s) => Value::String(s),
                    None => Value::Null,
                };
                existing.metadata.insert(k, json_val);
            }
            existing.updated_at = now;
            self.books.save(&existing).await?;
            return self.ensure_cover(existing, &source).await;
        }

        let mut metadata = Map::new();
        for (k, v) in draft.extra {
            metadata.insert(
                k,
                match v {
                    Some(s) => Value::String(s),
                    None => Value::Null,
                },
            );
        }

        let book = Book {
            id: new_id("book"),
            source_id: source_id.to_string(),
            source_book_id: draft.source_book_id,
            url: draft.url,
            title: draft.title,
            author: draft.author,
            intro: draft.intro,
            language: None,
            cover_url: draft.cover_url,
            cover_path: None,
            status: draft.status,
            latest_chapter: draft.latest_chapter,
            word_count: 0,
            chapter_count: 0,
            created_at: now,
            updated_at: now,
            metadata,
        };
        self.books.save(&book).await?;
        info!(book_id = %book.id, source_id, "task.book_registered");
        self.ensure_cover(book, &source).await
    }

    async fn ensure_cover(&self, mut book: Book, source: &InstalledSource) -> MoGrabResult<Book> {
        let Some(ref covers) = self.covers else {
            return Ok(book);
        };
        let Some(relative) = covers
            .ensure(&book, Some(&source.spec.permissions.network))
            .await
        else {
            return Ok(book);
        };
        book.cover_path = Some(relative);
        self.books.save(&book).await?;
        Ok(book)
    }

    pub async fn plan_update(&self, book_id: &str) -> MoGrabResult<DownloadPlan> {
        let (book, source) = self.load(book_id).await?;
        self.build_plan(&book, &source).await
    }

    pub async fn run(
        &self,
        book_id: &str,
        on_progress: Option<Arc<dyn ProgressHook>>,
        cancel: Option<CancellationToken>,
        export_to: Option<&Path>,
    ) -> MoGrabResult<DownloadReport> {
        let (book, source) = self.load(book_id).await?;
        let mut book = self.ensure_cover(book, &source).await?;
        let plan = self.build_plan(&book, &source).await?;

        if plan.is_noop() {
            info!(book_id, chapters = plan.total, "task.already_up_to_date");
            return Ok(DownloadReport {
                plan,
                downloaded: 0,
                failed: 0,
                failures: Vec::new(),
                export_path: None,
            });
        }

        let (chapters, failures) = self
            .download_chapters(
                &source.spec,
                &book.id,
                &plan.to_download,
                on_progress,
                cancel,
            )
            .await?;

        let mut downloaded = 0usize;
        if !chapters.is_empty() {
            self.chapters.save_many(&chapters).await?;
            downloaded = chapters.len();
        }

        self.refresh_book_stats(&mut book, &plan).await?;

        let export_path = if let (Some(target), Some(exporter)) = (export_to, &self.exporter) {
            let all_chapters = self.chapters.list_by_book(&book.id).await?;
            let res = exporter.export(&book, &all_chapters, target).await?;
            Some(res.path)
        } else {
            None
        };

        let failed = failures.len();
        info!(
            book_id,
            downloaded,
            failed,
            skipped = plan.skipped,
            "task.download_finished"
        );

        Ok(DownloadReport {
            plan,
            downloaded,
            failed,
            failures,
            export_path,
        })
    }

    async fn load(&self, book_id: &str) -> MoGrabResult<(Book, InstalledSource)> {
        let book = self.books.get(book_id).await?.ok_or_else(|| {
            MoGrabError::entity_not_found(
                format!("书籍不存在: {book_id}"),
                json!({"book_id": book_id}),
            )
        })?;
        let source = self.require_source(&book.source_id).await?;
        if !source.is_usable() {
            return Err(MoGrabError::source_unsupported_with(
                format!("书源当前不可用: {}", book.source_id),
                json!({
                    "source_id": book.source_id,
                    "enabled": source.enabled,
                    "health": source.health.as_str(),
                }),
            ));
        }
        Ok((book, source))
    }

    async fn require_source(&self, source_id: &str) -> MoGrabResult<InstalledSource> {
        self.sources.get(source_id).await?.ok_or_else(|| {
            MoGrabError::source_not_found(
                format!("书源未安装: {source_id}"),
                json!({"source_id": source_id}),
            )
        })
    }

    async fn build_plan(
        &self,
        book: &Book,
        source: &InstalledSource,
    ) -> MoGrabResult<DownloadPlan> {
        let drafts = self.engine.fetch_chapters(&source.spec, &book.url).await?;
        let local = self.chapters.list_by_book(&book.id).await?;
        let diff = compute_chapter_diff(&local, &drafts);

        if !diff.missing.is_empty() {
            warn!(
                book_id = %book.id,
                count = diff.missing.len(),
                "task.chapters_missing_remotely"
            );
        }

        let latest_chapter = drafts.last().map(|d| d.title.clone());
        Ok(DownloadPlan {
            book_id: book.id.clone(),
            total: drafts.len(),
            to_download: diff.to_download(),
            skipped: diff.unchanged.len(),
            missing: diff.missing,
            latest_chapter,
        })
    }

    async fn download_chapters(
        &self,
        spec: &SourceSpec,
        book_id: &str,
        drafts: &[ChapterDraft],
        on_progress: Option<Arc<dyn ProgressHook>>,
        cancel: Option<CancellationToken>,
    ) -> MoGrabResult<(Vec<Chapter>, Vec<ChapterFailure>)> {
        let semaphore = Arc::new(Semaphore::new(spec.network.concurrency.max(1)));
        let total = drafts.len();
        let done = Arc::new(AtomicUsize::new(0));
        let cancel_tok = cancel.unwrap_or_default();

        let mut join_set: JoinSet<MoGrabResult<Result<Chapter, ChapterFailure>>> = JoinSet::new();

        for draft in drafts.iter().cloned() {
            let sem = Arc::clone(&semaphore);
            let engine = Arc::clone(&self.engine);
            let pipeline = self.pipeline.clone();
            let spec_cloned = spec.clone();
            let book_id_owned = book_id.to_string();
            let done_counter = Arc::clone(&done);
            let progress_cb = on_progress.clone();
            let tok = cancel_tok.clone();

            join_set.spawn(async move {
                let _permit = tokio::select! {
                    _ = tok.cancelled() => return Err(MoGrabError::task_cancelled("下载已取消")),
                    p = sem.acquire_owned() => p.expect("download semaphore closed"),
                };

                // 拿到信号量之后、发请求之前再查取消
                if tok.is_cancelled() {
                    return Err(MoGrabError::task_cancelled("下载已取消"));
                }

                let outcome = match fetch_single_chapter(
                    &engine,
                    pipeline.as_ref(),
                    &spec_cloned,
                    &book_id_owned,
                    &draft,
                )
                .await
                {
                    Ok(ch) => Ok(ch),
                    Err(err) => {
                        error!(url = %draft.url, error = %err, "task.chapter_failed");
                        Err(ChapterFailure {
                            title: draft.title.clone(),
                            url: draft.url.clone(),
                            code: err.code().to_string(),
                            message: err.message().to_string(),
                        })
                    }
                };

                let current_done = done_counter.fetch_add(1, Ordering::SeqCst) + 1;
                if let Some(ref cb) = progress_cb {
                    cb.on_progress(current_done, total).await;
                }

                Ok(outcome)
            });
        }

        let mut chapters = Vec::new();
        let mut failures = Vec::new();

        while let Some(res) = join_set.join_next().await {
            match res {
                Ok(Ok(Ok(ch))) => chapters.push(ch),
                Ok(Ok(Err(fail))) => failures.push(fail),
                Ok(Err(cancel_err @ MoGrabError::TaskCancelled { .. })) => {
                    join_set.abort_all();
                    return Err(cancel_err);
                }
                Ok(Err(other)) => return Err(other),
                Err(join_err) => {
                    if !join_err.is_cancelled() {
                        return Err(MoGrabError::task(
                            format!("下载任务异常退出: {join_err}"),
                            json!({}),
                        ));
                    }
                }
            }
        }

        chapters.sort_by_key(|c| c.index);
        Ok((chapters, failures))
    }

    async fn refresh_book_stats(&self, book: &mut Book, plan: &DownloadPlan) -> MoGrabResult<()> {
        let (count, words) = self.chapters.stats_by_book(&book.id).await?;
        book.chapter_count = count;
        book.word_count = words;
        if let Some(ref latest) = plan.latest_chapter {
            book.latest_chapter = Some(latest.clone());
        }
        book.updated_at = Utc::now();
        self.books.save(book).await
    }
}

async fn fetch_single_chapter(
    engine: &SourceEngine,
    pipeline: Option<&Arc<ContentPipeline>>,
    spec: &SourceSpec,
    book_id: &str,
    draft: &ChapterDraft,
) -> MoGrabResult<Chapter> {
    let raw = engine
        .fetch_content(spec, &draft.url, Some(draft.index))
        .await?;
    let now = Utc::now();

    let (text, word_count, content_hash) = if let Some(pipe) = pipeline {
        let pipe_clone = Arc::clone(pipe);
        let processed = tokio::task::spawn_blocking(move || pipe_clone.process(&raw, None))
            .await
            .map_err(|e| MoGrabError::task(e.to_string(), json!({})))??;
        (processed.text, processed.word_count, processed.content_hash)
    } else {
        let t = raw.trim().to_string();
        let wc = count_words(&t) as i64;
        let ch = compute_content_hash(&t);
        (t, wc, ch)
    };

    Ok(Chapter {
        id: new_id("chap"),
        book_id: book_id.to_string(),
        source_chapter_id: draft.source_chapter_id.clone(),
        title: draft.title.clone(),
        url: draft.url.clone(),
        index: draft.index,
        content: Some(text),
        content_hash: Some(content_hash),
        word_count,
        created_at: now,
        updated_at: now,
    })
}

#[allow(dead_code)]
fn _unused_status_guard(_: BookStatus) {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_chapter_diff_candidate_keys() {
        let now = Utc::now();
        let local = vec![Chapter {
            id: "c1".into(),
            book_id: "b1".into(),
            source_chapter_id: Some("s1".into()),
            title: "第一章".into(),
            url: "https://example.com/ch/1?utm_source=x".into(),
            index: 0,
            content: Some("body".into()),
            content_hash: Some("h".into()),
            word_count: 4,
            created_at: now,
            updated_at: now,
        }];
        // 即使远程不再返回 source_chapter_id，靠规范化 URL 候选键仍能匹配为 unchanged
        let remote = vec![
            ChapterDraft {
                title: "第一章".into(),
                url: "https://example.com/ch/1".into(),
                index: 0,
                source_chapter_id: None,
            },
            ChapterDraft {
                title: "第二章".into(),
                url: "https://example.com/ch/2".into(),
                index: 1,
                source_chapter_id: Some("s2".into()),
            },
        ];
        let diff = compute_chapter_diff(&local, &remote);
        assert_eq!(diff.unchanged.len(), 1);
        assert_eq!(diff.new.len(), 1);
        assert!(diff.changed.is_empty());
        assert!(diff.missing.is_empty());
    }
}
