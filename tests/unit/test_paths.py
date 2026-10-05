# SPDX-License-Identifier: GPL-3.0-only
"""运行目录与数据目录解析测试。

锁定便携模式的关键行为：

1. 打包后数据落在可执行文件同级的 data/ 下
2. 开发模式下落在当前工作目录的 data/ 下
3. MOGRAB_HOME 可直接覆盖数据目录
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mograb.config import ENV_HOME, data_dir, get_paths, is_frozen, runtime_dir
from mograb.config.paths import DATA_DIRNAME, DATABASE_FILENAME


class TestRuntimeDir:
    def test_dev_mode_uses_cwd(self, tmp_path: Path, monkeypatch) -> None:
        """未打包时跟随当前工作目录。"""
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.chdir(tmp_path)
        assert runtime_dir() == tmp_path.resolve()

    def test_frozen_uses_executable_dir(self, tmp_path: Path, monkeypatch) -> None:
        """打包后跟随可执行文件所在目录。"""
        exe_dir = tmp_path / "MoGrab-CLI"
        exe_dir.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "mog.exe"))
        assert runtime_dir() == exe_dir.resolve()

    def test_is_frozen_defaults_false(self, monkeypatch) -> None:
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert is_frozen() is False


class TestDataDir:
    def test_env_override_wins(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv(ENV_HOME, str(tmp_path))
        assert data_dir() == tmp_path.resolve()

    def test_env_override_expands_user(self, monkeypatch) -> None:
        monkeypatch.setenv(ENV_HOME, "~")
        assert data_dir() == Path.home().resolve()

    def test_env_override_skips_data_subdir(self, tmp_path: Path, monkeypatch) -> None:
        """MOGRAB_HOME 直接指定数据目录，不再追加 data 子目录。"""
        monkeypatch.setenv(ENV_HOME, str(tmp_path))
        assert data_dir().name != DATA_DIRNAME

    def test_dev_mode_nests_under_cwd(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv(ENV_HOME, raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.chdir(tmp_path)
        assert data_dir() == tmp_path.resolve() / DATA_DIRNAME

    def test_frozen_nests_under_executable_dir(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv(ENV_HOME, raising=False)
        exe_dir = tmp_path / "app"
        exe_dir.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "mog.exe"))
        assert data_dir() == exe_dir.resolve() / DATA_DIRNAME

    def test_env_override_beats_frozen(self, tmp_path: Path, monkeypatch) -> None:
        override = tmp_path / "custom"
        monkeypatch.setenv(ENV_HOME, str(override))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "mog.exe"))
        assert data_dir() == override.resolve()


class TestPaths:
    def test_explicit_root(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        assert paths.root == tmp_path.resolve()
        assert paths.database == tmp_path.resolve() / DATABASE_FILENAME
        assert paths.config_file == tmp_path.resolve() / "config.toml"

    def test_all_paths_under_root(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        for path in (
            paths.config_file,
            paths.database,
            paths.covers_dir,
            paths.logs_dir,
            paths.exports_dir,
            paths.sources_dir,
        ):
            assert path.is_relative_to(paths.root), path

    def test_ensure_creates_dirs(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path / "fresh")
        paths.ensure()
        for directory in (
            paths.covers_dir,
            paths.logs_dir,
            paths.exports_dir,
            paths.sources_dir,
        ):
            assert directory.is_dir()

    def test_ensure_is_idempotent(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        paths.ensure()
        paths.ensure()

    def test_paths_is_frozen_dataclass(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        with pytest.raises(AttributeError):
            paths.root = tmp_path  # type: ignore[misc]

    def test_data_is_flat_under_root(self, tmp_path: Path) -> None:
        """数据项直接位于数据根下，不再嵌套一层。"""
        paths = get_paths(tmp_path)
        assert paths.database.parent == paths.root
        assert paths.exports_dir.parent == paths.root
        assert paths.logs_dir.parent == paths.root


class TestIsolationFromRepo:
    def test_data_dir_not_in_repo_root(self, tmp_path: Path, monkeypatch) -> None:
        """数据目录名与仓库的 sources/ 目录区分开，避免开发时撞名。"""
        monkeypatch.delenv(ENV_HOME, raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.chdir(tmp_path)
        repo_like = tmp_path
        assert data_dir() != repo_like
        assert data_dir().parent == repo_like
