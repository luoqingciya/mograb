# SPDX-License-Identifier: GPL-3.0-only
"""日志子系统。

注意：本包名为 ``mograb.logging``，与标准库 ``logging`` 同名。
包内所有模块一律使用绝对导入（``import logging``）以确保拿到标准库模块。
"""

from .setup import (
    SENSITIVE_KEYS,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    redact_headers,
)

__all__ = [
    "SENSITIVE_KEYS",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "redact_headers",
]
