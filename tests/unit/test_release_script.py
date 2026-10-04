# SPDX-License-Identifier: GPL-3.0-only
"""发布辅助脚本的测试。

盯的是 ``extract_notes`` —— 它决定 GitHub Release 页面上显示什么。
这段逻辑原先在 Release 工作流里是内联 awk，反斜杠要穿过 YAML → bash → awk
三层转义，写错一次就会把整份 CHANGELOG（连版本规划表都算上）当成发布说明，
而且不报错。挪进 Python 之后才有得测。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def _load_release_module():
    spec = importlib.util.spec_from_file_location("mograb_release_script", RELEASE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def release_module():
    return _load_release_module()


class TestExtractNotes:
    def test_提取当前版本(self, release_module) -> None:
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        notes = release_module.extract_notes(version)

        assert notes.startswith(f"## [{version}]")
        assert "预发布版本" in notes

    def test_只取本版本段落(self, release_module) -> None:
        """不能把下一个二级标题的内容也带进来。"""
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        notes = release_module.extract_notes(version)

        # `## 版本规划` 是下一个二级标题，它的表格不该出现在发布说明里
        assert "## 版本规划" not in notes
        assert "| v1.0.0 |" not in notes

    def test_不含其他版本的标题(self, release_module) -> None:
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        notes = release_module.extract_notes(version)

        # 全文只应有一个二级标题
        assert notes.count("\n## ") == 0

    def test_找不到版本时给占位(self, release_module) -> None:
        notes = release_module.extract_notes("9.9.9")

        assert notes.strip() == "Release 9.9.9"

    def test_版本号里的点号不当通配符(self, release_module, tmp_path: Path, monkeypatch) -> None:
        """`re.escape` 的回归测试：`1.0.0` 不该匹配到 `1x0x0`。"""
        fake = tmp_path / "CHANGELOG.md"
        fake.write_text(
            "## [1x0x0] - 2026-01-01\n\n不该被匹配\n\n## [1.0.0] - 2026-01-02\n\n应该被匹配\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(release_module, "CHANGELOG", fake)

        notes = release_module.extract_notes("1.0.0")

        assert "应该被匹配" in notes
        assert "不该被匹配" not in notes


class TestChangelogShape:
    """发布说明依赖 CHANGELOG 的标题格式，这里把它钉住。"""

    def test_当前版本有对应标题(self) -> None:
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        text = CHANGELOG.read_text(encoding="utf-8")

        assert f"## [{version}]" in text, (
            f"CHANGELOG 里没有 `## [{version}]` 标题，发布说明会是空的"
        )

    def test_当前版本的标题带日期(self) -> None:
        """`## [x] - 未发布` 这种标题在正式发布前要改成日期。

        只看**当前 VERSION 对应**的那个标题 —— 顶部可能还有一个
        `## [未发布]` 段落，那是正常的工作区。
        """
        version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        text = CHANGELOG.read_text(encoding="utf-8")

        heading = next(line for line in text.splitlines() if line.startswith(f"## [{version}]"))
        assert "未发布" not in heading, f"发布前要把标题改成带日期的形式：{heading}"


class TestChecksums:
    def test_生成并校验(self, release_module, tmp_path: Path) -> None:
        (tmp_path / "a.zip").write_bytes(b"aaa")
        (tmp_path / "b.tar.gz").write_bytes(b"bbb")

        sums = release_module.generate_checksums(tmp_path)

        assert sums.is_file()
        assert release_module.verify_checksums(tmp_path) == 0

    def test_内容被改动时校验失败(self, release_module, tmp_path: Path) -> None:
        target = tmp_path / "a.zip"
        target.write_bytes(b"aaa")
        release_module.generate_checksums(tmp_path)

        target.write_bytes(b"tampered")

        assert release_module.verify_checksums(tmp_path) != 0
