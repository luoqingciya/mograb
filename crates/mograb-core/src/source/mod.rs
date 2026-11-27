// SPDX-License-Identifier: GPL-3.0-only
//! Source 模块入口。

pub mod engine;
pub mod extractor;
pub mod fixture;
pub mod loader;
pub mod request;
pub mod transformer;
pub mod validator;

pub use engine::{
    BookDraft, ChapterDraft, FetchOptions, FetchResponse, Fetcher, SearchResult, SourceEngine,
};
pub use extractor::{Document, ExtractResult, extract, extract_many, extract_one};
pub use fixture::{
    CASES_FILENAME, CaseResult, FIXTURES_DIRNAME, FixtureCase, cases_path, load_cases, run_cases,
};
pub use loader::{dump_source_yaml, load_source_file, load_source_str, write_source_file};
pub use request::{
    DEFAULT_USER_AGENT, RenderedRequest, TemplateContext, build_request, find_variables, render,
};
pub use transformer::{apply_transforms, apply_transforms_many, url_join};
pub use validator::{Diagnostic, LintReport, Severity, lint};
