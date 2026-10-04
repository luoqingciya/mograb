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


def _force_utf8_output() -> None:
    """把标准输出切到 UTF-8。

    Windows 控制台默认编码是 cp1252 或 cp936，直接 print 中文会抛
    UnicodeEncodeError。本地和 CI 行为要一致，所以显式设置。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_force_utf8_output()

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO_ROOT / "release-artifacts"
BUILD_DIR = REPO_ROOT / "build"

# 各目标产物配置
#
# entry 用 scripts/ 下的专用入口，而不是包的 __main__.py —— 后者是相对导入，
# 被 PyInstaller 当独立脚本跑时会失败。
#
# paths 显式给出源码目录：包是以 editable 方式装的，PyInstaller 未必能顺着
# editable finder 找到源码，直接指路径更可靠。
TARGETS = {
    "cli": {
        "entry": REPO_ROOT / "scripts" / "entry_cli.py",
        "name": "mog",
        "out": ARTIFACTS / "MoGrab-CLI",
        "paths": [
            REPO_ROOT / "apps" / "cli" / "src",
            REPO_ROOT / "packages" / "mograb" / "src",
        ],
        "metadata": ["mograb", "mograb-cli"],
    },
    "backend": {
        "entry": REPO_ROOT / "scripts" / "entry_api.py",
        "name": "mograb-api",
        "out": ARTIFACTS / "backend",
        "paths": [
            REPO_ROOT / "apps" / "api" / "src",
            REPO_ROOT / "packages" / "mograb" / "src",
        ],
        "metadata": ["mograb", "mograb-api"],
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

# 动态导入、PyInstaller 静态分析发现不了的模块
HIDDEN_IMPORTS = [
    # SQLAlchemy 的 dialect 是按名字动态加载的
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    # uvicorn 的运行期依赖
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
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
    for module in HIDDEN_IMPORTS:
        args += ["--hidden-import", module]
    for source_path in cfg["paths"]:
        args += ["--paths", str(source_path)]
    # 把 dist-info 元数据一起打进去。版本号是运行时从
    # importlib.metadata 读的，不复制元数据的话会退化成 0.0.0+unknown。
    for dist in cfg["metadata"]:
        args += ["--copy-metadata", dist]
    args.append(str(entry))

    subprocess.run(args, check=True, cwd=REPO_ROOT)

    flatten_dist(out_dir, str(cfg["name"]))

    print(f"[build] 完成: {out_dir}")
    return out_dir


def flatten_dist(out_dir: Path, name: str) -> None:
    """把 PyInstaller 多套的那层目录拍平。

    PyInstaller 的 onedir 产物固定是 ``<distpath>/<name>/...``，
    拍平之后可执行文件直接落在 ``out_dir`` 下，打包出来的 ZIP 里顶层就是
    ``MoGrab-CLI/``，不会多一层 ``mog/``。

    注意 Linux：可执行文件名和目录名都叫 ``mog``，逐个搬的话第一个就撞上自己
    （目标路径正是 nested 本身）。所以先把整层挪到临时目录再搬。
    """
    nested = out_dir / name
    if not nested.is_dir():
        return

    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    nested.rename(staging)

    try:
        for item in staging.iterdir():
            target = out_dir / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
    finally:
        if staging.exists():
            shutil.rmtree(staging)


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
