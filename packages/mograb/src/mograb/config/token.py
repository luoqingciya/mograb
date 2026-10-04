# SPDX-License-Identifier: GPL-3.0-only
"""本地 API 的访问令牌。

为什么需要
----------

API 只监听 ``127.0.0.1``，但**监听回环不等于安全**。浏览器里的任意页面都能向
``127.0.0.1:48721`` 发请求 —— 简单请求（表单编码、``text/plain``）连预检都不
触发，CORS 只能挡住**读响应**，挡不住副作用。也就是说，用户随便打开一个网页，
那个页面就能让 MoGrab 开始下载、删书源、建导出任务。

所以每个请求都要带令牌。没有令牌的请求直接 401。

令牌放在哪
----------

放在数据目录下的 ``token`` 文件里，**不放进 config.toml**：

- ``config.toml`` 是给人看的，会被备份、会被贴进 issue、会在机器之间拷贝。
  密钥混在里面就会跟着走。
- 分开之后可以单独设权限（POSIX 上 0600），配置文件仍然可以随便共享。
- ``config.toml`` 的 schema 是 ``extra="forbid"``，塞一个机器管理的字段进去
  只会让「用户手改配置」这件事更容易出错。

令牌是**机器生成、机器读取**的，用户不需要知道它的内容 —— 除非要用 curl
手工调接口，那种情况下 ``mog server token`` 会打印出来。

生成规则
--------

``secrets.token_urlsafe(32)``：256 位熵，43 个 URL 安全字符。
用 ``secrets`` 而不是 ``random`` —— 后者是可预测的伪随机，拿来生成凭据是错的。

写入规则
--------

「有就复用，没有就生成」，用 ``O_CREAT | O_EXCL`` 独占创建来仲裁：
谁先创建成功谁的令牌生效，后来者读到的是同一份。这样重启 server 不会让
已连接的客户端失效，CLI 和 Desktop 也各自独立地拿到同一个值。

**为什么不是「写临时文件再原子替换」。** 那个做法在 POSIX 上很干净，但 Windows
上 ``os.replace`` 遇到目标文件正被另一个句柄打开时会直接抛 PermissionError ——
而并发读恰恰是这里的常态。独占创建不需要替换，也就没有这个问题。
代价是文件创建到写入之间有个极短的「存在但为空」的窗口，靠下面的
:func:`_read_until_settled` 等过去。
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from .paths import Paths, get_paths

TOKEN_BYTES = 32
"""令牌的随机字节数。256 位熵，暴力猜解不现实。"""

# POSIX 权限：只有属主可读写。Windows 上没有对应概念，靠用户目录本身的 ACL。
_CREATE_MODE = 0o600

# 「存在但为空」的等待窗口。写一个 44 字节的文件是微秒级的事，
# 留一秒只是为了容忍调度抖动和杀软扫描。
# 这个时长只在**异常路径**上付出（正常路径文件不存在，独占创建立刻成功）。
_SETTLE_TIMEOUT_SECONDS = 1.0
_SETTLE_INTERVAL_SECONDS = 0.01


def read_token(paths: Paths | None = None) -> str | None:
    """读已有的令牌；没有或为空时返回 ``None``。

    内容首尾的空白会去掉 —— 手工编辑过也不至于带上换行。
    """
    resolved = paths or get_paths()
    path = resolved.token_file
    if not path.is_file():
        return None
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:  # pragma: no cover - 文件在 is_file 之后被删
        return None
    return token or None


def ensure_token(paths: Paths | None = None) -> str:
    """拿到令牌，没有就生成一个写下来。幂等。

    并发调用时返回同一个值 —— 见模块开头的写入规则。
    """
    resolved = paths or get_paths()
    path = resolved.token_file

    existing = read_token(resolved)
    if existing is not None:
        return existing

    token = generate_token()
    if _create_exclusive(path, token):
        return token

    # 别人抢先建了。它可能刚创建、内容还没落盘，等它写完再读。
    settled = _read_until_settled(resolved)
    if settled is not None:
        return settled

    # 文件存在、但是空的，而且等了这么久还是空的 —— 上一个写它的进程多半
    # 在「创建」和「写入」之间挂了。这种文件没有任何价值，清掉重来一次，
    # 否则每个调用方都会各自生成一份，谁都对不上。
    try:
        path.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - 被别的句柄占着，交给下次调用
        return token

    if _create_exclusive(path, token):
        return token
    settled = _read_until_settled(resolved)
    return settled if settled is not None else token


def generate_token() -> str:
    """生成一个新令牌（不落盘）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def _create_exclusive(path: Path, token: str) -> bool:
    """独占创建并写入。文件已存在时返回 ``False``，不覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _CREATE_MODE)
    except FileExistsError:
        return False

    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    return True


def _read_until_settled(paths: Paths) -> str | None:
    """等到读出一个非空令牌，或者超时。"""
    deadline = time.monotonic() + _SETTLE_TIMEOUT_SECONDS
    while True:
        token = read_token(paths)
        if token is not None:
            return token
        if time.monotonic() >= deadline:
            return None
        time.sleep(_SETTLE_INTERVAL_SECONDS)


__all__ = ["TOKEN_BYTES", "ensure_token", "generate_token", "read_token"]
