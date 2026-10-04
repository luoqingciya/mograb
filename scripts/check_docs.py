# SPDX-License-Identifier: GPL-3.0-only
"""文档内链校验。

扫仓库里的 Markdown，检查 ``[文本](相对路径)`` 指向的文件是否真实存在。
只校验文件是否存在，不校验锚点 —— 锚点写错的情况极少，且校验成本高得多。

用法::

    python scripts/check_docs.py            # 报告断链，有断链则退出码 1
    python scripts/check_docs.py --list     # 额外打印每个文件的出链数量

会跳过 ``node_modules``、``.venv``、``dist`` 这类目录。第三方包自带的
README 里全是断链，扫进来只会淹没真正的问题。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# 这些目录下的 Markdown 不参与校验
SKIP_DIRS = frozenset(
    {
        ".git",
        ".github",  # 工作流里的链接是 YAML 里的注释，不是文档
        ".venv",
        ".workbuddy-ai",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "release-artifacts",
        "site-packages",
    }
)

# 行内链接：[文本](目标)  目标里不含空白和右括号
_LINK_PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# 这些前缀说明是外部资源，不校验
_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "ftp://")


def _iter_markdown() -> list[Path]:
    """列出参与校验的 Markdown 文件。"""
    found: list[Path] = []
    for path in REPO_ROOT.rglob("*.md"):
        if SKIP_DIRS.intersection(path.relative_to(REPO_ROOT).parts):
            continue
        found.append(path)
    return sorted(found)


def _iter_links(text: str) -> list[str]:
    """从 Markdown 正文里抽出所有链接目标。"""
    return _LINK_PATTERN.findall(text)


def check() -> tuple[list[tuple[Path, str, Path]], int]:
    """执行校验。

    返回 ``(断链列表, 链接总数)``。断链元素是
    ``(所在文件, 原始目标, 解析后的绝对路径)``。
    """
    broken: list[tuple[Path, str, Path]] = []
    total = 0

    for doc in _iter_markdown():
        text = doc.read_text(encoding="utf-8")
        for target in _iter_links(text):
            if target.startswith(_EXTERNAL_PREFIXES):
                continue

            # 去掉锚点，只看文件部分
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue

            total += 1
            resolved = (doc.parent / file_part).resolve()
            if not resolved.exists():
                broken.append((doc, target, resolved))

    return broken, total


def main() -> int:
    parser = argparse.ArgumentParser(description="校验文档内链")
    parser.add_argument("--list", action="store_true", help="按文件列出出链数量")
    args = parser.parse_args()

    if args.list:
        for doc in _iter_markdown():
            count = len(_iter_links(doc.read_text(encoding="utf-8")))
            rel = doc.relative_to(REPO_ROOT).as_posix()
            print(f"{count:>4}  {rel}")
        print()

    broken, total = check()

    if not broken:
        print(f"文档内链校验通过：{total} 条链接，全部有效。")
        return 0

    print(f"发现 {len(broken)} 条断链（共检查 {total} 条）：\n")
    for doc, target, resolved in broken:
        try:
            shown = resolved.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            shown = str(resolved)
        print(f"  {doc.relative_to(REPO_ROOT).as_posix()}")
        print(f"      -> {target}")
        print(f"      解析为 {shown}")
    print()
    print("断链要么是路径写错，要么是目标文件被删了 —— 两种情况都要修。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
