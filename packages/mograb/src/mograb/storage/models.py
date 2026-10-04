# SPDX-License-Identifier: GPL-3.0-only
"""SQLAlchemy ORM 模型（规划书 §24）。

表清单与关系::

    sources ──< books ──< chapters
    books   ──< tasks ──< task_items
    books   ──< exports
    http_cache（独立）
    settings（键值）

设计约定：

- 主键统一使用 TEXT（ULID），与领域模型一致。
- 所有时间戳使用 UTC，存储为 ISO-8601 字符串（SQLite 无原生时间类型）。
- ``books`` 上对 ``(source_id, source_book_id)`` 建唯一索引，保证幂等写入。
- ``chapters`` 上对 ``(book_id, identity_key)`` 建唯一索引，实现章节去重。
- 内容变更检测依赖 ``content_hash`` 列（规划书 §6.3）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """ORM 基类。"""


class SourceRow(Base):
    """已安装书源的元数据。"""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    version: Mapped[str] = mapped_column(String(32))
    spec_version: Mapped[int] = mapped_column(Integer, default=1)
    homepage: Mapped[str | None] = mapped_column(String(512), nullable=True)
    license: Mapped[str | None] = mapped_column(String(64), nullable=True)

    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 版本管理（规划书 §55、§56）
    installed_version: Mapped[str] = mapped_column(String(32), default="")
    previous_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    health: Mapped[str] = mapped_column(String(16), default="unknown")

    installed_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))

    books: Mapped[list[BookRow]] = relationship(back_populates="source")


class BookRow(Base):
    """书籍。"""

    __tablename__ = "books"
    __table_args__ = (UniqueConstraint("source_id", "source_book_id", name="uq_book_identity"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    source_book_id: Mapped[str] = mapped_column(String(256), index=True)

    title: Mapped[str] = mapped_column(String(512), index=True)
    author: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    intro: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cover_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    latest_chapter: Mapped[str | None] = mapped_column(String(512), nullable=True)

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32), index=True)

    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)

    source: Mapped[SourceRow] = relationship(back_populates="books")
    chapters: Mapped[list[ChapterRow]] = relationship(
        back_populates="book", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[TaskRow]] = relationship(back_populates="book")


class ChapterRow(Base):
    """章节。"""

    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("book_id", "identity_key", name="uq_chapter_identity"),
        Index("ix_chapter_book_index", "book_id", "index"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    source_chapter_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    identity_key: Mapped[str] = mapped_column(String(512), index=True)

    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(String(1024))
    normalized_url: Mapped[str] = mapped_column(String(1024), default="")
    index: Mapped[int] = mapped_column(Integer, default=0)

    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))

    book: Mapped[BookRow] = relationship(back_populates="chapters")


class TaskRow(Base):
    """任务。"""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"), nullable=True, index=True)

    total: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    resume_cursor: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)

    book: Mapped[BookRow | None] = relationship(back_populates="tasks")
    items: Mapped[list[TaskItemRow]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class TaskItemRow(Base):
    """任务项（单章）。"""

    __tablename__ = "task_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))

    task: Mapped[TaskRow] = relationship(back_populates="items")


class ExportRow(Base):
    """导出记录。"""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    format: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[str] = mapped_column(String(32))
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class HttpCacheRow(Base):
    """HTTP 缓存条目（规划书 §16）。"""

    __tablename__ = "http_cache"
    __table_args__ = (Index("ix_http_cache_expires", "expires_at"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    status_code: Mapped[int] = mapped_column(Integer)
    encoding: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content: Mapped[bytes] = mapped_column(Text)  # 存 base64 或原始 bytes

    created_at: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)


class SettingRow(Base):
    """键值配置（用户级覆盖）。"""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(32))


def utc_now_iso() -> str:
    """UTC 当前时间的 ISO 字符串（统一时间戳格式）。"""
    return datetime.now(UTC).isoformat()


__all__ = [
    "Base",
    "BookRow",
    "ChapterRow",
    "ExportRow",
    "HttpCacheRow",
    "SettingRow",
    "SourceRow",
    "TaskItemRow",
    "TaskRow",
    "utc_now_iso",
]
