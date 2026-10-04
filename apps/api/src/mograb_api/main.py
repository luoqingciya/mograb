# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 本地 REST API（规划书 §29、§30、§34、§50）。

设计要点：

- 版本化前缀 ``/api/v1``
- 默认仅监听 ``127.0.0.1``（§40）
- REST + SSE（任务进度单向推送，第一版不用 WebSocket）
- 统一错误模型 ``{code, message, details}``（§37）
- 自动生成 OpenAPI 文档，``/docs`` 可访问

各层的装配在 :func:`mograb.app.create_application` —— CLI 用的是同一份，
这里只负责把它挂到 ``app.state`` 上，并在启动时拉起 worker 池。

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
from mograb.app import Application, build_task_manager, create_application
from mograb.config import AppSettings, load_settings
from mograb.domain.task import Task
from mograb.logging import get_logger

from .bus import EventBus
from .errors import register_exception_handlers
from .routers import books, events, exports, search, sources, tasks

_logger = get_logger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """装配应用、拉起 worker 池，退出时收尾。"""
    settings: AppSettings = app.state.settings
    bus = EventBus()

    async def publish_task(task: Task) -> None:
        """任务状态变了就广播一条，SSE 那边在等。"""
        await bus.publish(
            {
                "event": "task",
                "task_id": task.id,
                "type": task.type.value,
                "status": task.status.value,
                "book_id": task.book_id,
                "total": task.total,
                "completed": task.completed,
                "failed": task.failed,
                "error_code": task.error_code,
                "error_message": task.error_message,
            }
        )

    async with create_application(settings=settings) as application:
        # 换掉默认的 TaskManager：加上广播钩子，并启动 worker 池。
        # start() 同时会做一次孤儿任务恢复。
        application.task_manager = build_task_manager(application, on_status_change=publish_task)
        await application.task_manager.start()

        app.state.application = application
        app.state.bus = bus

        _logger.info(
            "api.startup",
            version=__version__,
            host=settings.server.host,
            port=settings.server.port,
        )
        try:
            yield
        finally:
            _logger.info("api.shutdown")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """应用工厂。"""
    resolved = settings or load_settings()

    app = FastAPI(
        title="MoGrab API",
        version=__version__,
        description="MoGrab 本地 API —— 书源、搜索、书籍、任务与导出。",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved

    # 本地 API 的 CORS：只允许本机来源（Desktop 走 file:// 或 localhost）
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(https?://(127\.0\.0\.1|localhost)(:\d+)?|file://.*)$",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # 顺序有讲究：`/tasks/events` 和 `/tasks/{task_id}` 段数一样，
    # events 必须先注册，否则 "events" 会被当成任务 ID。
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(sources.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(books.router, prefix=API_PREFIX)
    app.include_router(tasks.router, prefix=API_PREFIX)
    app.include_router(exports.router, prefix=API_PREFIX)

    @app.get("/health", tags=["meta"], summary="健康检查")
    async def health() -> dict[str, str]:
        """健康检查端点（Desktop 启动时轮询，规划书 §34）。"""
        return {"status": "ok", "version": __version__}

    return app


app = create_app()


def run() -> None:
    """console script 入口：``mograb-api``。

    直接传 app 对象而不是 ``"mograb_api.main:app"`` 字符串 —— 后者靠运行时
    导入，PyInstaller 静态分析发现不了，打出来的 exe 会在启动时报找不到模块。
    """
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_config=None,
    )


__all__ = ["API_PREFIX", "Application", "app", "create_app", "run"]
