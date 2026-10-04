# SPDX-License-Identifier: GPL-3.0-only
"""正文规范化（规划书 §21）。

规范化目标：把「能读」的文本变成「一致、可 diff、可排版」的文本。

规则：

- 行内连续空白折叠为单个空格
- 去除行首行尾空白
- 中文段落之间的单换行 → 保留；连续空行压缩为最多一个空行
- 全角空格（U+3000）转半角空格
- 统一换行符为 ``\\n``
- 段落切分（供 EPUB 生成 ``<p>``）

规范化是**幂等**的：``normalize(normalize(x)) == normalize(x)``。
"""

from __future__ import annotations

import re

_CRLF_RE = re.compile(r"\r\n?")
_IDEOGRAPHIC_SPACE = "\u3000"
_INLINE_WS_RE = re.compile(r"[ \t\f\v]+")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """规范化正文文本（幂等）。"""
    if not text:
        return ""

    # 1) 统一换行
    result = _CRLF_RE.sub("\n", text)

    # 2) 全角空格 -> 半角
    result = result.replace(_IDEOGRAPHIC_SPACE, " ")

    # 3) 逐行折叠行内空白
    lines = [_INLINE_WS_RE.sub(" ", line).strip() for line in result.split("\n")]

    # 4) 压缩连续空行
    result = _MULTI_BLANK_RE.sub("\n\n", "\n".join(lines))

    return result.strip()


def split_paragraphs(text: str) -> list[str]:
    """把规范化文本切分为段落列表。

    切分依据：空行；若无空行则以单换行为界（中文网文常见）。
    """
    normalized = normalize_text(text)
    if not normalized:
        return []

    if "\n\n" in normalized:
        return [p.strip() for p in normalized.split("\n\n") if p.strip()]

    return [line.strip() for line in normalized.split("\n") if line.strip()]


def count_words(text: str) -> int:
    """统计字数。

    采用「CJK 字符数 + 非 CJK 词数」的混合计数，贴近中文阅读器的口径。
    """
    if not text:
        return 0

    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    non_cjk_words = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + non_cjk_words


__all__ = ["count_words", "normalize_text", "split_paragraphs"]
