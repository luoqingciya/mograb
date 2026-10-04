# SPDX-License-Identifier: GPL-3.0-only
"""版本号管理（PEP 440）。

版本号的唯一来源是仓库根目录的 ``VERSION`` 文件。三个分发包
（``mograb`` / ``mograb-cli`` / ``mograb-api``）在构建时从该文件读取，
因此这里改动会一次性影响全部包。

用法::

    python scripts/version.py show              # 显示当前版本
    python scripts/version.py check             # 校验格式与一致性
    python scripts/version.py set 0.2.0.dev0    # 设置新版本

版本号必须是合法的 PEP 440 版本。常见形式：

    0.1.0.dev0      开发版（当前）
    0.1.0a1         预发布 alpha
    0.1.0rc1        预发布 rc
    0.1.0           正式版
    0.1.0.post1     修订版
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _console import force_utf8_stdio

force_utf8_stdio()

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO_ROOT / "VERSION"

# 允许出现在 VERSION 文件里的字符；实际合法性由 packaging 判定
_RAW_PATTERN = re.compile(r"^[0-9][0-9A-Za-z.+#!-]*$")

# 需要与 VERSION 保持一致的包（用于 check 子命令）
PACKAGE_DIRS = (
    REPO_ROOT / "packages" / "mograb",
    REPO_ROOT / "apps" / "cli",
    REPO_ROOT / "apps" / "api",
)


def read_version() -> str:
    """读取 VERSION 文件内容（去除空白）。"""
    if not VERSION_FILE.is_file():
        raise SystemExit(f"VERSION 文件不存在: {VERSION_FILE}")
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def validate(raw: str) -> str:
    """校验版本号是否为合法 PEP 440 版本，返回规范化后的字符串。"""
    if not raw:
        raise SystemExit("版本号为空")

    if not _RAW_PATTERN.match(raw):
        raise SystemExit(
            f"版本号含非法字符: {raw!r}\n"
            "PEP 440 版本应以数字开头，只含数字、字母、点、加号、连字符与感叹号"
        )

    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:  # packaging 未安装时退化为正则校验
        print("[version] 警告：未安装 packaging，仅做字符级校验", file=sys.stderr)
        return raw

    try:
        parsed = Version(raw)
    except InvalidVersion as exc:
        raise SystemExit(f"不是合法的 PEP 440 版本: {raw!r}（{exc}）") from exc

    # 回写规范化形式（如 0.1.0.DEV0 -> 0.1.0.dev0）
    normalized = str(parsed)
    if normalized != raw:
        print(f"[version] 提示：{raw!r} 的规范形式是 {normalized!r}", file=sys.stderr)
    return normalized


def cmd_show() -> None:
    """显示当前版本。"""
    raw = read_version()
    print(raw)


def cmd_flags() -> None:
    """输出版本属性，写成 ``key=value`` 供 CI 直接塞进 ``$GITHUB_OUTPUT``。

    ``prerelease`` 决定 GitHub Release 要不要标成预发布。用 ``packaging``
    判定而不是自己写正则 —— 「哪些后缀算预发布」是 PEP 440 定义的，
    手写正则迟早会漏掉 ``.post`` 之类的边角。
    """
    version = validate(read_version())

    try:
        from packaging.version import Version
    except ImportError as exc:  # pragma: no cover - CI 里一定有
        raise SystemExit("需要 packaging 才能判定预发布，先跑 uv sync") from exc

    print(f"version={version}")
    print(f"prerelease={'true' if Version(version).is_prerelease else 'false'}")


def cmd_check() -> int:
    """校验版本格式，并确认各包未硬编码版本号。"""
    raw = read_version()
    version = validate(raw)
    print(f"[version] VERSION 文件: {version}")

    problems = 0
    # 1) 各包的 pyproject 应使用 dynamic version，而非硬编码
    for pkg_dir in PACKAGE_DIRS:
        pyproject = pkg_dir / "pyproject.toml"
        if not pyproject.is_file():
            print(f"[version] 缺少 {pyproject}", file=sys.stderr)
            problems += 1
            continue
        text = pyproject.read_text(encoding="utf-8")

        if 'dynamic = ["version"]' not in text:
            print(
                f"[version] {pyproject.relative_to(REPO_ROOT)} 未使用 dynamic version",
                file=sys.stderr,
            )
            problems += 1
        if 'source = "regex"' not in text or "../../VERSION" not in text:
            print(
                f"[version] {pyproject.relative_to(REPO_ROOT)} 未指向 ../../VERSION",
                file=sys.stderr,
            )
            problems += 1
        if re.search(r'^version\s*=\s*"', text, re.MULTILINE):
            print(
                f"[version] {pyproject.relative_to(REPO_ROOT)} 存在硬编码 version 字段",
                file=sys.stderr,
            )
            problems += 1

    # 2) 源码里不应再出现硬编码的 __version__ 字面量
    hardcoded = re.compile(r'^__version__\s*=\s*["\']', re.MULTILINE)
    for pattern in (
        "packages/mograb/src/mograb/__init__.py",
        "apps/cli/src/mograb_cli/__init__.py",
        "apps/api/src/mograb_api/__init__.py",
    ):
        path = REPO_ROOT / pattern
        if path.is_file() and hardcoded.search(path.read_text(encoding="utf-8")):
            print(f"[version] {pattern} 存在硬编码 __version__", file=sys.stderr)
            problems += 1

    if problems:
        print(f"[version] 检查未通过，{problems} 处问题", file=sys.stderr)
        return 1

    print("[version] 检查通过：版本号来源唯一")
    return 0


def cmd_set(new_version: str) -> None:
    """写入新版本号。"""
    normalized = validate(new_version)
    VERSION_FILE.write_text(f"{normalized}\n", encoding="utf-8")
    print(f"[version] 已更新为 {normalized}")
    print("[version] 提醒：同步更新 CHANGELOG.md 后提交")


def main() -> None:
    parser = argparse.ArgumentParser(description="MoGrab 版本号管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("show", help="显示当前版本")
    sub.add_parser("check", help="校验版本格式与来源唯一性")
    sub.add_parser("flags", help="输出版本属性（key=value），供 CI 使用")

    p_set = sub.add_parser("set", help="设置新版本")
    p_set.add_argument("version", help="新的 PEP 440 版本号")

    args = parser.parse_args()

    if args.command == "show":
        cmd_show()
    elif args.command == "check":
        sys.exit(cmd_check())
    elif args.command == "flags":
        cmd_flags()
    elif args.command == "set":
        cmd_set(args.version)


if __name__ == "__main__":
    main()
