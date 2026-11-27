// SPDX-License-Identifier: GPL-3.0-only
//! Content 模块入口。

pub mod cleaner;
pub mod normalizer;
pub mod pipeline;

pub use cleaner::clean_text;
pub use normalizer::{count_words, normalize_text, split_paragraphs};
pub use pipeline::{ContentPipeline, ContentPolicy, ProcessedContent};
