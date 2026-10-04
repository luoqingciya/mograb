# SPDX-License-Identifier: GPL-3.0-only
"""脚本共用的控制台编码处理。

**为什么这里和 ``mograb.console`` 有一份重复实现。**

``scripts/`` 下的工具刻意保持独立 —— ``version.py`` 要在 ``uv sync`` 之前
就能跑（它是版本号的引导工具），所以不能依赖核心库。这个文件把原先散在
三个脚本里的三份拷贝收敛成一份。

两边的逻辑必须一致：只在**输出被重定向**时改 UTF-8。
详见 ``mograb/console.py`` 的模块文档，那里有完整的来龙去脉。
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["force_utf8_stdio"]


def force_utf8_stdio() -> None:
    """把被重定向的 stdout / stderr 固定成 UTF-8。幂等。"""
    for stream in (sys.stdout, sys.stderr):
        if _is_terminal(stream):
            continue
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _is_terminal(stream: object) -> bool:
    """认不出来就按「是终端」处理 —— 不改编码比改错安全。"""
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return True
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return True
