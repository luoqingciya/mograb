# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 构建脚本（规划书 §57.2、§57.3）。

用法::

    python scripts/build.py cli      --version 0.1.0    # 构建 CLI（PyInstaller onedir）
    python scripts/build.py backend  --version 0.1.0    # 构建 Desktop 后端 sidecar
    python scripts/build.py clean                        # 清理产物

设计约束（§57.2）：

- 使用 PyInstaller **onedir**，**不追求单文件 EXE**。
- 最终产物**不包含** uv / 开发环境。
- 用户解压后即可运行，无需安装 Python。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "release-artifacts"
BUILD_DIR = REPO_ROOT / "build"

# 各目标产物配置
TARGETS = {
    "cli": {
        "entry": REPO_ROOT / "apps" / "cli" / "src" / "mograb_cli" / "__main__.py",
        "name": "mog",
        "out": ARTIFACTS / "MoGrab-CLI",
    },
    "backend": {
        "entry": REPO_ROOT / "apps" / "api" / "src" / "mograb_api" / "__main__.py",
        "name": "mograb-api",
        "out": ARTIFACTS / "backend",
    },
}

# 需要排除的模块（减小体积、避免误打包）
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "IPython",
    "pytest",
    "pyright",
    "ruff",
]


def build(target: str, version: str) -> Path:
    """构建指定目标。"""
    if target not in TARGETS:
        raise SystemExit(f"未知构建目标: {target}（可选: {', '.join(TARGETS)}）")

    cfg = TARGETS[target]
    entry: Path = cfg["entry"]
    out_dir: Path = cfg["out"]

    if not entry.is_file():
        raise SystemExit(f"入口文件不存在: {entry}")

    print(f"[build] 目标={target} 版本={version}")
    print(f"[build] 入口={entry}")
    print(f"[build] 输出={out_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",  # §57.2：目录型产物，非单文件
        "--name",
        str(cfg["name"]),
        "--distpath",
        str(out_dir),
        "--workpath",
        str(BUILD_DIR / target),
        "--specpath",
        str(BUILD_DIR),
        "--console",
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    args.append(str(entry))

    subprocess.run(args, check=True, cwd=REPO_ROOT)

    print(f"[build] 完成: {out_dir}")
    return out_dir


def clean() -> None:
    """清理构建产物。"""
    for path in (ARTIFACTS, BUILD_DIR):
        if path.exists():
            shutil.rmtree(path)
            print(f"[clean] 已删除 {path}")
    for spec in REPO_ROOT.glob("*.spec"):
        spec.unlink()
        print(f"[clean] 已删除 {spec}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MoGrab 构建脚本")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in (*TARGETS, "all"):
        p = sub.add_parser(name, help=f"构建 {name}")
        p.add_argument("--version", default="0.0.0", help="版本号（写入产物元数据）")

    sub.add_parser("clean", help="清理构建产物")

    args = parser.parse_args()

    if args.command == "clean":
        clean()
    elif args.command == "all":
        for target in TARGETS:
            build(target, args.version)
    else:
        build(args.command, args.version)


if __name__ == "__main__":
    main()
