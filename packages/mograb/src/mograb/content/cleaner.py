# SPDX-License-Identifier: GPL-3.0-only
"""正文清洗（规划书 §21）。

清洗分两级：

1. **DOM 级**：移除 ``script`` / ``style`` / 广告节点（在 Source Engine 中执行，
   因为需要已解析的树）。
2. **文本级**：本模块负责 —— 去残余标签、去不可见字符、去重复空行、
   去站点水印行等。

清洗规则应尽量声明式（来自书源 ``content.clean``），但部分通用规则
（控制字符、零宽字符、行首广告）适合作为内建默认，避免每个书源重复声明。
"""

from __future__ import annotations

import re

from ..domain.source import CleanSpec

# 内建通用清洗规则（所有书源共享）
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2028-\u202f\ufeff]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_ENTITY_HINT_RE = re.compile(r"&(?:[a-zA-Z]+|#\d+);")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# 常见站点水印/导航行（整行匹配时移除）
_DEFAULT_JUNK_LINES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^\s*(本章未完|请记住本站|手机用户请浏览|天才一秒记住|"
        r"最新章节|上一章|下一章|返回目录|加入书签|投推荐票)\s*.*$"
    ),
    re.compile(
        r"^\s*[（(]?\s*(?:www|m)\.[a-z0-9.-]+(?:\.(?:com|net|org|cn|cc|xyz))?\s*[)）]?\s*$", re.I
    ),
    re.compile(r"^\s*(?:https?://)?[a-z0-9.-]+\.(?:com|net|org|cn|cc|xyz)\s*$", re.I),
)


def clean_text(
    text: str,
    spec: CleanSpec | None = None,
    *,
    extra_junk_patterns: list[str] | None = None,
) -> str:
    """对正文文本执行清洗。

    Args:
        text: 待清洗文本（可能仍含 HTML 片段）。
        spec: 书源声明的清洗规格；为 None 时仅用内建规则。
        extra_junk_patterns: 附加的「整行丢弃」正则。

    Returns:
        清洗后的纯文本。
    """
    result = text

    # 1) 去残余 HTML 标签（若书源以 html 属性提取）
    if "<" in result and ">" in result:
        result = _HTML_TAG_RE.sub("", result)

    # 2) HTML 实体已在 Extractor 阶段处理；此处兜底常见残留
    result = result.replace("&nbsp;", " ").replace("&amp;", "&")

    # 3) 去零宽与不可见字符
    result = _ZERO_WIDTH_RE.sub("", result)
    result = _CONTROL_CHAR_RE.sub("", result)

    # 4) 逐行过滤水印
    patterns = list(_DEFAULT_JUNK_LINES)
    for raw in extra_junk_patterns or []:
        try:
            patterns.append(re.compile(raw))
        except re.error:
            continue  # 非法正则由 Linter 报告，此处不阻断

    lines = [line.rstrip() for line in result.split("\n")]
    kept = [line for line in lines if not any(p.match(line) for p in patterns)]

    # 5) 合并多余空行
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(kept)).strip()


__all__ = ["clean_text"]
