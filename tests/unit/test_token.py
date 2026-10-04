# SPDX-License-Identifier: GPL-3.0-only
"""API 访问令牌的生成与存储。"""

from __future__ import annotations

import os
import stat
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mograb.config import ensure_token, generate_token, get_paths, read_token

pytestmark = pytest.mark.unit


class TestGenerate:
    def test_is_url_safe_and_long_enough(self) -> None:
        token = generate_token()

        # token_urlsafe 的字符集：字母数字加 - 和 _
        assert set(token) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        # 32 字节 base64url 编码后是 43 个字符
        assert len(token) == 43

    def test_每次都不一样(self) -> None:
        assert len({generate_token() for _ in range(50)}) == 50


class TestReadWrite:
    def test_首次调用会生成并落盘(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)

        token = ensure_token(paths)

        assert paths.token_file.is_file()
        assert read_token(paths) == token

    def test_幂等(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)

        first = ensure_token(paths)
        second = ensure_token(paths)

        assert first == second

    def test_没有文件时读到_None(self, tmp_path: Path) -> None:
        assert read_token(get_paths(tmp_path)) is None

    def test_空文件当成没有(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        paths.token_file.parent.mkdir(parents=True, exist_ok=True)
        paths.token_file.write_text("   \n", encoding="utf-8")

        assert read_token(paths) is None
        assert ensure_token(paths) != ""

    def test_去掉首尾空白(self, tmp_path: Path) -> None:
        """手工编辑过也不该带上换行。"""
        paths = get_paths(tmp_path)
        paths.token_file.parent.mkdir(parents=True, exist_ok=True)
        paths.token_file.write_text("  abc123  \n", encoding="utf-8")

        assert read_token(paths) == "abc123"

    def test_已有令牌会被复用而不是覆盖(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)
        paths.token_file.parent.mkdir(parents=True, exist_ok=True)
        paths.token_file.write_text("preset-token", encoding="utf-8")

        assert ensure_token(paths) == "preset-token"

    def test_不会留下临时文件(self, tmp_path: Path) -> None:
        """写盘走的是「临时文件 + 原子替换」，收尾要干净。"""
        paths = get_paths(tmp_path)
        ensure_token(paths)

        leftovers = [p.name for p in paths.root.iterdir() if p.name != "token"]
        assert leftovers == []

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows 没有 POSIX 权限位")
    def test_POSIX_下权限是_0600(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)

        ensure_token(paths)

        mode = stat.S_IMODE(paths.token_file.stat().st_mode)
        assert mode == 0o600, f"期望 0600，实际 {oct(mode)}"


class TestConcurrency:
    def test_并发调用拿到同一个令牌(self, tmp_path: Path) -> None:
        """CLI 和 server 同时首次启动时不该各写一份。

        原子替换保证文件不会出现「存在但内容为空」的中间态 ——
        有那个窗口的话，读到空值的进程会另生成一份，两边就对不上了。
        """
        paths = get_paths(tmp_path)
        workers = 8

        # 同时放行，尽量制造真正的并发
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = [
                f.result() for f in [pool.submit(ensure_token, paths) for _ in range(workers)]
            ]

        assert len(set(results)) == 1
        assert read_token(paths) == results[0]


class TestPaths:
    def test_令牌文件在数据目录下(self, tmp_path: Path) -> None:
        paths = get_paths(tmp_path)

        assert paths.token_file == tmp_path / "token"
        assert paths.token_file.parent == paths.root

    def test_ensure_不创建令牌文件(self, tmp_path: Path) -> None:
        """建目录和生成令牌是两件事，别在 ensure() 里顺手生成。"""
        paths = get_paths(tmp_path)
        paths.ensure()

        assert not paths.token_file.exists()
        assert os.path.isdir(tmp_path)
