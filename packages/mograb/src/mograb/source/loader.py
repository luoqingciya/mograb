# SPDX-License-Identifier: GPL-3.0-only
"""Source Loader —— YAML -> SourceSpec（规划书 §10）。

加载流程::

    YAML 文件
       ↓ 读取
    原始 dict
       ↓ Pydantic 校验（结构 / 类型 / 引用）
    SourceSpec
       ↓ 语义校验（validator.py）
    Compiled Source

本模块只负责「读取 + 结构校验」，语义层面的检查（选择器可用性、
模板变量完整性等）由 :mod:`mograb.source.validator` 完成。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..domain.source import SourceSpec
from ..errors import SourceSchemaError


def load_source_dict(data: dict[str, Any], *, origin: str = "<dict>") -> SourceSpec:
    """从已解析的字典构造 :class:`SourceSpec`。

    Raises:
        SourceSchemaError: 结构校验失败，错误信息含字段路径与原因。
    """
    try:
        return SourceSpec.model_validate(data)
    except ValidationError as exc:
        raise SourceSchemaError(
            f"书源 Schema 校验失败 ({origin})",
            details={"origin": origin, "errors": _format_errors(exc)},
        ) from exc


def load_source_file(path: str | Path) -> SourceSpec:
    """从 YAML 文件加载书源。

    Raises:
        SourceSchemaError: 文件不存在、YAML 非法或 Schema 校验失败。
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise SourceSchemaError(f"书源文件不存在: {file_path}", details={"path": str(file_path)})
    try:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SourceSchemaError(
            f"YAML 解析失败: {file_path}",
            details={"path": str(file_path), "reason": str(exc)},
        ) from exc

    if not isinstance(raw, dict):
        raise SourceSchemaError(
            f"书源根节点必须是映射（mapping），实际为 {type(raw).__name__}",
            details={"path": str(file_path)},
        )
    return load_source_dict(raw, origin=str(file_path))


def _format_errors(exc: ValidationError) -> list[dict[str, Any]]:
    """把 pydantic 错误整理为「字段路径 + 原因」，便于 CLI 展示。"""
    formatted: list[dict[str, Any]] = []
    for err in exc.errors():
        location = ".".join(str(p) for p in err.get("loc", ()))
        formatted.append(
            {
                "path": location,
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
        )
    return formatted


__all__ = ["load_source_dict", "load_source_file"]
