# SPDX-License-Identifier: GPL-3.0-only
"""控制台输出的编码处理。

为什么需要这个模块
------------------

**打包后的可执行文件会无视编码相关的环境变量。** 实测（PyInstaller onedir，
Windows + 中文区域设置）：

======================  ==========
环境                    实际输出
======================  ==========
（默认）                 GBK
``PYTHONUTF8=1``         GBK
``PYTHONIOENCODING``     GBK
``PYTHONLEGACYWINDOWSSTDIO=0``  GBK
======================  ==========

而开发态（``uv run``）是 UTF-8 —— 于是**只有用户拿到的包是坏的**，
本地怎么测都测不出来。表现为 ``--json`` 产出的不是合法 JSON
（JSON 规范要求 UTF-8），管道给别的工具也是乱码。

所以这件事必须在代码里显式做，不能指望环境变量。
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["force_utf8_stdio"]


def force_utf8_stdio() -> None:
    """把被重定向的 stdout / stderr 固定成 UTF-8。

    **只在输出不是终端时才改。** 直接连控制台时 CPython 走宽字符 API
    （``WriteConsoleW``），中文本来就显示正常；硬改成 UTF-8 反而会让
    cp936 控制台显示乱码。而被管道或重定向时，Python 按控制台代码页编码，
    中文 Windows 上就是 GBK —— 那才是要修的场景。

    幂等，重复调用无害。
    """
    for stream in (sys.stdout, sys.stderr):
        if _is_terminal(stream):
            continue
        reconfigure: Any = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # errors="replace"：输出永远不该因为某个字符编不出来就崩掉
            reconfigure(encoding="utf-8", errors="replace")


def _is_terminal(stream: object) -> bool:
    """判断是不是连着终端。拿不到判断结果时按「是终端」处理。

    保守取值：认不出来就**不改**编码。控制台场景本来就正确，
    改错了反而把好的搞坏。
    """
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return True
    try:
        return bool(isatty())
    except (ValueError, OSError):
        # 流已关闭之类的情况
        return True
