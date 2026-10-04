# SPDX-License-Identifier: GPL-3.0-only
"""书源仓储测试。

这个仓储同时碰磁盘和数据库，所以重点测两边的一致性：
文件是定义的唯一真相，索引丢了能重建，文件丢了索引行就该被跳过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mograb.domain.enums import HealthStatus, SourceCapability
from mograb.domain.source import SourceSpec
from mograb.errors import SourceNotFoundError
from mograb.source.loader import load_source_file
from mograb.storage import Database, SqliteSourceRepository

pytestmark = pytest.mark.unit


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.init_schema()
    yield database
    await database.dispose()


@pytest.fixture
def sources_dir(tmp_path: Path) -> Path:
    path = tmp_path / "sources"
    path.mkdir()
    return path


@pytest.fixture
def repo(db: Database, sources_dir: Path) -> SqliteSourceRepository:
    return SqliteSourceRepository(db, sources_dir)


@pytest.fixture
def example_spec(example_source_dir: Path) -> SourceSpec:
    return load_source_file(example_source_dir / "source.yaml")


def make_spec(source_id: str = "demo", version: str = "1.0.0", **overrides) -> SourceSpec:
    """一个最小可用书源。"""
    data: dict = {
        "spec_version": 1,
        "id": source_id,
        "name": f"Demo {source_id}",
        "version": version,
        "capabilities": ["search"],
        "search": {
            "request": {"method": "GET", "url": "https://demo.example.com/s"},
            "result": {"list": ".item", "fields": {"title": ".t", "url": "a@href"}},
        },
    }
    data.update(overrides)
    return SourceSpec.model_validate(data)


class TestSaveAndGet:
    async def test_save_writes_file_and_row(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        await repo.save(make_spec())

        assert (sources_dir / "demo" / "source.yaml").is_file()
        entry = await repo.get("demo")
        assert entry is not None
        assert entry.spec.id == "demo"
        assert entry.enabled is True
        assert entry.health is HealthStatus.UNKNOWN

    async def test_saved_file_is_reloadable(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        """落盘的定义要能被重新加载 —— 否则拷到别的机器就废了。"""
        original = make_spec()
        await repo.save(original)

        reloaded = load_source_file(sources_dir / "demo" / "source.yaml")
        assert reloaded == original

    async def test_get_missing_returns_none(self, repo: SqliteSourceRepository) -> None:
        assert await repo.get("nope") is None

    async def test_get_returns_none_when_file_gone(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        """索引里有、磁盘上没有，当没装处理。"""
        await repo.save(make_spec())
        (sources_dir / "demo" / "source.yaml").unlink()

        assert await repo.get("demo") is None

    async def test_example_source_roundtrip(
        self, repo: SqliteSourceRepository, example_spec: SourceSpec
    ) -> None:
        await repo.save(example_spec)
        entry = await repo.get("example")
        assert entry is not None
        assert entry.spec == example_spec
        assert entry.spec.supports(SourceCapability.CONTENT)


class TestVersionHistory:
    async def test_upgrade_records_previous_version(self, repo: SqliteSourceRepository) -> None:
        await repo.save(make_spec(version="1.0.0"))
        await repo.save(make_spec(version="1.2.0"))

        entry = await repo.get("demo")
        assert entry is not None
        assert entry.installed_version == "1.2.0"
        assert entry.previous_version == "1.0.0"

    async def test_reinstall_same_version_keeps_rollback_point(
        self, repo: SqliteSourceRepository
    ) -> None:
        """同版本重装不该把回滚点冲掉。"""
        await repo.save(make_spec(version="1.0.0"))
        await repo.save(make_spec(version="1.2.0"))
        await repo.save(make_spec(version="1.2.0"))

        entry = await repo.get("demo")
        assert entry is not None
        assert entry.installed_version == "1.2.0"
        assert entry.previous_version == "1.0.0"


class TestListing:
    async def test_list_all(self, repo: SqliteSourceRepository) -> None:
        await repo.save(make_spec("alpha"))
        await repo.save(make_spec("beta"))
        ids = sorted(e.id for e in await repo.list_all())
        assert ids == ["alpha", "beta"]

    async def test_list_all_skips_missing_files(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        await repo.save(make_spec("alpha"))
        await repo.save(make_spec("beta"))
        (sources_dir / "alpha" / "source.yaml").unlink()

        assert [e.id for e in await repo.list_all()] == ["beta"]

    async def test_list_enabled_filters_disabled(self, repo: SqliteSourceRepository) -> None:
        await repo.save(make_spec("alpha"))
        await repo.save(make_spec("beta"))
        await repo.set_enabled("alpha", False)

        assert [e.id for e in await repo.list_enabled()] == ["beta"]

    @pytest.mark.parametrize("health", [HealthStatus.BROKEN, HealthStatus.UNSUPPORTED])
    async def test_list_enabled_filters_unusable(
        self, repo: SqliteSourceRepository, health: HealthStatus
    ) -> None:
        await repo.save(make_spec("alpha"))
        await repo.set_health("alpha", health)

        assert await repo.list_enabled() == []

    async def test_list_enabled_keeps_degraded(self, repo: SqliteSourceRepository) -> None:
        """部分能力异常还能用，不该被过滤掉。"""
        await repo.save(make_spec("alpha"))
        await repo.set_health("alpha", HealthStatus.DEGRADED)

        assert len(await repo.list_enabled()) == 1


class TestEnableAndHealth:
    async def test_set_enabled_roundtrip(self, repo: SqliteSourceRepository) -> None:
        await repo.save(make_spec())
        await repo.set_enabled("demo", False)
        entry = await repo.get("demo")
        assert entry is not None and entry.enabled is False

    async def test_set_health_roundtrip(self, repo: SqliteSourceRepository) -> None:
        await repo.save(make_spec())
        await repo.set_health("demo", HealthStatus.HEALTHY)
        entry = await repo.get("demo")
        assert entry is not None and entry.health is HealthStatus.HEALTHY

    async def test_set_enabled_missing_raises(self, repo: SqliteSourceRepository) -> None:
        with pytest.raises(SourceNotFoundError):
            await repo.set_enabled("nope", False)

    async def test_set_health_missing_raises(self, repo: SqliteSourceRepository) -> None:
        with pytest.raises(SourceNotFoundError):
            await repo.set_health("nope", HealthStatus.HEALTHY)


class TestDelete:
    async def test_delete_removes_row_and_directory(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        await repo.save(make_spec())
        assert await repo.delete("demo") is True

        assert await repo.get("demo") is None
        assert not (sources_dir / "demo").exists()

    async def test_delete_missing_returns_false(self, repo: SqliteSourceRepository) -> None:
        assert await repo.delete("nope") is False

    @pytest.mark.parametrize("bad_id", ["../etc", "a/b", "A-B", "", "1abc"])
    async def test_delete_rejects_bad_id(self, repo: SqliteSourceRepository, bad_id: str) -> None:
        """ID 非法时直接拒绝，不去碰文件系统。"""
        assert await repo.delete(bad_id) is False


class TestRescan:
    async def test_rebuilds_index_from_disk(
        self, db: Database, sources_dir: Path, example_spec: SourceSpec
    ) -> None:
        """索引清空后能从磁盘重建。"""
        repo = SqliteSourceRepository(db, sources_dir)
        await repo.save(make_spec("alpha"))

        # 模拟「换了台机器，只拷了 data/sources 目录」：换一个空数据库
        await db.dispose()
        fresh = Database(sources_dir.parent / "fresh.db")
        await fresh.init_schema()
        rebuilt = SqliteSourceRepository(fresh, sources_dir)

        assert await rebuilt.get("alpha") is None  # 新库还没有索引
        entries = await rebuilt.rescan()
        assert [e.id for e in entries] == ["alpha"]
        await fresh.dispose()

    async def test_rescan_preserves_enabled(self, repo: SqliteSourceRepository) -> None:
        """扫描不该把用户手动关掉的开关重置回打开。"""
        await repo.save(make_spec("alpha"))
        await repo.set_enabled("alpha", False)

        await repo.rescan()

        entry = await repo.get("alpha")
        assert entry is not None and entry.enabled is False

    async def test_rescan_drops_rows_without_file(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        await repo.save(make_spec("alpha"))
        await repo.save(make_spec("beta"))
        (sources_dir / "alpha" / "source.yaml").unlink()

        entries = await repo.rescan()

        assert [e.id for e in entries] == ["beta"]

    async def test_rescan_picks_up_hand_dropped_file(
        self, repo: SqliteSourceRepository, sources_dir: Path, example_spec: SourceSpec
    ) -> None:
        """用户直接往目录里丢了个 yaml，扫描后应该能认出来。"""
        from mograb.source.loader import write_source_file

        write_source_file(example_spec, sources_dir / "example" / "source.yaml")

        entries = await repo.rescan()
        assert [e.id for e in entries] == ["example"]

    async def test_rescan_skips_broken_file(
        self, repo: SqliteSourceRepository, sources_dir: Path
    ) -> None:
        """坏掉的定义跳过，不影响其余书源。"""
        await repo.save(make_spec("good"))
        bad = sources_dir / "bad"
        bad.mkdir()
        (bad / "source.yaml").write_text("这不是合法的书源: [", encoding="utf-8")

        entries = await repo.rescan()
        assert [e.id for e in entries] == ["good"]

    async def test_rescan_empty_dir(self, db: Database, tmp_path: Path) -> None:
        repo = SqliteSourceRepository(db, tmp_path / "not-created")
        assert await repo.rescan() == []
