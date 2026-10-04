# SPDX-License-Identifier: GPL-3.0-only
"""Book 领域模型（规划书 §6.2）。

关键约定：

- ``id`` 是 MoGrab 内部主键（ULID），**绝不**直接使用来源站 ID 作为主键。
- ``source_book_id`` 保存来源站自身标识，用于增量更新与去重。
- 同一 ``source_id`` + ``source_book_id`` 唯一。

相对规划书的补全项（详见 docs/evaluation/规划评估报告.md）：
``language`` / ``word_count`` / ``chapter_count`` / ``cover_path`` —— 这些字段
EPUB 导出（§27）与书架展示（§33）需要，但原规划书未在模型中定义。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import BookStatus


class Book(BaseModel):
    """一本书的元数据（不含章节正文）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # --- 标识 ---
    id: str = Field(description="MoGrab 内部 ID（ULID）")
    source_id: str = Field(description="来源书源 ID")
    source_book_id: str = Field(description="来源站自身的书籍标识")

    # --- 元数据 ---
    title: str
    author: str | None = None
    intro: str | None = None
    language: str | None = Field(
        default=None,
        description="BCP-47 语言标签，如 zh-CN；EPUB metadata 必需",
    )
    cover_url: str | None = None
    cover_path: str | None = Field(default=None, description="已下载封面的本地相对路径")
    status: BookStatus = BookStatus.UNKNOWN
    latest_chapter: str | None = Field(
        default=None, description="来源站最新章节标题（用于快速判断更新）"
    )

    # --- 派生统计（由 Storage/Content 层维护，非书源提供）---
    word_count: int = 0
    chapter_count: int = 0

    # --- 时间戳 ---
    created_at: datetime
    updated_at: datetime

    # --- 扩展 ---
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="书源自定义附加字段，不得用于承载核心语义",
    )

    @property
    def identity(self) -> tuple[str, str]:
        """用于去重/幂等写入的业务唯一键。"""
        return (self.source_id, self.source_book_id)


__all__ = ["Book"]
