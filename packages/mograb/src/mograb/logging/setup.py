# SPDX-License-Identifier: GPL-3.0-only
"""结构化日志（规划书 §36）。

要求：

- 结构化字段：``timestamp`` / ``level`` / ``logger`` / ``task_id`` /
  ``source_id`` / ``book_id`` / ``chapter_id`` / ``request_id`` / ``message``
- 分流输出：``app.log`` / ``task.log`` / ``source.log``
- **脱敏**：``Cookie`` / ``Authorization`` / ``Set-Cookie`` / ``X-Api-Key``
  一律替换为 ``***``（规划书 §40）
- 轮转与保留策略（规划书未定义，此处补齐）：单文件 10MB，保留 5 份

实现基于 ``structlog``。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict

# 需要脱敏的头部/字段名（大小写不敏感）
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api_key",
        "apikey",
        "token",
        "password",
        "secret",
    }
)

_REDACTED = "***"

# 日志轮转参数
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def redact_headers(headers: MutableMapping[str, Any] | None) -> dict[str, Any]:
    """对头部字典做脱敏，返回新字典。"""
    if not headers:
        return {}
    return {
        key: (_REDACTED if key.lower() in SENSITIVE_KEYS else value)
        for key, value in headers.items()
    }


def _redact_processor(_logger: Any, _method: str, event_dict: EventDict) -> EventDict:
    """structlog 处理器：递归脱敏敏感字段。"""
    return _redact_mapping(dict(event_dict))


def _redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            result[key] = _REDACTED
        elif isinstance(value, dict):
            result[key] = _redact_mapping(value)
        else:
            result[key] = value
    return result


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    json_output: bool = False,
    console: bool = True,
) -> None:
    """初始化日志系统（幂等）。

    Args:
        level: 根日志级别。
        log_dir: 若提供，则写入轮转文件 ``app.log`` / ``task.log`` / ``source.log``。
        json_output: 是否输出 JSON 行（适合机器解析）。
        console: 是否输出到 stderr。
    """
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = []
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        for name in ("app.log", "task.log", "source.log"):
            handler = logging.handlers.RotatingFileHandler(
                log_dir / name,
                maxBytes=MAX_BYTES,
                backupCount=BACKUP_COUNT,
                encoding="utf-8",
            )
            handlers.append(handler)

    logging.basicConfig(level=level, handlers=handlers, format="%(message)s")

    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_output
        else structlog.dev.ConsoleRenderer(colors=console)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            _redact_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """获取绑定 logger。"""
    return structlog.get_logger(name)


def bind_context(**kwargs: Any) -> None:
    """把上下文（task_id / source_id / book_id ...）绑定到当前协程。"""
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """清除协程上下文。"""
    structlog.contextvars.clear_contextvars()


__all__ = [
    "BACKUP_COUNT",
    "MAX_BYTES",
    "SENSITIVE_KEYS",
    "bind_context",
    "clear_context",
    "configure_logging",
    "get_logger",
    "redact_headers",
]
