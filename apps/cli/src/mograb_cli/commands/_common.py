# SPDX-License-Identifier: GPL-3.0-only
"""CLI 公共工具：退出码、输出、错误处理。

退出码约定（规划书 §31 要求「退出码」但未定义，此处补齐）::

    0    成功
    1    一般错误（未分类异常）
    2    参数/用法错误（由 Typer 处理）
    3    未找到（书源 / 书籍 / 任务不存在）
    4    校验失败（书源 Schema / 内容校验）
    5    网络错误
    130  用户中断（Ctrl+C）
"""

from __future__ import annotations

import json as _json
from enum import IntEnum
from typing import Any

import typer
from rich.console import Console

from mograb.errors import (
    ContentValidationError,
    EntityNotFoundError,
    MoGrabError,
    NetworkError,
    SourceNotFoundError,
    SourceSchemaError,
    TaskNotFoundError,
)

console = Console()
err_console = Console(stderr=True)


class ExitCode(IntEnum):
    """CLI 退出码。"""

    OK = 0
    ERROR = 1
    USAGE = 2
    NOT_FOUND = 3
    VALIDATION = 4
    NETWORK = 5
    INTERRUPTED = 130


def exit_code_for(error: BaseException) -> int:
    """把异常映射为退出码。"""
    if isinstance(error, (EntityNotFoundError, SourceNotFoundError, TaskNotFoundError)):
        return ExitCode.NOT_FOUND
    if isinstance(error, (SourceSchemaError, ContentValidationError)):
        return ExitCode.VALIDATION
    if isinstance(error, NetworkError):
        return ExitCode.NETWORK
    return ExitCode.ERROR


def fail(error: MoGrabError, *, json_output: bool = False) -> None:
    """统一错误输出并退出。"""
    if json_output:
        err_console.print_json(_json.dumps({"error": error.to_dict()}))
    else:
        err_console.print(f"[red]错误[/red] [{error.code}] {error.message}")
        if error.details:
            err_console.print(f"  [dim]{error.details}[/dim]")
    raise typer.Exit(code=exit_code_for(error))


def emit(data: Any, *, json_output: bool = False) -> None:
    """输出结构化结果。

    约定：``emit`` **只在** ``json_output=True`` 时输出。
    人类可读输出由各命令自行用 ``console`` 渲染——因为可读格式依赖具体语义
    （表格 / 树形 / 分组），无法由一个通用函数合理推断。
    """
    if json_output:
        console.print_json(_json.dumps(data, ensure_ascii=False, default=str))


__all__ = ["ExitCode", "console", "emit", "err_console", "exit_code_for", "fail"]
