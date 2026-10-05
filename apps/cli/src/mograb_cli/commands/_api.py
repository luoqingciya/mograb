# SPDX-License-Identifier: GPL-3.0-only
"""本地 API 客户端。

CLI 大部分命令直接调 Core（进程内，简单也快），但**控制一个正在跑的
server** 必须走 API —— 任务状态在 server 进程的内存里，改数据库它不知道。

所以 ``mog task pause/resume/cancel/retry`` 这类命令走这里。
连不上 server 时给一句人话，而不是抛一个 httpx 的堆栈。

鉴权
----

server 要求 ``Authorization: Bearer <token>``。令牌由 server 启动时生成在
``data/token``，这里用 :func:`~mograb.config.ensure_token` 读 ——
**读不到就现生成一个**：那种情况说明 server 还没起过，接下来必然连不上，
生成的令牌也不会有害；而一旦 server 起过，两边读的就是同一份。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from mograb.config import AppSettings, ensure_token, get_paths

from ._common import console

TIMEOUT_SECONDS = 10.0


def api_base_url(settings: AppSettings) -> str:
    """本地 API 的根地址。"""
    return f"http://{settings.server.host}:{settings.server.port}/api/v1"


def auth_headers() -> dict[str, str]:
    """带令牌的请求头。

    ``settings.server.auth`` 关掉时不带 —— 但那样 server 也不校验，
    带不带都一样，所以这里不读配置，避免两处判断不一致。
    """
    return {"Authorization": f"Bearer {ensure_token(get_paths())}"}


class ApiUnavailable(Exception):
    """本地 server 没在跑。"""


class ApiUnauthorized(Exception):
    """令牌不对。

    正常路径下不该出现 —— CLI 和 server 读的是同一个 ``data/token``。
    真撞上了通常是「令牌文件被换过而 server 还是老进程」，
    或者两个进程在同一瞬间各自首次生成（见 token 模块的说明）。
    """


async def request(
    settings: AppSettings,
    method: str,
    path: str,
    *,
    json: Any = None,
) -> Any:
    """调一次本地 API。

    Raises:
        ApiUnavailable: 连不上。调用方负责转成友好的提示。
        ApiUnauthorized: server 拒绝了这个令牌。
        httpx.HTTPStatusError: 服务端返回了其他错误状态。
    """
    url = f"{api_base_url(settings)}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, json=json, headers=auth_headers())
    except httpx.HTTPError as exc:
        raise ApiUnavailable(str(exc)) from exc

    if response.status_code == 401:
        raise ApiUnauthorized(response.text)

    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


async def is_running(settings: AppSettings) -> bool:
    """server 是否在跑（探一次健康检查）。

    ``/health`` 不需要令牌，所以这里不带 —— 探测和鉴权是两件事。
    """
    url = f"http://{settings.server.host}:{settings.server.port}/health"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def explain_unavailable(settings: AppSettings) -> None:
    """打印一句人话，说明为什么这条命令需要 server。"""
    console.print("[yellow]本地 API Server 没在运行[/yellow]")
    console.print(
        f"[dim]这条命令要控制一个正在跑的任务，得先起 server："
        f"`mog server start`（默认 {settings.server.host}:{settings.server.port}）[/dim]"
    )


def explain_unauthorized() -> None:
    """令牌对不上时给一句可操作的提示。"""
    console.print("[red]API 令牌校验失败[/red]")
    console.print(
        "[dim]CLI 和 server 读的是同一个 data/token，正常不会不一致。"
        "多半是 server 启动之后令牌文件被换过 —— 重启 server 即可。[/dim]"
    )


__all__ = [
    "ApiUnauthorized",
    "ApiUnavailable",
    "api_base_url",
    "auth_headers",
    "explain_unauthorized",
    "explain_unavailable",
    "is_running",
    "request",
]


def parse_sse_data(line: str) -> dict[str, Any] | None:
    """解析一行 SSE，取出任务事件。

    SSE 一帧长这样（``sse_starlette`` 用 CRLF）：

        event: task
        id: task_xxx
        data: {"task_id": "...", "status": "running", ...}

    只看 ``data:`` 行。**心跳帧要被丢掉** —— 它只有 ``task_id``、没有
    ``status``，当成事件推出去会让调用方渲染出一个空行。

    Returns:
        事件字典；这一行不是有效的事件数据时返回 ``None``。
    """
    if not line.startswith("data:"):
        return None
    payload = line[len("data:") :].strip()
    if not payload:
        return None
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict) or "status" not in event:
        return None
    return event


async def stream_task_events(
    settings: AppSettings, task_id: str | None = None
) -> AsyncIterator[dict[str, Any]]:
    """订阅任务事件流（SSE）。

    ``task_id`` 为空就订阅全局流（所有任务）。

    **不用 ``EventSource``** —— 它设不了请求头，而令牌只能走
    ``Authorization``（见 ADR-0004）。所以这里用 httpx 读流、手写解析，
    和桌面端 ``renderer/sse.ts`` 的做法一致。

    Yields:
        每个事件的字典。心跳帧会被过滤掉 —— 它没有 ``status`` 字段。

    Raises:
        ApiUnavailable: 连不上，或流中途断了。
        ApiUnauthorized: 令牌不对。
    """
    path = f"/tasks/{task_id}/events" if task_id else "/tasks/events"
    url = f"{api_base_url(settings)}{path}"

    try:
        # timeout=None：长连接，不能按普通请求的超时算
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream("GET", url, headers=auth_headers()) as response,
        ):
            if response.status_code == 401:
                raise ApiUnauthorized(response.text)
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload:
                    continue
                event = json.loads(payload)
                # 心跳帧只有 task_id，没有 status
                if isinstance(event, dict) and "status" in event:
                    yield event
    except httpx.HTTPError as exc:
        raise ApiUnavailable(str(exc)) from exc
