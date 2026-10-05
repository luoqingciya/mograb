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
from collections.abc import Callable, MutableMapping
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


class _SinkHandler(logging.Handler):
    """把渲染好的日志行交给调用方给的回调。

    用于让日志和 Rich 进度条共用同一个 console —— 详见
    :func:`configure_logging` 的 ``console_sink``。
    """

    def __init__(self, sink: Callable[[str], None]) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sink(self.format(record))
        except Exception:
            self.handleError(record)


def configure_logging(
    *,
    level: str = "INFO",
    log_dir: Path | None = None,
    json_output: bool = False,
    console: bool = True,
    console_sink: Callable[[str], None] | None = None,
) -> None:
    """初始化日志系统（幂等）。

    Args:
        level: 根日志级别。
        log_dir: 若提供，则写入轮转文件 ``app.log`` / ``task.log`` / ``source.log``。
        json_output: 是否输出 JSON 行（适合机器解析）。
        console: 是否输出到 stderr。
        console_sink: 控制台日志的落点。给了就用它代替写 stderr。

            **这是给进度条场景准备的。** 默认直接写 stderr，而 Rich 的进度条
            在 stdout 上不断重画当前行 —— 两个写入者不协调，日志会糊在进度条
            中间（实测：``339/2036 0:06:06<日志>attempt=1 delay=0.85``）。
            调用方传一个「往它自己的 Rich console 打」的函数进来，
            Rich 就知道有 Live 区域，会把日志排在进度条**上方**。

            核心库不依赖 Rich，所以这里是回调而不是 Console 对象。
    """
    global _configured
    if _configured:
        return

    handlers: list[logging.Handler] = []
    if console:
        handlers.append(
            _SinkHandler(console_sink) if console_sink else logging.StreamHandler(sys.stderr)
        )

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

    # **必须 force=True。** 不带它的话，只要根 logger 上已经有别的 handler，
    # basicConfig 就**什么都不做** —— 整个日志配置静默失效，一个 handler
    # 都装不上，而且不报错。写测试时撞到过：pytest 会先挂自己的 handler，
    # 于是这里装的控制台通道完全没生效。
    #
    # 「配了等于没配，还不报错」正是这个项目反复在防的那类问题。
    logging.basicConfig(level=level, handlers=handlers, format="%(message)s", force=True)

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
