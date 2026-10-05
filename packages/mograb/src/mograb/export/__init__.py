# SPDX-License-Identifier: GPL-3.0-only
"""导出子系统：TXT / Markdown / EPUB。

导出器**不得**直接请求网络（规划书 §61）。
"""

from collections.abc import Mapping
from pathlib import Path

from .base import (
    DEFAULT_BOOK_TEMPLATE,
    DEFAULT_CHAPTER_TEMPLATE,
    Exporter,
    ExportResult,
    render_filename,
    safe_path,
    sanitize_component,
)
from .epub import EpubExporter
from .markdown import MarkdownExporter
from .txt import TxtExporter

_EXPORTERS: dict[str, type] = {
    "txt": TxtExporter,
    "markdown": MarkdownExporter,
    "md": MarkdownExporter,
    "epub": EpubExporter,
}


def get_exporter(
    fmt: str,
    *,
    covers_dir: Path | None = None,
    metadata: Mapping[str, str] | None = None,
) -> Exporter:
    """按格式名取导出器实例。

    Args:
        fmt: 格式名。
        covers_dir: 封面所在目录。**只有 EPUB 用得上**（它要把封面嵌进去），
            所以这里显式分派，而不是给 TXT / Markdown 也加一个用不到的形参。
        metadata: EPUB 元数据补充（``[output.metadata]``）。同样是 EPUB 专用。

    Raises:
        ExportError: 不支持的格式。
    """
    from ..errors import ExportError

    key = fmt.lower()
    if key not in _EXPORTERS:
        raise ExportError(
            f"不支持的导出格式: {fmt}",
            details={"format": fmt, "supported": sorted(_EXPORTERS)},
        )
    if key == "epub":
        return EpubExporter(covers_dir=covers_dir, metadata_templates=metadata)
    return _EXPORTERS[key]()


def supported_formats() -> list[str]:
    """已支持的导出格式名。"""
    return ["txt", "markdown", "epub"]


__all__ = [
    "DEFAULT_BOOK_TEMPLATE",
    "DEFAULT_CHAPTER_TEMPLATE",
    "EpubExporter",
    "ExportResult",
    "Exporter",
    "MarkdownExporter",
    "TxtExporter",
    "get_exporter",
    "render_filename",
    "safe_path",
    "sanitize_component",
    "supported_formats",
]
