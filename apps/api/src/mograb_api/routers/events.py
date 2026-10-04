# SPDX-License-Identifier: GPL-3.0-only
"""SSE 事件流（规划书 §30）。

规划书只定义了单任务事件流 ``GET /tasks/{id}/events``；
但 Desktop 的任务页需要**全局**实时更新，因此本实现额外提供
``GET /tasks/events`` 聚合流（对应评估报告 P2-01）。

事件格式::

    event: progress
    data: {"task_id":"task_123","completed":520,"total":1000,"speed":3.4}

第一版不需要 WebSocket —— SSE 对单向进度通知已足够。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15
"""心跳间隔；防止中间代理断开空闲连接。"""


async def _event_stream(
    request: Request, *, task_id: str | None = None
) -> AsyncIterator[dict[str, str]]:
    """事件流生成器。

    骨架实现：以固定间隔发送心跳，直到客户端断开。
    接入 TaskManager 后，改为从内部事件总线（asyncio.Queue）消费。
    """
    seq = 0
    while True:
        if await request.is_disconnected():
            break
        seq += 1
        yield {
            "event": "heartbeat",
            "id": str(seq),
            "data": json.dumps({"task_id": task_id, "seq": seq}, ensure_ascii=False),
        }
        await asyncio.sleep(HEARTBEAT_SECONDS)


@router.get("/tasks/{task_id}/events", summary="单任务事件流（SSE）")
async def task_events(task_id: str, request: Request) -> EventSourceResponse:
    """订阅单个任务的进度事件。"""
    # TODO(task): 校验任务存在性（接入 TaskManager 后启用）
    _ = task_id
    return EventSourceResponse(_event_stream(request, task_id=task_id))


@router.get("/tasks/events", summary="全局任务事件流（SSE）")
async def all_task_events(request: Request) -> EventSourceResponse:
    """订阅所有任务的事件（Desktop 任务页使用）。"""
    return EventSourceResponse(_event_stream(request))


__all__: list[str] = ["router"]
