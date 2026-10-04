# SPDX-License-Identifier: GPL-3.0-only
"""Desktop 后端 sidecar 的打包入口。

和 CLI 一样，用绝对导入，避免被 PyInstaller 当独立脚本执行时找不到包。
"""

from __future__ import annotations

from mograb_api.main import run

if __name__ == "__main__":
    run()
