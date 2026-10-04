# SPDX-License-Identifier: GPL-3.0-only
"""CLI 命令实现。

约定：命令函数只负责「参数解析 + 输出格式化」，
业务逻辑一律委托给 :mod:`mograb` 核心库或本地 API。
"""

from . import (
    book,
    cache,
    config,
    download,
    export,
    logs,
    search,
    server,
    source,
    task,
    update,
)

__all__ = [
    "book",
    "cache",
    "config",
    "download",
    "export",
    "logs",
    "search",
    "server",
    "source",
    "task",
    "update",
]
