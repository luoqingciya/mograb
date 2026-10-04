# SPDX-License-Identifier: GPL-3.0-only
"""Source Validator / Linter —— 语义校验（规划书 §10、§11）。

与 :mod:`loader` 的分工：

- ``loader``  ：结构校验（字段是否存在、类型是否正确、版本是否合法）
- ``validator``：语义校验（选择器能否编译、模板变量是否声明、
  权限与域名是否一致、clean 规则是否覆盖常见噪声节点）

Linter 的输出必须包含：**错误位置 + 字段路径 + 原因 + 解决建议**（§11），
而不是笼统的 "Invalid source"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from cssselect import SelectorError  # type: ignore[import-untyped]
from cssselect import parse as css_parse
from lxml import etree  # type: ignore[import-untyped]

from ..domain.source import RuleType, SourceSpec
from .request import find_variables

_KNOWN_VARIABLES: frozenset[str] = frozenset(
    {
        "keyword",
        "page",
        "user_agent",
        "book.url",
        "book.id",
        "book.title",
        "chapter.url",
        "chapter.index",
        "chapter.id",
    }
)
"""v1 已知的模板变量；``config.*`` 前缀单独放行。"""


class Severity(StrEnum):
    """诊断级别。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(slots=True)
class Diagnostic:
    """一条 linter 诊断。"""

    severity: Severity
    path: str
    message: str
    hint: str | None = None

    def format(self) -> str:
        """人类可读输出。"""
        head = f"[{self.severity.value.upper()}] {self.path}: {self.message}"
        return f"{head}\n    → {self.hint}" if self.hint else head


@dataclass(slots=True)
class LintReport:
    """lint 汇总结果。"""

    source_id: str
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity is Severity.WARNING]

    @property
    def is_ready(self) -> bool:
        """无 ERROR 即视为可用。"""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "schema": "PASS" if self.is_ready else "FAIL",
            "errors": [d.format() for d in self.errors],
            "warnings": [d.format() for d in self.warnings],
            "result": "READY" if self.is_ready else "BROKEN",
        }


def lint(source: SourceSpec) -> LintReport:
    """对书源执行全部语义检查。"""
    report = LintReport(source_id=source.id)

    _check_selectors(source, report)
    _check_templates(source, report)
    _check_permissions(source, report)
    _check_clean_rules(source, report)
    _check_optional_fields(source, report)

    return report


# ---------------------------------------------------------------------------
# 各项检查
# ---------------------------------------------------------------------------
def _check_selectors(source: SourceSpec, report: LintReport) -> None:
    """校验所有 CSS/XPath 选择器可编译。"""
    for path, rule in _iter_rules(source):
        if rule.type is RuleType.CSS:
            try:
                css_parse(rule.expression)
            except SelectorError as exc:
                report.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        path,
                        f"非法 CSS 选择器: {rule.expression!r} ({exc})",
                        hint="检查括号/引号是否闭合，或改用 xpath: 前缀",
                    )
                )
        elif rule.type is RuleType.XPATH:
            try:
                etree.XPath(rule.expression)
            except etree.XPathSyntaxError as exc:
                report.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        path,
                        f"非法 XPath: {rule.expression!r} ({exc})",
                        hint="检查 xpath 表达式语法",
                    )
                )


def _check_templates(source: SourceSpec, report: LintReport) -> None:
    """校验模板变量均已声明。"""
    for path, template in _iter_templates(source):
        for name in find_variables(template):
            if name in _KNOWN_VARIABLES or name.startswith("config."):
                continue
            report.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    path,
                    f"未定义的模板变量: {{{{{name}}}}}",
                    hint=f"可用变量: {', '.join(sorted(_KNOWN_VARIABLES))}",
                )
            )


def _check_permissions(source: SourceSpec, report: LintReport) -> None:
    """校验请求域名都在 permissions.network 白名单内。"""
    allowed = set(source.permissions.network)
    if not allowed:
        report.diagnostics.append(
            Diagnostic(
                Severity.WARNING,
                "permissions.network",
                "未声明允许访问的域名",
                hint="建议显式列出书源访问的域名，便于用户审阅",
            )
        )
        return

    for path, url_template in _iter_urls(source):
        host = _extract_host(url_template)
        if host and not any(host.endswith(a) for a in allowed):
            report.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    path,
                    f"域名 {host} 不在 permissions.network 白名单中",
                    hint=f"将该域名加入 permissions.network: {host}",
                )
            )


def _check_clean_rules(source: SourceSpec, report: LintReport) -> None:
    """提示正文清洗未覆盖常见噪声节点（规划书 §11 示例）。"""
    if source.content is None:
        return
    remove = set(source.content.clean.remove)
    for noisy in ("script", "style"):
        if noisy not in remove:
            report.diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "content.clean.remove",
                    f"未移除常见的 {noisy} 节点",
                    hint=f"在 content.clean.remove 中加入 {noisy!r}",
                )
            )


def _check_optional_fields(source: SourceSpec, report: LintReport) -> None:
    """提示可选字段缺失（不阻断）。"""
    if source.search is not None:
        for required in ("title", "url"):
            if required not in source.search.result.fields:
                report.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        "search.result.fields",
                        f"搜索结果缺少必需字段 {required!r}",
                        hint=f"补充 search.result.fields.{required}",
                    )
                )
        if "author" not in source.search.result.fields:
            report.diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "search.result.fields.author",
                    "搜索结果未提供 author 字段",
                    hint="作者信息将留空",
                )
            )


# ---------------------------------------------------------------------------
# 遍历辅助
# ---------------------------------------------------------------------------
def _iter_rules(source: SourceSpec):
    """遍历所有 (字段路径, 提取规则)。"""
    if source.search:
        yield "search.result.list", source.search.result.list
        for name, rule in source.search.result.fields.items():
            yield f"search.result.fields.{name}", rule
    if source.book:
        for name, rule in source.book.fields.items():
            yield f"book.fields.{name}", rule
    if source.chapters:
        yield "chapters.result.list", source.chapters.result.list
        for name, rule in source.chapters.result.fields.items():
            yield f"chapters.result.fields.{name}", rule
    if source.content:
        yield "content.body", source.content.body


def _iter_templates(source: SourceSpec):
    """遍历所有 (路径, 模板字符串)。"""
    for name, spec in (
        ("search", source.search),
        ("book", source.book),
        ("chapters", source.chapters),
        ("content", source.content),
    ):
        if spec is None:
            continue
        req = spec.request
        yield f"{name}.request.url", req.url
        for key, value in req.headers.items():
            yield f"{name}.request.headers.{key}", value
        for key, value in req.query.items():
            yield f"{name}.request.query.{key}", str(value)


def _iter_urls(source: SourceSpec):
    """遍历所有请求 URL 模板。"""
    for name, spec in (
        ("search", source.search),
        ("book", source.book),
        ("chapters", source.chapters),
        ("content", source.content),
    ):
        if spec is not None:
            yield f"{name}.request.url", spec.request.url


_HOST_RE = re.compile(r"^[a-zA-Z]+://([^/?#]+)")


def _extract_host(url_template: str) -> str | None:
    """从 URL 模板中提取主机名；含未解析变量时返回 None。"""
    if "{{" in url_template:
        return None
    match = _HOST_RE.match(url_template)
    if not match:
        return None
    return match.group(1).split(":")[0].lower()


__all__ = ["Diagnostic", "LintReport", "Severity", "lint"]
