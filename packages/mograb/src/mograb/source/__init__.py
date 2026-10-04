# SPDX-License-Identifier: GPL-3.0-only
"""书源子系统：加载、校验、执行声明式书源。"""

from .engine import BookDraft, ChapterDraft, Fetcher, ResponseLike, SearchResult, SourceEngine
from .extractor import Document, Extractor, ExtractResult, extract_many, extract_one
from .loader import dump_source_yaml, load_source_dict, load_source_file, write_source_file
from .request import TemplateContext, build_request, find_variables, render
from .transformer import apply_transforms, apply_transforms_many
from .validator import Diagnostic, LintReport, Severity, lint

__all__ = [
    "BookDraft",
    "ChapterDraft",
    "Diagnostic",
    "Document",
    "ExtractResult",
    "Extractor",
    "Fetcher",
    "LintReport",
    "ResponseLike",
    "SearchResult",
    "Severity",
    "SourceEngine",
    "TemplateContext",
    "apply_transforms",
    "apply_transforms_many",
    "build_request",
    "dump_source_yaml",
    "extract_many",
    "extract_one",
    "find_variables",
    "lint",
    "load_source_dict",
    "load_source_file",
    "render",
    "write_source_file",
]
