# SPDX-License-Identifier: GPL-3.0-only
"""SSE 事件流（规划书 §30）。

规划书只定义了单任务事件流 ``GET /tasks/{id}/events``；但 Desktop 的任务页
需要**全局**实时更新，所以额外提供 ``GET /tasks/events`` 聚合流。

第一版不用 WebSocket —— 单向进度通知，SSE 够用。

注意路由顺序：``/tasks/events`` 和 ``/tasks/{task_id}`` 段数相同，
所以这个 router 必须在 tasks router **之前**注册，否则 ``events``
会被当成一个任务 ID。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..bus import EventBus

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
"""心跳间隔。防中间代理把空闲连接掐掉。"""


async def _stream(
    bus: EventBus, request: Request, *, task_id: str | None
) -> AsyncIterator[dict[str, str]]:
    """从总线读事件往下推。"""
    async with bus.subscribe() as queue:
        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield {"event": "heartbeat", "data": json.dumps({"task_id": task_id})}
                continue

            if task_id is not None and event.get("task_id") != task_id:
                continue

            yield {
                "event": str(event.get("event", "message")),
                "id": str(event.get("task_id", "")),
                "data": json.dumps(event, ensure_ascii=False, default=str),
            }


def _bus(request: Request) -> EventBus:
    bus: EventBus | None = getattr(request.app.state, "bus", None)
    if bus is None:  # pragma: no cover - lifespan 正常跑就不会走到
        raise RuntimeError("事件总线未初始化")
    return bus


@router.get("/tasks/events", summary="全局任务事件流（SSE）")
async def all_task_events(request: Request) -> EventSourceResponse:
    """订阅所有任务的事件。Desktop 的任务页用这个。"""
    return EventSourceResponse(_stream(_bus(request), request, task_id=None))


@router.get("/tasks/{task_id}/events", summary="单任务事件流（SSE）")
async def task_events(task_id: str, request: Request) -> EventSourceResponse:
    """订阅单个任务的进度事件。"""
    return EventSourceResponse(_stream(_bus(request), request, task_id=task_id))


__all__: list[str] = ["router"]
