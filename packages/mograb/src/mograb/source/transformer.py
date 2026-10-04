# SPDX-License-Identifier: GPL-3.0-only
"""Transformer —— 字段值的声明式变换流水线（规划书 §8.3）。

变换在「提取之后、进入领域模型之前」执行，可作用于：

- 全局：``SourceSpec.transforms``（作用于所有提取值）
- 能力级：``SearchSpec.transform`` / ``ContentSpec.transform`` 等
- 字段级：由能力级 transform 的目标字段隐含（v1 采用能力级统一流水线）

执行顺序为**声明顺序**，与规划书示例一致::

    transform:
      - trim
      - normalize_whitespace
      - regex_replace: { pattern: "\\\\s+", replacement: " " }
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from html import unescape
from urllib.parse import urljoin

from ..domain.source import Transform, TransformOp
from ..errors import SourceExecutionError

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# url_join 的「像 URL 引用」判定
_URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")
_FILENAME_LIKE_RE = re.compile(
    r"^[\w\-.%]+\.(?:x?html?|php\d?|aspx?|jsp|json|xml|txt)$", re.IGNORECASE
)


def _looks_like_url_ref(value: str) -> bool:
    """判断一个值是否像 URL 引用。

    必要性：v1 的 ``transform`` 作用于能力下的**所有**字段，因此
    ``url_join`` 若无条件执行，会把标题/作者也拼成 URL
    （例如 ``urljoin(base, "三体")`` → ``https://site/三体``）。

    判定规则（保守，宁可漏拼不可误拼）：

    - 含空白 → 不是（标题通常含空格）
    - 以 ``//`` / ``/`` / ``./`` / ``../`` 开头 → 是
    - 带 scheme（``https://`` 等）→ 是
    - 含 ``/`` 且无空白 → 是（形如 ``book/1001``）
    - 形如 ``chapter.html`` 的文件名 → 是

    Note:
        v1 的折中方案。字段级 transform 将在 v1.1 引入，
        届时可精确指定「仅对 url 字段执行 url_join」。
    """
    text = value.strip()
    if not text or any(ch.isspace() for ch in text):
        return False
    if text.startswith(("//", "/", "./", "../")):
        return True
    if _URL_SCHEME_RE.match(text):
        return True
    if "/" in text:
        return True
    return bool(_FILENAME_LIKE_RE.match(text))


def apply_transforms(
    value: str | None,
    transforms: Iterable[Transform],
    *,
    base_url: str | None = None,
) -> str | None:
    """对单个值依次应用变换。

    Args:
        value: 待变换的原始值；None 表示未提取到。
        transforms: 变换序列（按声明顺序执行）。
        base_url: ``url_join`` 所需的基准 URL（通常是请求 URL）。

    Returns:
        变换后的值；``default`` 算子可在值为空时提供兜底。

    Raises:
        SourceExecutionError: 未知算子或参数缺失。
    """
    current = value
    for transform in transforms:
        current = _apply_one(current, transform, base_url=base_url)
    return current


def apply_transforms_many(
    rows: list[dict[str, str | None]],
    transforms: Iterable[Transform],
    *,
    base_url: str | None = None,
) -> list[dict[str, str | None]]:
    """对列表型提取结果的每个字段应用同一组变换。"""
    transforms = list(transforms)
    if not transforms:
        return rows
    return [
        {key: apply_transforms(val, transforms, base_url=base_url) for key, val in row.items()}
        for row in rows
    ]


def _apply_one(value: str | None, transform: Transform, *, base_url: str | None) -> str | None:
    op = transform.op

    if op is TransformOp.TRIM:
        return value.strip() if value else value

    if op is TransformOp.NORMALIZE_WHITESPACE:
        return _WS_RE.sub(" ", value).strip() if value else value

    if op is TransformOp.REMOVE_HTML:
        return unescape(_TAG_RE.sub("", value)) if value else value

    if op is TransformOp.REPLACE:
        if value is None or transform.pattern is None:
            return value
        return value.replace(transform.pattern, transform.replacement or "")

    if op is TransformOp.REGEX_REPLACE:
        if value is None or transform.pattern is None:
            return value
        return re.sub(transform.pattern, transform.replacement or "", value)

    if op is TransformOp.PREPEND:
        return f"{transform.value or ''}{value or ''}"

    if op is TransformOp.APPEND:
        return f"{value or ''}{transform.value or ''}"

    if op is TransformOp.URL_JOIN:
        if not value:
            return value
        # 只对「像 URL 引用」的值生效，避免误拼标题/作者等字段
        if not _looks_like_url_ref(value):
            return value
        if not base_url:
            raise SourceExecutionError("url_join 需要 base_url 上下文")
        return urljoin(base_url, value.strip())

    if op is TransformOp.DEFAULT:
        if value is None or value == "":
            return transform.value
        return value

    if op is TransformOp.JOIN:
        # 单值上下文中 join 为恒等操作；列表合并由 Engine 处理
        return value

    raise SourceExecutionError(f"未实现的变换算子: {op}")


__all__ = ["apply_transforms", "apply_transforms_many"]
