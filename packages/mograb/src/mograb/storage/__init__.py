# SPDX-License-Identifier: GPL-3.0-only
"""存储子系统：ORM 模型、仓储接口与 SQLite 实现。

业务层只依赖 :mod:`mograb.storage.repository` 中的协议，不直接写 SQL。
"""

from .models import (
    Base,
    BookRow,
    ChapterRow,
    ExportRow,
    HttpCacheRow,
    SettingRow,
    SourceRow,
    TaskItemRow,
    TaskRow,
    utc_now_iso,
)
from .repository import (
    BookRepository,
    ChapterRepository,
    ExportRepository,
    SettingsRepository,
    SourceRepository,
    TaskRepository,
)
from .sqlite import (
    Database,
    SqliteBookRepository,
    SqliteChapterRepository,
    SqliteSettingsRepository,
    SqliteTaskRepository,
)

__all__ = [
    "Base",
    "BookRepository",
    "BookRow",
    "ChapterRepository",
    "ChapterRow",
    "Database",
    "ExportRepository",
    "ExportRow",
    "HttpCacheRow",
    "SettingRow",
    "SettingsRepository",
    "SourceRepository",
    "SourceRow",
    "SqliteBookRepository",
    "SqliteChapterRepository",
    "SqliteSettingsRepository",
    "SqliteTaskRepository",
    "TaskItemRow",
    "TaskRepository",
    "TaskRow",
    "utc_now_iso",
]
