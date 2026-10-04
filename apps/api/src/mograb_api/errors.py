# SPDX-License-Identifier: GPL-3.0-only
"""API 错误模型与异常映射（规划书 §37）。

把领域层的 :class:`MoGrabError` 层次映射为稳定的 HTTP 响应：

.. code-block:: json

    {
      "code": "SOURCE_PARSE_FAILED",
      "message": "...",
      "details": {}
    }
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mograb.errors import (
    AuthError,
    ContentValidationError,
    EntityNotFoundError,
    ExportError,
    HttpStatusError,
    MoGrabError,
    NetworkError,
    SourceNotFoundError,
    SourceSchemaError,
    SourceUnsupportedError,
    StorageError,
    TaskError,
    TaskNotFoundError,
    TaskParameterError,
)

# 错误类型 -> HTTP 状态码
# 顺序有意义：先匹配到子类。TaskParameterError 必须排在 TaskError 前面，
# 否则会被后者拦成 409。
_STATUS_MAP: tuple[tuple[type[MoGrabError], int], ...] = (
    (AuthError, 401),
    (EntityNotFoundError, 404),
    (SourceNotFoundError, 404),
    (TaskNotFoundError, 404),
    (SourceSchemaError, 422),
    (SourceUnsupportedError, 422),
    (ContentValidationError, 422),
    (ExportError, 422),
    (TaskParameterError, 400),
    (HttpStatusError, 502),
    (NetworkError, 502),
    (StorageError, 500),
    (TaskError, 409),
)


def status_for(error: MoGrabError) -> int:
    """把领域错误映射为 HTTP 状态码。"""
    for error_type, status in _STATUS_MAP:
        if isinstance(error, error_type):
            return status
    return 500


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(MoGrabError)
    async def _handle_mograb_error(_request: Request, exc: MoGrabError) -> JSONResponse:
        headers = {}
        if isinstance(exc, AuthError):
            # RFC 9110 要求 401 带 WWW-Authenticate，客户端据此知道该用哪种方案
            headers["WWW-Authenticate"] = 'Bearer realm="MoGrab"'
        return JSONResponse(
            status_code=status_for(exc), content=exc.to_dict(), headers=headers or None
        )

    @app.exception_handler(ValueError)
    async def _handle_value_error(_request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "INVALID_ARGUMENT",
                "message": str(exc),
                "details": {},
            },
        )


__all__ = ["register_exception_handlers", "status_for"]
