# SPDX-License-Identifier: GPL-3.0-only
"""导出子系统：TXT / Markdown / EPUB。

导出器**不得**直接请求网络（规划书 §61）。
"""

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


def get_exporter(fmt: str) -> Exporter:
    """按格式名取导出器实例。

    Raises:
        ExportError: 不支持的格式。
    """
    from ..errors import ExportError

    try:
        return _EXPORTERS[fmt.lower()]()
    except KeyError as exc:
        raise ExportError(
            f"不支持的导出格式: {fmt}",
            details={"format": fmt, "supported": sorted(_EXPORTERS)},
        ) from exc


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
