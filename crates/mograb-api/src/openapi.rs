// SPDX-License-Identifier: GPL-3.0-only
//! OpenAPI 3.x 文档定义（/openapi.json 与 /docs Swagger UI）。

use crate::routers::{books, events, exports, health, search, sources, tasks};
use utoipa::openapi::security::{HttpAuthScheme, HttpBuilder, SecurityScheme};
use utoipa::{Modify, OpenApi};

struct SecurityAddon;

impl Modify for SecurityAddon {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        let components = openapi.components.get_or_insert_with(Default::default);
        components.add_security_scheme(
            "MoGrabToken",
            SecurityScheme::Http(
                HttpBuilder::new()
                    .scheme(HttpAuthScheme::Bearer)
                    .bearer_format("token")
                    .description(Some(
                        "本地 API 令牌，见 data/token。用 `mog server token` 打印。",
                    ))
                    .build(),
            ),
        );
    }
}

#[derive(OpenApi)]
#[openapi(
    info(
        title = "MoGrab API",
        version = env!("CARGO_PKG_VERSION"),
        description = "MoGrab 本地 API —— 书源、搜索、书籍、任务与导出。"
    ),
    modifiers(&SecurityAddon),
    paths(
        health::health,
        sources::list_sources,
        sources::create_source,
        sources::rescan_sources,
        sources::get_source,
        sources::delete_source,
        sources::enable_source,
        sources::disable_source,
        sources::doctor_source,
        search::search,
        search::search_local,
        books::list_books,
        books::get_book,
        books::list_chapters,
        books::get_chapter,
        books::update_book,
        events::all_task_events,
        events::task_events,
        tasks::create_task,
        tasks::list_tasks,
        tasks::get_task,
        tasks::pause_task,
        tasks::resume_task,
        tasks::cancel_task,
        tasks::retry_task,
        exports::create_export,
        exports::get_export,
        exports::list_exports,
    ),
    components(schemas(
        health::HealthOut,
        sources::SourceOut,
        sources::SourceDetail,
        sources::SourceInstallRequest,
        sources::SourceInstallResult,
        sources::RemoveSourceResult,
        search::SearchItem,
        search::SearchError,
        search::SearchResponse,
        search::LocalHit,
        search::LocalSearchResponse,
        books::BookOut,
        books::ChapterSummaryOut,
        books::ChapterDetailOut,
        books::UpdateResult,
        tasks::TaskCreate,
        tasks::TaskOut,
        exports::ExportCreate,
        exports::ExportOut,
    ))
)]
pub struct ApiDoc;
