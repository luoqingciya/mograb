# SPDX-License-Identifier: GPL-3.0-only
"""本地 API 客户端。

CLI 大部分命令直接调 Core（进程内，简单也快），但**控制一个正在跑的
server** 必须走 API —— 任务状态在 server 进程的内存里，改数据库它不知道。

所以 ``mog task pause/resume/cancel/retry`` 这类命令走这里。
连不上 server 时给一句人话，而不是抛一个 httpx 的堆栈。
"""

from __future__ import annotations

from typing import Any

import httpx

from mograb.config import AppSettings

from ._common import console

TIMEOUT_SECONDS = 10.0


def api_base_url(settings: AppSettings) -> str:
    """本地 API 的根地址。"""
    return f"http://{settings.server.host}:{settings.server.port}/api/v1"


class ApiUnavailable(Exception):
    """本地 server 没在跑。"""


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
        httpx.HTTPStatusError: 服务端返回了错误状态。
    """
    url = f"{api_base_url(settings)}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.request(method, url, json=json)
    except httpx.HTTPError as exc:
        raise ApiUnavailable(str(exc)) from exc

    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


async def is_running(settings: AppSettings) -> bool:
    """server 是否在跑（探一次健康检查）。"""
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


__all__ = [
    "ApiUnavailable",
    "api_base_url",
    "explain_unavailable",
    "is_running",
    "request",
]
