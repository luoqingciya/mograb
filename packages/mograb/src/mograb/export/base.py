# SPDX-License-Identifier: GPL-3.0-only
"""导出层公共契约（规划书 §26、§28、§40）。

包含：

- :class:`Exporter` 协议 —— 所有导出器实现同一接口
- :func:`render_filename` —— 文件名模板渲染（§28）
- :func:`safe_path` —— 路径安全校验（§40.6/§40.7）

**安全约束**：所有写盘路径必须先经 :func:`safe_path` 规范化，
拒绝路径穿越、保留字与非法字符。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..domain.book import Book
from ..domain.chapter import Chapter
from ..domain.enums import ExportFormat
from ..errors import UnsafePathError

# Windows / POSIX 非法字符
_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
# Windows 保留设备名
_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)
_TEMPLATE_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")

DEFAULT_BOOK_TEMPLATE = "{{author}} - {{title}}"
DEFAULT_CHAPTER_TEMPLATE = "{{index}}. {{title}}"


@dataclass(slots=True)
class ExportResult:
    """导出结果。"""

    book_id: str
    format: ExportFormat
    path: Path
    size_bytes: int
    chapter_count: int
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class Exporter(Protocol):
    """导出器协议（规划书 §26）。

    注意：导出器**不得**直接发起网络请求（§61 架构边界）。
    """

    format: ExportFormat

    async def export(self, book: Book, chapters: list[Chapter], target: Path) -> ExportResult:
        """把书籍导出到 ``target``。"""
        ...


# ---------------------------------------------------------------------------
# 文件名与路径
# ---------------------------------------------------------------------------
def book_variables(book: Book) -> dict[str, str]:
    """书名等变量，供 ``{{...}}`` 模板使用（§28）。"""
    return {
        "title": book.title or "untitled",
        "author": book.author or "unknown",
        "source_id": book.source_id,
        "source_book_id": book.source_book_id,
        "latest_chapter": book.latest_chapter or "",
        "status": book.status.value,
    }


def render_template(template: str, values: Mapping[str, str]) -> str:
    """把 ``{{var}}`` 换成值。认不出的变量换成空串。

    **不做文件名清洗** —— 那是 :func:`render_filename` 的事。元数据模板
    里可以有空格和标点。
    """
    return _TEMPLATE_VAR_RE.sub(lambda match: values.get(match.group(1), ""), template)


def render_filename(template: str, *, book: Book, chapter: Chapter | None = None) -> str:
    """渲染文件名模板。

    支持变量（§28）::

        {{title}} {{author}} {{source_id}} {{latest_chapter}} {{status}}
        {{index}} {{chapter_title}}（章节模板专用）
    """
    values = book_variables(book)
    if chapter is not None:
        values["index"] = str(chapter.index)
        values["chapter_title"] = chapter.title
        values["chapter_id"] = chapter.id

    return sanitize_component(render_template(template, values))


def sanitize_component(name: str) -> str:
    """清洗单个路径组件：去非法字符、去首尾空白与点、处理保留名。"""
    cleaned = _ILLEGAL_CHARS_RE.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        cleaned = "untitled"
    stem = cleaned.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    # 限制长度，避免超出文件系统上限
    return cleaned[:150]


def safe_path(base_dir: Path, *components: str) -> Path:
    """在 ``base_dir`` 下安全地构造路径。

    与 :func:`sanitize_component` 的分工：

    - :func:`sanitize_component` 是**宽容**的：把非法字符替换掉，
      适合处理来自书籍元数据（标题、作者）的字符串。
    - :func:`safe_path` 是**严格**的：对明显危险的组件（``..`` / ``.`` /
      路径分隔符 / NUL）直接拒绝，适合处理可能来自用户输入或书源的路径片段。

    调用方若希望宽容处理，应先自行调用 :func:`sanitize_component`。

    Raises:
        UnsafePathError: 组件危险，或结果路径逃逸出 ``base_dir``。
    """
    base = base_dir.resolve()
    candidate = base
    for component in components:
        _assert_component_safe(component)
        candidate = candidate / component
    resolved = candidate.resolve()
    if not _is_within(resolved, base):
        raise UnsafePathError(
            f"路径越界: {resolved} 不在 {base} 之下",
            details={"base": str(base), "candidate": str(resolved)},
        )
    return resolved


def _assert_component_safe(component: str) -> None:
    """拒绝明显危险的路径组件。"""
    if component in ("", ".", ".."):
        raise UnsafePathError(f"非法路径组件: {component!r}", details={"component": component})
    if "/" in component or "\\" in component or "\x00" in component:
        raise UnsafePathError(
            f"路径组件不得包含分隔符: {component!r}",
            details={"component": component},
        )


def _is_within(path: Path, parent: Path) -> bool:
    """判断 ``path`` 是否位于 ``parent`` 之下（含相等）。"""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


__all__ = [
    "DEFAULT_BOOK_TEMPLATE",
    "DEFAULT_CHAPTER_TEMPLATE",
    "ExportResult",
    "Exporter",
    "render_filename",
    "safe_path",
    "sanitize_component",
]
