# SPDX-License-Identifier: GPL-3.0-only
"""Request 构造与模板变量替换（规划书 §8.1）。

书源通过 ``{{var}}`` 引用运行时变量。v1 支持的变量命名空间：

===================  ==============================================
变量                  含义
===================  ==============================================
``{{keyword}}``       搜索关键词（URL 编码由引擎负责）
``{{book.url}}``      书籍详情页 URL
``{{book.id}}``       来源站书籍 ID
``{{chapter.url}}``   章节页 URL
``{{chapter.index}}`` 章节序号
``{{page}}``          分页页码
``{{user_agent}}``    引擎提供的 UA（书源不应硬编码）
``{{config.<key>}}``  用户配置项
===================  ==============================================

未定义的变量会抛 ``SourceExecutionError``（而非静默替换为空字符串），
以便在 linter 与运行时尽早暴露书源错误。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain.source import RequestSpec
from ..errors import SourceExecutionError

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")

# 引擎注入的只读变量
BUILTIN_VARS: dict[str, str] = {
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 MoGrab/0.1"
    ),
}


@dataclass(slots=True)
class TemplateContext:
    """模板变量上下文。

    采用「扁平点号键」存储，例如 ``book.url`` / ``chapter.index``，
    与书源 DSL 中的写法一一对应，避免嵌套字典的取值歧义。
    """

    values: dict[str, Any] = field(default_factory=dict)

    def with_values(self, **kwargs: Any) -> TemplateContext:
        """派生出携带附加变量的新上下文。"""
        merged = {**self.values, **kwargs}
        return TemplateContext(values=merged)

    def get(self, name: str, default: Any = None) -> Any:
        if name in self.values:
            return self.values[name]
        if name in BUILTIN_VARS:
            return BUILTIN_VARS[name]
        return default


@dataclass(slots=True)
class RenderedRequest:
    """模板替换后的具体请求。"""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, str] = field(default_factory=dict)
    data: str | dict[str, Any] | None = None
    cookies: dict[str, str] = field(default_factory=dict)
    encoding: str | None = None
    timeout_ms: int | None = None


def render(template: str, context: TemplateContext, *, strict: bool = True) -> str:
    """替换模板中的 ``{{var}}``。

    Args:
        template: 含变量的字符串。
        context: 变量上下文。
        strict: 为 True 时，未定义变量抛错；为 False 时保留原样。

    Raises:
        SourceExecutionError: ``strict=True`` 且变量未定义。
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = context.get(name)
        if value is None:
            if strict:
                raise SourceExecutionError(
                    f"未定义的模板变量: {{{{{name}}}}}",
                    details={"variable": name, "template": template},
                )
            return match.group(0)
        return str(value)

    return _VAR_RE.sub(_sub, template)


def find_variables(template: str) -> set[str]:
    """静态提取模板中引用的变量名（供 Linter 做「未定义变量」检查）。"""
    return {m.group(1) for m in _VAR_RE.finditer(template)}


def build_request(
    spec: RequestSpec,
    context: TemplateContext,
    *,
    default_headers: Mapping[str, str] | None = None,
) -> RenderedRequest:
    """把书源的 :class:`RequestSpec` 渲染为具体请求。

    Args:
        spec: 书源里声明的请求规格。
        context: 模板变量上下文。
        default_headers: 来源级默认请求头（来自 ``network.headers``）。
            会被 ``request.headers`` 覆盖 —— 越具体的声明优先级越高。
            两处都能写是有意的：UA / Referer 这类对整站通用的放 ``network``，
            只在某个端点需要的放 ``request``。
    """
    headers = {k: render(v, context) for k, v in (default_headers or {}).items()}
    headers.update({k: render(v, context) for k, v in spec.headers.items()})

    return RenderedRequest(
        method=spec.method,
        url=render(spec.url, context),
        headers=headers,
        params={k: render(str(v), context) for k, v in spec.query.items()},
        data=_render_body(spec.body, context),
        cookies={k: render(v, context) for k, v in spec.cookies.items()},
        encoding=spec.encoding,
        timeout_ms=spec.timeout_ms,
    )


def _render_body(body: str | dict[str, Any] | None, context: TemplateContext) -> Any:
    if body is None:
        return None
    if isinstance(body, str):
        return render(body, context)
    return {k: render(str(v), context) for k, v in body.items()}


__all__ = [
    "BUILTIN_VARS",
    "RenderedRequest",
    "TemplateContext",
    "build_request",
    "find_variables",
    "render",
]
