# SPDX-License-Identifier: GPL-3.0-only
"""MoGrab 发布辅助脚本（规划书 §57.6、§57.7、§57.8）。

用法::

    python scripts/release.py checksums --dir release-artifacts
    python scripts/release.py notes --version 0.1.0
    python scripts/release.py verify --dir release-artifacts

说明：正式的 Release 由 GitHub Actions 完成（见 .github/workflows/release.yml）。
本脚本用于本地预演与产物校验。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
CHECKSUM_FILE = "SHA256SUMS.txt"


def sha256_of(path: Path) -> str:
    """计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_checksums(directory: Path) -> Path:
    """为目录下所有产物生成 SHA256SUMS.txt（§57.8）。"""
    if not directory.is_dir():
        raise SystemExit(f"目录不存在: {directory}")

    artifacts = sorted(p for p in directory.rglob("*") if p.is_file() and p.name != CHECKSUM_FILE)
    if not artifacts:
        raise SystemExit(f"目录中没有产物: {directory}")

    lines = [f"{sha256_of(p)}  {p.relative_to(directory).as_posix()}" for p in artifacts]
    target = directory / CHECKSUM_FILE
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[release] 已生成 {target}（{len(lines)} 个文件）")
    return target


def verify_checksums(directory: Path) -> int:
    """校验 SHA256SUMS.txt。返回失败数量。"""
    checksum_path = directory / CHECKSUM_FILE
    if not checksum_path.is_file():
        raise SystemExit(f"校验和文件不存在: {checksum_path}")

    failures = 0
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, _, relative = line.partition("  ")
        path = directory / relative
        if not path.is_file():
            print(f"[FAIL] 文件缺失: {relative}", file=sys.stderr)
            failures += 1
            continue
        actual = sha256_of(path)
        if actual != expected:
            print(f"[FAIL] 校验和不符: {relative}", file=sys.stderr)
            failures += 1
        else:
            print(f"[ OK ] {relative}")

    print(f"[release] 校验完成，失败 {failures} 项")
    return failures


def extract_notes(version: str) -> str:
    """从 CHANGELOG.md 提取指定版本的发布说明。"""
    if not CHANGELOG.is_file():
        raise SystemExit(f"CHANGELOG 不存在: {CHANGELOG}")

    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^##\s*\[?{re.escape(version)}\]?.*?$(.*?)(?=^##\s|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        print(f"[release] CHANGELOG 中未找到版本 {version}，返回占位说明")
        return f"Release {version}\n"
    return match.group(0).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="MoGrab 发布辅助")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ck = sub.add_parser("checksums", help="生成 SHA256SUMS.txt")
    p_ck.add_argument("--dir", type=Path, default=REPO_ROOT / "release-artifacts")

    p_vf = sub.add_parser("verify", help="校验 SHA256SUMS.txt")
    p_vf.add_argument("--dir", type=Path, default=REPO_ROOT / "release-artifacts")

    p_nt = sub.add_parser("notes", help="提取版本发布说明")
    p_nt.add_argument("--version", required=True)

    args = parser.parse_args()

    if args.command == "checksums":
        generate_checksums(args.dir)
    elif args.command == "verify":
        sys.exit(1 if verify_checksums(args.dir) else 0)
    elif args.command == "notes":
        sys.stdout.write(extract_notes(args.version))


if __name__ == "__main__":
    main()
