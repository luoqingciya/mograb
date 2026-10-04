# SPDX-License-Identifier: GPL-3.0-only
"""Fixture 测试运行器（规划书 §12、§47）。

书源规则会随站点改版失效。离线快照让作者能在**不访问站点**的前提下验证
规则是否仍然成立 —— 这也是 `mog source test` 的实现。

用例写在书源目录下的 ``fixtures/cases.yaml``：

```yaml
- capability: book
  url: https://example.com/book/1001
  files: [book.html]

- capability: chapters
  url: https://example.com/book/1001
  # 目录分页时按**请求顺序**依次提供多个快照
  files: [book.html, book-page2.html]
```

为什么要显式写 ``url`` 而不是从文件名猜：``chapters`` 的目录常常就在书籍页上
（``{{book.url}}``），猜不出来。而且 ``url_join`` 需要真实的 base URL 才能
验出「相对地址有没有被正确补全」。

为什么 ``files`` 是列表：分页书源会连续发多个请求，快照得按顺序喂进去。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..domain.enums import SourceCapability
from ..domain.source import SourceSpec
from ..errors import SourceExecutionError
from .engine import SourceEngine

CASES_FILENAME = "cases.yaml"
FIXTURES_DIRNAME = "fixtures"


@dataclass(slots=True)
class FixtureCase:
    """一条用例：跑哪个能力、用什么 URL、喂哪些快照。"""

    capability: SourceCapability
    url: str
    files: list[str] = field(default_factory=list)
    keyword: str | None = None

    @property
    def fixture_name(self) -> str:
        """用例在报告里的标识，例如 ``chapters (book.html)``。"""
        return f"{self.capability.value} ({', '.join(self.files) or '无快照'})"


@dataclass(slots=True)
class CaseResult:
    """一条用例的执行结果。"""

    case: FixtureCase
    ok: bool
    summary: str

    @property
    def capability(self) -> str:
        return self.case.capability.value


class FixtureError(Exception):
    """用例文件本身有问题（格式错、快照缺失）。"""


# ---------------------------------------------------------------------------
# 读取用例
# ---------------------------------------------------------------------------
def cases_path(source_dir: Path) -> Path:
    return source_dir / FIXTURES_DIRNAME / CASES_FILENAME


def load_cases(source_dir: Path) -> list[FixtureCase]:
    """读取 ``fixtures/cases.yaml``。

    Raises:
        FixtureError: 文件不存在、格式不对、引用了不存在的快照。
    """
    path = cases_path(source_dir)
    if not path.is_file():
        raise FixtureError(
            f"找不到用例文件 {path}。\n"
            "先写一份 fixtures/cases.yaml，声明每个能力用哪个快照：\n\n"
            "  - capability: book\n"
            "    url: https://example.com/book/1\n"
            "    files: [book.html]\n"
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise FixtureError(f"{path} 的顶层应该是用例列表")

    fixtures_dir = source_dir / FIXTURES_DIRNAME
    cases: list[FixtureCase] = []
    for index, item in enumerate(raw, start=1):
        where = f"{path}: 第 {index} 条"
        if not isinstance(item, dict):
            raise FixtureError(f"{where} 不是映射")

        name = item.get("capability")
        try:
            capability = SourceCapability(str(name))
        except ValueError:
            valid = ", ".join(c.value for c in SourceCapability)
            raise FixtureError(f"{where} 的能力名非法: {name!r}（可选 {valid}）") from None

        url = item.get("url")
        if not url:
            raise FixtureError(f"{where} 缺少 url")

        files = item.get("files") or []
        if isinstance(files, str):
            files = [files]
        if not files:
            raise FixtureError(f"{where} 没有声明 files")

        for name_ in files:
            if not (fixtures_dir / name_).is_file():
                raise FixtureError(f"{where} 引用的快照不存在: {fixtures_dir / name_}")

        cases.append(
            FixtureCase(
                capability=capability,
                url=str(url),
                files=[str(f) for f in files],
                keyword=item.get("keyword"),
            )
        )
    return cases


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
class _SnapshotResponse:
    """一页快照伪装成的 HTTP 响应。"""

    def __init__(self, path: Path, url: str) -> None:
        self.content = path.read_bytes()
        self.encoding = "utf-8"
        self.status_code = 200
        self.url = url


class _SnapshotFetcher:
    """按**请求顺序**依次返回快照的假 fetcher。

    按顺序而不是按 URL 匹配：分页链接长什么样只有站点知道，让用例去描述
    「第二页的快照是哪个文件」比让它复刻分页 URL 规则简单得多。
    """

    def __init__(self, files: list[Path]) -> None:
        self._files = files
        self.calls: list[str] = []

    async def fetch(self, method: str, url: str, **kwargs: Any) -> Any:
        index = len(self.calls)
        self.calls.append(url)
        if index >= len(self._files):
            raise FixtureError(
                f"引擎请求了第 {index + 1} 个页面（{url}），但用例只给了 {len(self._files)} 个快照"
            )
        return _SnapshotResponse(self._files[index], url)


async def run_cases(
    spec: SourceSpec, cases: list[FixtureCase], source_dir: Path
) -> list[CaseResult]:
    """逐条跑用例，返回结果。**不抛异常** —— 单条失败只记进结果。"""
    fixtures_dir = source_dir / FIXTURES_DIRNAME
    results: list[CaseResult] = []

    for case in cases:
        fetcher = _SnapshotFetcher([fixtures_dir / f for f in case.files])
        engine = SourceEngine(fetcher)
        try:
            summary = await _run_one(engine, spec, case)
        except Exception as exc:
            results.append(CaseResult(case=case, ok=False, summary=_describe(exc)))
        else:
            results.append(CaseResult(case=case, ok=True, summary=summary))

    return results


async def _run_one(engine: SourceEngine, spec: SourceSpec, case: FixtureCase) -> str:
    """跑一条用例，成功时返回一句摘要。"""
    if case.capability is SourceCapability.SEARCH:
        keyword = case.keyword or "test"
        hits = await engine.search(spec, keyword)
        if not hits:
            raise SourceExecutionError(f"搜索「{keyword}」没有命中任何结果")
        return f"{len(hits)} 条结果，首条 {hits[0].title!r}"

    if case.capability is SourceCapability.BOOK:
        draft = await engine.fetch_book(spec, case.url)
        return f"书名 {draft.title!r}，作者 {draft.author or '（无）'}"

    if case.capability is SourceCapability.CHAPTERS:
        chapters = await engine.fetch_chapters(spec, case.url)
        if not chapters:
            raise SourceExecutionError("目录里没有任何章节")
        return f"{len(chapters)} 章，首章 {chapters[0].title!r}"

    if case.capability is SourceCapability.CONTENT:
        content = await engine.fetch_content(spec, case.url)
        if not content.strip():
            raise SourceExecutionError("正文为空")
        return f"{len(content)} 字符，段落 {len([p for p in content.splitlines() if p.strip()])} 段"

    raise SourceExecutionError(f"暂不支持测试能力 {case.capability.value}")


def _describe(exc: BaseException) -> str:
    """把异常转成一句给人看的原因。"""
    if isinstance(exc, FixtureError):
        return str(exc)
    if isinstance(exc, SourceExecutionError):
        detail = getattr(exc, "details", None) or {}
        extra = f"（{detail}）" if detail else ""
        return f"{exc}{extra}"
    return f"{type(exc).__name__}: {exc}"


__all__ = [
    "CASES_FILENAME",
    "FIXTURES_DIRNAME",
    "CaseResult",
    "FixtureCase",
    "FixtureError",
    "cases_path",
    "load_cases",
    "run_cases",
]
