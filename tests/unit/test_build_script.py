# SPDX-License-Identifier: GPL-3.0-only
"""构建脚本的辅助逻辑测试。

主要盯 ``flatten_dist`` —— 这段逻辑在 Linux 上踩过一次坑：可执行文件名和
PyInstaller 建的目录名都叫 ``mog``，逐个搬文件时第一个就撞上自己。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("mograb_build_script", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def build_module():
    return _load_build_module()


def _make_nested(out_dir: Path, name: str, exe_name: str) -> Path:
    """造一个 PyInstaller 风格的产物：<out_dir>/<name>/{exe,_internal/}"""
    nested = out_dir / name
    (nested / "_internal").mkdir(parents=True)
    (nested / exe_name).write_text("binary", encoding="utf-8")
    (nested / "_internal" / "lib.txt").write_text("x", encoding="utf-8")
    return nested


class TestFlattenDist:
    def test_windows_style_exe_name(self, tmp_path: Path, build_module) -> None:
        """Windows：目录名 mog，可执行文件 mog.exe，名字不冲突。"""
        out_dir = tmp_path / "MoGrab-CLI"
        _make_nested(out_dir, "mog", "mog.exe")

        build_module.flatten_dist(out_dir, "mog")

        names = sorted(p.name for p in out_dir.iterdir())
        assert names == ["_internal", "mog.exe"]
        assert (out_dir / "_internal" / "lib.txt").is_file()

    def test_linux_style_same_name(self, tmp_path: Path, build_module) -> None:
        """Linux：目录名和可执行文件名都是 mog，容易撞上自己。"""
        out_dir = tmp_path / "MoGrab-CLI"
        _make_nested(out_dir, "mog", "mog")

        build_module.flatten_dist(out_dir, "mog")

        names = sorted(p.name for p in out_dir.iterdir())
        assert names == ["_internal", "mog"]
        assert (out_dir / "mog").is_file()
        assert (out_dir / "_internal" / "lib.txt").is_file()

    def test_no_staging_left_behind(self, tmp_path: Path, build_module) -> None:
        out_dir = tmp_path / "MoGrab-CLI"
        _make_nested(out_dir, "mog", "mog.exe")

        build_module.flatten_dist(out_dir, "mog")

        assert not (out_dir / "_staging").exists()

    def test_missing_nested_dir_is_noop(self, tmp_path: Path, build_module) -> None:
        """没有嵌套目录时不该抛错。"""
        out_dir = tmp_path / "empty"
        out_dir.mkdir()
        build_module.flatten_dist(out_dir, "mog")
        assert list(out_dir.iterdir()) == []

    def test_recovers_from_stale_staging(self, tmp_path: Path, build_module) -> None:
        """上次构建失败留下的 _staging 要能清掉。"""
        out_dir = tmp_path / "MoGrab-CLI"
        _make_nested(out_dir, "mog", "mog.exe")
        stale = out_dir / "_staging"
        stale.mkdir()
        (stale / "junk.txt").write_text("junk", encoding="utf-8")

        build_module.flatten_dist(out_dir, "mog")

        assert not stale.exists()
        assert (out_dir / "mog.exe").is_file()

    def test_overwrites_existing_target(self, tmp_path: Path, build_module) -> None:
        """目标位置已有同名文件时覆盖，而不是报错。"""
        out_dir = tmp_path / "MoGrab-CLI"
        _make_nested(out_dir, "mog", "mog.exe")
        (out_dir / "mog.exe").write_text("old", encoding="utf-8")

        build_module.flatten_dist(out_dir, "mog")

        assert (out_dir / "mog.exe").read_text(encoding="utf-8") == "binary"


class TestTargetConfig:
    def test_all_targets_have_required_keys(self, build_module) -> None:
        for name, cfg in build_module.TARGETS.items():
            for key in ("entry", "name", "out", "paths", "metadata"):
                assert key in cfg, f"{name} 缺少配置项 {key}"

    def test_entries_exist(self, build_module) -> None:
        for name, cfg in build_module.TARGETS.items():
            assert cfg["entry"].is_file(), f"{name} 的入口文件不存在: {cfg['entry']}"

    def test_paths_exist(self, build_module) -> None:
        for name, cfg in build_module.TARGETS.items():
            for path in cfg["paths"]:
                assert path.is_dir(), f"{name} 的源码路径不存在: {path}"
