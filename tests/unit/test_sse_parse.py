# SPDX-License-Identifier: GPL-3.0-only
"""SSE 事件解析的测试。

盯的是 ``mog task watch`` 的传输层 —— 对应 API 的 ``GET /tasks/events``
和 ``GET /tasks/{id}/events``。

**不用 ``EventSource``**：它设不了请求头，而令牌只能走 ``Authorization``
（ADR-0004）。所以这里手写解析，也就得自己盯着。
"""

from __future__ import annotations

import json

import pytest

from mograb_cli.commands._api import parse_sse_data

pytestmark = pytest.mark.unit


def _frame(event: str, payload: dict) -> list[str]:
    """造一帧 SSE 的原始行。"""
    return [
        f"event: {event}",
        f"id: {payload.get('task_id', '')}",
        f"data: {json.dumps(payload, ensure_ascii=False)}",
    ]


class TestParseSseData:
    def test_解析出事件(self) -> None:
        payload = {"task_id": "task_1", "status": "running", "completed": 3, "total": 10}

        event = parse_sse_data(_frame("task", payload)[2])

        assert event == payload

    def test_忽略_event_和_id_行(self) -> None:
        """一帧有三行，只有 data 那行是内容。"""
        assert parse_sse_data("event: task") is None
        assert parse_sse_data("id: task_1") is None

    def test_丢掉心跳帧(self) -> None:
        """**这条是关键。**

        心跳只有 ``task_id``、没有 ``status``。当成事件推出去的话，
        ``mog task watch`` 会渲染出一个内容全空的进度行，而心跳每 15 秒
        就来一次 —— 长时间盯着一个任务会刷一屏空白。
        """
        heartbeat = json.dumps({"task_id": "task_1"})

        assert parse_sse_data(f"data: {heartbeat}") is None

    def test_空_data_行(self) -> None:
        assert parse_sse_data("data:") is None
        assert parse_sse_data("data:   ") is None

    def test_坏_JSON_不炸(self) -> None:
        """网络抖动、代理截断都可能送来半截 JSON。"""
        assert parse_sse_data("data: {不是 json") is None

    def test_JSON_不是对象(self) -> None:
        assert parse_sse_data("data: [1, 2, 3]") is None
        assert parse_sse_data('data: "文本"') is None

    def test_中文不转义(self) -> None:
        """错误信息是中文的，别解出来一堆 \\uXXXX。"""
        payload = {"task_id": "t", "status": "failed", "error_message": "网络错误"}

        event = parse_sse_data(f"data: {json.dumps(payload, ensure_ascii=False)}")

        assert event is not None
        assert event["error_message"] == "网络错误"

    def test_行尾有回车也能解析(self) -> None:
        """``sse_starlette`` 用 CRLF。"""
        payload = {"task_id": "t", "status": "running"}

        event = parse_sse_data(f"data: {json.dumps(payload)}\r")

        assert event is not None
        assert event["status"] == "running"
