# SPDX-License-Identifier: GPL-3.0-only
"""运行目录与路径解析。

数据目录策略
------------

MoGrab 是**绿色便携**的：运行期数据全部放在运行目录下的 ``data/`` 里，
不写系统用户目录。整个程序目录可以直接拷走或删除，系统里不留残留。

``data/`` 与可执行文件同级，不散落到各处。

解析顺序：

1. 环境变量 ``MOGRAB_HOME`` —— 直接指定数据目录，跳过 ``data/`` 子目录
2. 冻结运行时（PyInstaller 打包后）：``<可执行文件所在目录>/data``
3. 开发模式（源码运行）：``<当前工作目录>/data``

第 2 与第 3 条的区别很重要：打包后跟随 exe，开发时跟随 ``cwd``。
从项目根执行 ``uv run mog`` 时数据落在 ``<项目根>/data``，
``.gitignore`` 已排除，不会与仓库的 ``sources/`` 等目录冲突。

目录布局::

    <运行目录>/
    ├── mog.exe  /  _internal/          ← 程序
    └── data/                           ← 数据（可整体备份或删除）
        ├── config.toml
        ├── mograb.db
        ├── cache/
        ├── covers/
        ├── logs/
        ├── exports/
        └── sources/

升级程序时替换程序文件即可，``data/`` 原样保留。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "MoGrab"
ENV_HOME = "MOGRAB_HOME"

DATA_DIRNAME = "data"

# data/ 下的固定名称
CONFIG_FILENAME = "config.toml"
DATABASE_FILENAME = "mograb.db"
CACHE_DIRNAME = "cache"
COVERS_DIRNAME = "covers"
LOGS_DIRNAME = "logs"
EXPORTS_DIRNAME = "exports"
SOURCES_DIRNAME = "sources"

# 需要创建的子目录
_SUBDIRS = (
    CACHE_DIRNAME,
    COVERS_DIRNAME,
    LOGS_DIRNAME,
    EXPORTS_DIRNAME,
    SOURCES_DIRNAME,
)


def is_frozen() -> bool:
    """是否运行在打包后的可执行文件中。"""
    return bool(getattr(sys, "frozen", False))


def runtime_dir() -> Path:
    """程序运行目录。

    打包后是可执行文件所在目录，开发时是当前工作目录。
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def data_dir() -> Path:
    """数据目录 —— 所有运行期数据的落点。

    ``MOGRAB_HOME`` 会直接覆盖它（不再追加 ``data`` 子目录）。
    """
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser().resolve()
    return runtime_dir() / DATA_DIRNAME


@dataclass(frozen=True, slots=True)
class Paths:
    """MoGrab 的全部路径。

    用 :func:`get_paths` 获取实例，不要直接构造 —— 这样 ``MOGRAB_HOME``
    覆盖才会生效。
    """

    root: Path
    config_file: Path
    database: Path
    cache_dir: Path
    covers_dir: Path
    logs_dir: Path
    exports_dir: Path
    sources_dir: Path

    def ensure(self) -> None:
        """创建所有需要的目录。幂等。"""
        self.root.mkdir(parents=True, exist_ok=True)
        for name in _SUBDIRS:
            (self.root / name).mkdir(parents=True, exist_ok=True)


def get_paths(root: Path | None = None) -> Paths:
    """解析当前生效的路径集合。

    Args:
        root: 显式指定数据根目录；为 None 时按 :func:`data_dir` 解析。
    """
    base = (root or data_dir()).expanduser().resolve()
    return Paths(
        root=base,
        config_file=base / CONFIG_FILENAME,
        database=base / DATABASE_FILENAME,
        cache_dir=base / CACHE_DIRNAME,
        covers_dir=base / COVERS_DIRNAME,
        logs_dir=base / LOGS_DIRNAME,
        exports_dir=base / EXPORTS_DIRNAME,
        sources_dir=base / SOURCES_DIRNAME,
    )


__all__ = [
    "APP_NAME",
    "CACHE_DIRNAME",
    "CONFIG_FILENAME",
    "COVERS_DIRNAME",
    "DATABASE_FILENAME",
    "DATA_DIRNAME",
    "ENV_HOME",
    "EXPORTS_DIRNAME",
    "LOGS_DIRNAME",
    "SOURCES_DIRNAME",
    "Paths",
    "data_dir",
    "get_paths",
    "is_frozen",
    "runtime_dir",
]
