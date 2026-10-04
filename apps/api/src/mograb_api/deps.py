# SPDX-License-Identifier: GPL-3.0-only
"""FastAPI 依赖。

应用实例在 ``lifespan`` 里装配好、挂在 ``app.state`` 上，这里只是取出来。
装配逻辑本身在 :func:`mograb.app.create_application` —— CLI 用的是同一份。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from mograb.app import Application
from mograb.config import AppSettings


def get_application(request: Request) -> Application:
    """取当前的应用实例。"""
    application = getattr(request.app.state, "application", None)
    if application is None:  # pragma: no cover - lifespan 正常跑就不会走到
        raise RuntimeError("应用尚未装配：lifespan 没有执行？")
    return application


def get_settings(request: Request) -> AppSettings:
    """取当前生效的配置。"""
    return request.app.state.settings  # type: ignore[no-any-return]


ApplicationDep = Annotated[Application, Depends(get_application)]
SettingsDep = Annotated[AppSettings, Depends(get_settings)]

__all__ = ["ApplicationDep", "SettingsDep", "get_application", "get_settings"]
