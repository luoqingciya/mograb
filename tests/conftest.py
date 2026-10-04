# SPDX-License-Identifier: GPL-3.0-only
"""pytest 全局夹具。

约定：测试默认离线。任何需要真实网络的测试必须标记 ``@pytest.mark.network``，
并在 CI 中默认跳过（规划书 §47）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mograb.domain.book import Book
from mograb.domain.chapter import Chapter
from mograb.domain.enums import BookStatus

REPO_ROOT = Path(__file__).resolve().parents[1]
# 示例书源放在测试夹具里，不放 sources/ —— 书源不进远程仓库
EXAMPLE_SOURCE = REPO_ROOT / "tests" / "fixtures" / "example-source"


@pytest.fixture(autouse=True)
def isolate_runtime_dir(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """把数据目录隔离到临时路径。

    开发模式下运行目录默认是 cwd，若不隔离，任何调用 ``Paths.ensure()``
    的测试（例如 API 冒烟测试触发的 lifespan）都会在仓库根创建
    ``cache/``、``logs/`` 等目录。

    需要验证默认解析行为的测试可以显式 ``delenv`` 覆盖。
    """
    home = tmp_path_factory.mktemp("mograb-home")
    monkeypatch.setenv("MOGRAB_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def example_source_dir() -> Path:
    """官方示例书源目录。"""
    return EXAMPLE_SOURCE


@pytest.fixture(scope="session")
def example_fixtures_dir(example_source_dir: Path) -> Path:
    """示例书源 fixture 目录。"""
    return example_source_dir / "fixtures"


@pytest.fixture
def now() -> datetime:
    """固定时间戳，避免测试依赖真实时钟。"""
    return datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def sample_book(now: datetime) -> Book:
    """样例书籍。"""
    return Book(
        id="book_test0001",
        source_id="example",
        source_book_id="1001",
        title="三体",
        author="刘慈欣",
        intro="文化大革命如火如荼进行的同时……",
        language="zh-CN",
        status=BookStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def sample_chapters(now: datetime, sample_book: Book) -> list[Chapter]:
    """样例章节列表。"""
    return [
        Chapter(
            id=f"chap_{i:04d}",
            book_id=sample_book.id,
            source_chapter_id=f"c{i}",
            title=f"第{i}章 测试章节",
            url=f"https://example.com/book/1001/chapter/{i}",
            index=i,
            content=f"这是第 {i} 章的正文内容。" * 5,
            created_at=now,
            updated_at=now,
        )
        for i in range(1, 4)
    ]
