// SPDX-License-Identifier: GPL-3.0-only
//! SSE 事件流（全局与单任务）。

use crate::AppState;
use axum::extract::{Path, State};
use axum::response::sse::{Event, KeepAlive, Sse};
use futures::stream::Stream;
use serde_json::json;
use std::convert::Infallible;
use std::time::Duration;
use tokio::sync::broadcast::error::RecvError;

pub const HEARTBEAT_SECONDS: u64 = 15;

fn make_event_stream(
    state: AppState,
    task_id_filter: Option<String>,
) -> impl Stream<Item = Result<Event, Infallible>> {
    async_stream_impl(state, task_id_filter)
}

fn async_stream_impl(
    state: AppState,
    task_id_filter: Option<String>,
) -> impl Stream<Item = Result<Event, Infallible>> {
    let rx = state.bus.subscribe();
    let ticker = tokio::time::interval(Duration::from_secs(HEARTBEAT_SECONDS));
    // First tick fires immediately; skip it so heartbeat waits 15s
    futures::stream::unfold(
        (rx, ticker, task_id_filter, true),
        |(mut rx, mut ticker, filter, first_tick)| async move {
            if first_tick {
                ticker.tick().await;
            }
            loop {
                tokio::select! {
                    _ = ticker.tick() => {
                        let hb = Event::default()
                            .event("heartbeat")
                            .data(json!({"task_id": filter}).to_string());
                        return Some((Ok(hb), (rx, ticker, filter, false)));
                    }
                    msg = rx.recv() => {
                        match msg {
                            Ok(val) => {
                                let ev_task_id = val.get("task_id").and_then(|v| v.as_str()).unwrap_or("");
                                if let Some(ref wanted) = filter
                                    && ev_task_id != wanted
                                {
                                    continue;
                                }
                                let event_name = val
                                    .get("event")
                                    .and_then(|v| v.as_str())
                                    .unwrap_or("task")
                                    .to_string();
                                let ev = Event::default()
                                    .event(event_name)
                                    .id(ev_task_id)
                                    .data(val.to_string());
                                return Some((Ok(ev), (rx, ticker, filter, false)));
                            }
                            Err(RecvError::Lagged(_)) => continue,
                            Err(RecvError::Closed) => return None,
                        }
                    }
                }
            }
        },
    )
}

#[utoipa::path(
    get,
    path = "/api/v1/tasks/events",
    tag = "events",
    summary = "全局任务事件流（SSE）",
    responses((status = 200, description = "text/event-stream")),
    security(("MoGrabToken" = []))
)]
pub async fn all_task_events(
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    Sse::new(make_event_stream(state, None)).keep_alive(KeepAlive::default())
}

#[utoipa::path(
    get,
    path = "/api/v1/tasks/{task_id}/events",
    tag = "events",
    summary = "单任务事件流（SSE）",
    params(("task_id" = String, Path, description = "任务 ID")),
    responses((status = 200, description = "text/event-stream")),
    security(("MoGrabToken" = []))
)]
pub async fn task_events(
    Path(task_id): Path<String>,
    State(state): State<AppState>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    Sse::new(make_event_stream(state, Some(task_id))).keep_alive(KeepAlive::default())
}
