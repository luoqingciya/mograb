# SPDX-License-Identifier: GPL-3.0-only
"""CLI 公共工具：命令装饰器、退出码、输出。

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

import asyncio
import functools
import json as _json
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from enum import IntEnum
from typing import Any

import typer
from rich.console import Console

from mograb.app import Application, create_application
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
    人类可读输出由各命令自行用 ``console`` 渲染 —— 因为可读格式依赖具体语义
    （表格 / 树形 / 分组），一个通用函数没法合理推断。
    """
    if json_output:
        console.print_json(_json.dumps(data, ensure_ascii=False, default=str))


def command(func: Callable[..., Coroutine[Any, Any, Any]]) -> Callable[..., Any]:
    """命令装饰器：跑协程，并把领域错误翻成退出码。

    做两件事：

    1. Typer 只认同步回调，这里用 ``asyncio.run`` 把协程跑起来。
       ``functools.wraps`` 会设上 ``__wrapped__``，Typer 通过
       ``inspect.signature`` 仍然能看到原始参数表，所以参数照常声明。
    2. 把 :class:`MoGrabError` 交给 :func:`fail`，统一成错误输出 + 退出码。
       不然每个命令都要写一遍 ``try/except``。

    Ctrl+C 会中断 ``asyncio.run``，KeyboardInterrupt 正常冒到 Typer，
    退出码自然是 130。
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return asyncio.run(func(*args, **kwargs))
        except MoGrabError as exc:
            fail(exc, json_output=bool(kwargs.get("json_output")))
            raise  # fail 内部已 raise typer.Exit，这行只为让类型检查满意

    return wrapper


_verbose = False


def set_verbose(value: bool) -> None:
    """由根命令的 ``--verbose`` 设置。

    用模块级状态而不是让每个命令都收 ``typer.Context``：CLI 一次进程只跑一个
    命令，传一个 Context 参数到十几个命令里反而更啰嗦。
    """
    global _verbose
    _verbose = value


@asynccontextmanager
async def open_app(*, ensure_paths: bool = True) -> AsyncIterator[Application]:
    """打开一个装配好的应用，用完自动收尾。

    只读命令传 ``ensure_paths=False``，免得为了看一眼书源列表就在磁盘上
    建出一堆目录。

    默认把日志压到 WARNING —— 命令行的正常输出是给用户看的，
    夹杂一堆 INFO 日志很难读。``mog -v`` 会放开。
    """
    async with create_application(
        ensure_paths=ensure_paths,
        log_level="INFO" if _verbose else "WARNING",
    ) as app:
        yield app


__all__ = [
    "ExitCode",
    "command",
    "console",
    "emit",
    "err_console",
    "exit_code_for",
    "fail",
    "open_app",
    "set_verbose",
]
