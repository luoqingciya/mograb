# SPDX-License-Identifier: GPL-3.0-only
"""API 鉴权（规划书 §40、评估报告 P2-02）。

威胁模型
--------

API 只监听 ``127.0.0.1``，但**回环地址不是安全边界**。浏览器里的任意页面
都能向 ``127.0.0.1:48721`` 发请求，而且下面这类请求连 CORS 预检都不触发：

    POST /api/v1/tasks
    Content-Type: text/plain

    {"type":"download_book", ...}

CORS 只约束**能不能读到响应**，不阻止请求送达。所以光靠 CORS 的话，
用户随手打开一个恶意网页，那个页面就能让 MoGrab 下载、删书源、建导出任务。

令牌怎么传
----------

只认一种方式::

    Authorization: Bearer <token>

**为什么不做查询参数。** ``EventSource`` 不能设请求头，所以 SSE 用查询参数
传令牌是常见做法。但令牌会因此出现在访问日志里（uvicorn 会把整个 path
连同 query 记下来），而日志是会被翻、会被贴的。宁可让桌面端改用 fetch
流式读取 SSE，也不多留一条会泄漏凭据的路径。

**为什么不认 Cookie。** 渲染进程的页面来源是 ``file://``，Cookie 在这种来源下
的域规则很别扭；而且 Cookie 是浏览器自动携带的，等于把 CSRF 防线交回去。

哪些端点要令牌
--------------

六个业务 router 全要，通过 router 级依赖挂上。``/health`` 保持开放 ——
它是用来探「有没有实例在跑」的，Desktop 和 ``mog server status`` 都靠它，
而且它只暴露「在跑」和版本号。``/docs`` / ``/openapi.json`` 也开放：
在浏览器里打开 Swagger UI 没法带请求头，而接口本身是公开文档，
真正要动手操作时照样得过令牌这一关。
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from mograb.errors import AuthError

# auto_error=False：缺头时返回 None 而不是让 FastAPI 抛自己的 403。
# 我们要的是统一错误模型（{code, message, details}），不是 FastAPI 默认的形状。
_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="MoGrabToken",
    description="本地 API 令牌，见 data/token。用 `mog server token` 打印。",
)

# 统一提示：不要把「没带令牌」和「令牌不对」区分开。
# 区分了等于告诉攻击者「猜的方向对，只是值错了」。
_MESSAGE = "缺少或无效的 API 令牌"


async def require_token(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> None:
    """校验 ``Authorization: Bearer <token>``。不通过就抛 :class:`AuthError`。

    用 :func:`secrets.compare_digest` 而不是 ``==``：后者一旦比较出第一个
    不同的字符就返回，比较耗时随「前缀匹配长度」变化，理论上可以被逐字节
    猜出来。这里是本地场景、影响有限，但正确写法本来就是一行的事。
    """
    settings = request.app.state.settings
    if not settings.server.auth:
        return

    expected: str | None = getattr(request.app.state, "token", None)
    if not expected:  # pragma: no cover - lifespan 正常跑就不会走到
        raise RuntimeError("令牌未初始化：lifespan 没有执行？")

    if credentials is None or not secrets.compare_digest(credentials.credentials, expected):
        raise AuthError(
            _MESSAGE,
            details={"scheme": "Bearer", "hint": "用 `mog server token` 查看令牌"},
        )


TokenDep = Depends(require_token)

__all__ = ["TokenDep", "require_token"]
