# SPDX-License-Identifier: GPL-3.0-only
"""CLI 打包入口。

为什么不直接用 ``mograb_cli/__main__.py``：那个文件里是相对导入
（``from .main import app``），被 PyInstaller 当独立脚本执行时没有包上下文，
会报 "attempted relative import with no known parent package"。
这里用绝对导入，两种运行方式都能用。
"""

from __future__ import annotations

from mograb_cli.main import app

if __name__ == "__main__":
    app()
