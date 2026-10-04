# SPDX-License-Identifier: GPL-3.0-only
"""运行时版本号。

版本号的唯一来源是仓库根目录的 ``VERSION`` 文件，由构建后端
（hatchling）在打包时写入包的元数据。运行时从已安装的元数据读取，
因此**不需要**在源码里维护第二份版本号。

三个包（``mograb`` / ``mograb-cli`` / ``mograb-api``）共用同一份 VERSION，
版本号始终一致。

在未安装的源码树中直接导入时（例如把 ``src`` 加进 ``sys.path``），
元数据不存在，此时回退为 ``0.0.0+unknown`` 而不是抛错——
导入一个模块不该因为缺少安装元数据而失败。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

_DIST_NAME = "mograb"
_FALLBACK = "0.0.0+unknown"


def _resolve_version() -> str:
    """从包元数据解析版本号。"""
    try:
        return _package_version(_DIST_NAME)
    except PackageNotFoundError:
        return _FALLBACK


__version__: str = _resolve_version()

__all__ = ["__version__"]
