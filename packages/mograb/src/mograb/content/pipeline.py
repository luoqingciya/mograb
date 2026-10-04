# SPDX-License-Identifier: GPL-3.0-only
"""内容管线与校验（规划书 §21、§22）。

流程::

    Raw Response
         ↓
    Extractor        （在 Source Engine 中完成）
         ↓
    HTML Cleanup     （DOM 级：cleaner.clean_text）
         ↓
    Content Normalize（normalizer.normalize_text）
         ↓
    Validation       （本模块 ContentValidator）
         ↓
    Chapter

**关键设计（对应 §22）**：校验阈值不得硬编码在业务代码里，
统一由 :class:`ContentPolicy` 提供，可按全局/书源/任务三级覆盖
（对应 §35 的配置优先级）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.chapter import compute_content_hash
from ..errors import ContentValidationError
from ..logging.setup import get_logger
from .cleaner import clean_text
from .normalizer import count_words, normalize_text

_logger = get_logger(__name__)


@dataclass(slots=True)
class ContentPolicy:
    """内容校验策略（可配置，见规划书 §22）。

    三级覆盖顺序：任务参数 > 书源配置 > 全局配置 > 此处默认值。
    """

    min_length: int = 50
    """正文最小字符数；低于此值视为抓取失败。"""

    max_length: int = 200_000
    """正文最大字符数；超过视为异常（可能是整页而非正文）。"""

    min_chinese_ratio: float = 0.30
    """中文字符占比下限；过低说明抓到的是导航/广告页。"""

    reject_on_empty: bool = True
    """正文为空时是否直接判失败。"""

    max_repeat_line_ratio: float = 0.60
    """单行重复率上限；过高说明是「请记住本站」类模板页。"""


@dataclass(slots=True)
class ProcessedContent:
    """管线处理结果。"""

    text: str
    word_count: int
    content_hash: str


class ContentPipeline:
    """把原始正文处理为可入库的规范化文本。"""

    def __init__(self, policy: ContentPolicy | None = None) -> None:
        self._policy = policy or ContentPolicy()

    @property
    def policy(self) -> ContentPolicy:
        return self._policy

    def process(
        self, raw: str, *, extra_junk_patterns: list[str] | None = None
    ) -> ProcessedContent:
        """执行 清洗 → 规范化 → 校验。

        Raises:
            ContentValidationError: 未通过校验（含具体原因与阈值）。
        """
        cleaned = clean_text(raw, extra_junk_patterns=extra_junk_patterns)
        normalized = normalize_text(cleaned)
        self.validate(normalized)
        return ProcessedContent(
            text=normalized,
            word_count=count_words(normalized),
            content_hash=compute_content_hash(normalized),
        )

    # ------------------------------------------------------------------
    def validate(self, text: str) -> None:
        """按策略校验正文，不通过则抛 :class:`ContentValidationError`。"""
        policy = self._policy
        length = len(text)

        if policy.reject_on_empty and not text.strip():
            raise ContentValidationError(
                "正文为空",
                details={"reason": "empty", "length": length},
            )

        if length < policy.min_length:
            raise ContentValidationError(
                f"正文过短（{length} < {policy.min_length}）",
                details={
                    "reason": "too_short",
                    "length": length,
                    "threshold": policy.min_length,
                },
            )

        if length > policy.max_length:
            raise ContentValidationError(
                f"正文过长（{length} > {policy.max_length}）",
                details={
                    "reason": "too_long",
                    "length": length,
                    "threshold": policy.max_length,
                },
            )

        chinese_ratio = _chinese_ratio(text)
        if chinese_ratio < policy.min_chinese_ratio:
            raise ContentValidationError(
                f"中文占比过低（{chinese_ratio:.2f} < {policy.min_chinese_ratio}）",
                details={
                    "reason": "low_chinese_ratio",
                    "ratio": round(chinese_ratio, 4),
                    "threshold": policy.min_chinese_ratio,
                },
            )

        repeat_ratio = _max_repeat_ratio(text)
        if repeat_ratio > policy.max_repeat_line_ratio:
            raise ContentValidationError(
                f"重复行占比过高（{repeat_ratio:.2f}），疑似模板页",
                details={
                    "reason": "high_repeat_ratio",
                    "ratio": round(repeat_ratio, 4),
                    "threshold": policy.max_repeat_line_ratio,
                },
            )


# ---------------------------------------------------------------------------
# 统计辅助
# ---------------------------------------------------------------------------
def _chinese_ratio(text: str) -> float:
    """中文字符占比。"""
    meaningful = [ch for ch in text if not ch.isspace()]
    if not meaningful:
        return 0.0
    cjk = sum(1 for ch in meaningful if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(meaningful)


def _max_repeat_ratio(text: str) -> float:
    """重复行占比（重复行数 / 总行数）。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if len(lines) < 3:
        return 0.0
    from collections import Counter

    counter = Counter(lines)
    repeated = sum(count for count in counter.values() if count > 1)
    return repeated / len(lines)


__all__ = ["ContentPipeline", "ContentPolicy", "ProcessedContent"]
