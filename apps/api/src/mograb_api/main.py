# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 本地 REST API（规划书 §29、§30、§34、§50）。

设计要点：

- 版本化前缀 ``/api/v1``
- 默认仅监听 ``127.0.0.1``（§40）
- REST + SSE（任务进度单向推送，第一版不用 WebSocket）
- 统一错误模型 ``{code, message, details}``（§37）
- 自动生成 OpenAPI 文档，``/docs`` 可访问

启动方式::

    mog server start              # 由 CLI 拉起
    python -m mograb_api          # 直接启动
    mograb-api                    # console script
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mograb import __version__
from mograb.config import AppSettings, get_paths, load_settings
from mograb.logging import configure_logging, get_logger

from .errors import register_exception_handlers
from .routers import books, events, exports, search, sources, tasks

_logger = get_logger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：初始化路径、日志、数据库与任务管理器。"""
    settings: AppSettings = app.state.settings
    paths = get_paths()
    paths.ensure()
    configure_logging(
        level=settings.logging.level,
        log_dir=paths.logs_dir,
        json_output=settings.logging.json_output,
    )
    _logger.info("api.startup", version=__version__, host=settings.server.host)

    # TODO(storage): 初始化 Database、TaskManager，并挂载到 app.state
    yield

    _logger.info("api.shutdown")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """应用工厂。"""
    settings = settings or load_settings()

    app = FastAPI(
        title="MoGrab API",
        version=__version__,
        description="MoGrab 本地 API —— 书源、搜索、书籍、任务与导出。",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

    # 本地 API 的 CORS 策略：仅允许本机来源（Desktop 使用 file:// 或 localhost）
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|file://.*)$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(sources.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(books.router, prefix=API_PREFIX)
    app.include_router(tasks.router, prefix=API_PREFIX)
    app.include_router(exports.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"], summary="健康检查")
    async def health() -> dict[str, str]:
        """健康检查端点（Desktop 启动时轮询，规划书 §34）。"""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


def run() -> None:
    """console script 入口：``mograb-api``。"""
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "mograb_api.main:app",
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
    )


__all__ = ["API_PREFIX", "app", "create_app", "run"]
