# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab Core Engine。

MoGrab 是一个开源、API-First、可扩展的小说获取与电子书整理工具。

架构边界（规划书 §61，必须长期保持）::

    Source      └── 规则
    Network     └── 网络
    Parser      └── 解析
    Content     └── 清洗
    Task        └── 调度
    Storage     └── 持久化
    Exporter    └── 导出
    API         └── 对外能力
    CLI         └── 命令行交互
    Desktop     └── 图形交互

禁止模块之间互相越权，例如：

- Exporter ❌ 直接请求网络
- Source   ❌ 直接操作数据库
- Desktop  ❌ 直接修改 DB
- Parser   ❌ 决定下载任务
"""

from __future__ import annotations

# 版本号来自包元数据（唯一来源为仓库根的 VERSION 文件）
from ._version import __version__
from .config import AppSettings, Paths, get_paths, load_settings
from .domain import Book, Chapter, SourceCapability, SourceSpec, Task, TaskStatus
from .errors import MoGrabError

__license__ = "GPL-3.0-only"

__all__ = [
    "AppSettings",
    "Book",
    "Chapter",
    "MoGrabError",
    "Paths",
    "SourceCapability",
    "SourceSpec",
    "Task",
    "TaskStatus",
    "__license__",
    "__version__",
    "get_paths",
    "load_settings",
]
