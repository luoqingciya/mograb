# SPDX-License-Identifier: GPL-3.0-only
"""版本号来源与格式测试。

版本号只有一个来源：仓库根的 VERSION 文件。这里锁定两件事：

1. VERSION 内容符合 PEP 440
2. 三个分发包运行时读到的版本与 VERSION 一致，且没有第二处硬编码
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPO_ROOT / "VERSION"

PACKAGE_PYPROJECTS = (
    REPO_ROOT / "packages" / "mograb" / "pyproject.toml",
    REPO_ROOT / "apps" / "cli" / "pyproject.toml",
    REPO_ROOT / "apps" / "api" / "pyproject.toml",
)


@pytest.fixture(scope="module")
def declared_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


class TestVersionFile:
    def test_file_exists(self) -> None:
        assert VERSION_FILE.is_file()

    def test_single_line(self) -> None:
        lines = [line for line in VERSION_FILE.read_text(encoding="utf-8").splitlines() if line]
        assert len(lines) == 1

    def test_is_pep440(self, declared_version: str) -> None:
        # 解析失败会抛 InvalidVersion，即测试失败
        assert Version(declared_version) == Version(declared_version)

    def test_不低于项目起点(self, declared_version: str) -> None:
        """版本号只能往上走，不能倒退。

        刻意**不写死具体版本**。原先这里断言的是 `^0\\.1\\.0(\\.dev\\d+)?$`
        （「当前处于 0.1.x 开发阶段」），每次发版都得改测试 —— 改着改着就变成
        「看到红就顺手把数字改掉」，约束也就没了。

        「打 tag 时版本号对不对」由 Release 工作流的版本一致性检查兜底，
        比在单元测试里钉一个数字可靠。
        """
        assert Version(declared_version) >= Version("0.1.0.dev0")


class TestRuntimeVersion:
    def test_mograb_matches_file(self, declared_version: str) -> None:
        import mograb

        assert mograb.__version__ == declared_version

    def test_cli_matches_file(self, declared_version: str) -> None:
        import mograb_cli

        assert mograb_cli.__version__ == declared_version

    def test_api_matches_file(self, declared_version: str) -> None:
        import mograb_api

        assert mograb_api.__version__ == declared_version

    def test_all_packages_agree(self) -> None:
        import mograb
        import mograb_api
        import mograb_cli

        assert mograb.__version__ == mograb_cli.__version__ == mograb_api.__version__


class TestNoDuplicateSource:
    @pytest.mark.parametrize("pyproject", PACKAGE_PYPROJECTS, ids=lambda p: p.parent.name)
    def test_uses_dynamic_version(self, pyproject: Path) -> None:
        text = pyproject.read_text(encoding="utf-8")
        assert 'dynamic = ["version"]' in text

    @pytest.mark.parametrize("pyproject", PACKAGE_PYPROJECTS, ids=lambda p: p.parent.name)
    def test_points_at_root_version_file(self, pyproject: Path) -> None:
        text = pyproject.read_text(encoding="utf-8")
        assert 'source = "regex"' in text
        assert "../../VERSION" in text

    @pytest.mark.parametrize("pyproject", PACKAGE_PYPROJECTS, ids=lambda p: p.parent.name)
    def test_has_no_hardcoded_version(self, pyproject: Path) -> None:
        text = pyproject.read_text(encoding="utf-8")
        assert not re.search(r'^version\s*=\s*"', text, re.MULTILINE)

    @pytest.mark.parametrize(
        "relative",
        [
            "packages/mograb/src/mograb/__init__.py",
            "apps/cli/src/mograb_cli/__init__.py",
            "apps/api/src/mograb_api/__init__.py",
        ],
    )
    def test_no_hardcoded_dunder_version(self, relative: str) -> None:
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert not re.search(r'^__version__\s*=\s*["\']', text, re.MULTILINE)
