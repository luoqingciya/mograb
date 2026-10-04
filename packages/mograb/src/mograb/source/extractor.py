# SPDX-License-Identifier: GPL-3.0-only
"""Extractor —— 统一的提取接口（规划书 §8.2）。

设计要点：

- 所有规则类型（CSS / XPath / JSONPath / Regex / Attr / Text）实现同一个
  :class:`Extractor` 协议，Source Engine 不需要关心具体规则类型。
- :func:`extract_many` 用于列表型提取（搜索结果、章节目录）；
  :func:`extract_one` 用于单值提取（书籍字段）。
- 解析引擎统一为 ``lxml``（CSS 经 ``cssselect`` 转换），
  避免同时维护 selectolax / lxml 两套语义（规划书 §58 的待定项已裁决）。

未匹配时的行为由 :attr:`ExtractResult.matched` 表达，**不抛异常**——
由上层（Engine / Validator）决定是「字段可选」还是「致命错误」。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, cast, runtime_checkable

from lxml import html  # type: ignore[import-untyped]

from ..domain.source import ExtractRule, RuleType

# 匹配空白（用于 text 归一）
_WS_RE = re.compile(r"\s+")


@dataclass(slots=True)
class ExtractResult:
    """提取结果。

    Attributes:
        values: 提取到的值列表（单值提取时长度为 0 或 1）。
        matched: 是否命中至少一个节点/捕获。
        rule: 产生该结果的规则，便于错误定位。
    """

    values: list[str] = field(default_factory=list)
    matched: bool = False
    rule: ExtractRule | None = None

    @property
    def value(self) -> str | None:
        """取第一个值；无匹配返回 None。"""
        return self.values[0] if self.values else None


@dataclass(slots=True)
class Document:
    """已解析的响应文档。

    同时持有原始字节与解析后的树，避免重复解析；
    ``encoding`` 记录实际使用的编码（引擎自动探测或书源强制）。
    """

    raw: bytes
    encoding: str = "utf-8"
    kind: str = "html"  # html | json | text

    _tree: Any = None
    _data: Any = None

    @property
    def tree(self) -> Any:
        """惰性解析为 lxml 树（HTML 或 XML）。

        注意：必须先按 ``self.encoding`` 解码为 ``str`` 再解析。
        直接把 bytes 交给 ``lxml.html.fromstring`` 会让 lxml 自行探测编码，
        对未声明 charset 的中文页面会退化为 latin-1 而产生乱码。
        """
        if self._tree is None:
            self._tree = html.fromstring(self.raw.decode(self.encoding, errors="replace"))
        return self._tree

    @property
    def data(self) -> Any:
        """惰性解析为 JSON 对象。"""
        if self._data is None:
            import json

            self._data = json.loads(self.raw.decode(self.encoding))
        return self._data


@runtime_checkable
class Extractor(Protocol):
    """提取器协议。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        """按规则从文档中提取。"""
        ...


# ---------------------------------------------------------------------------
# 具体实现
# ---------------------------------------------------------------------------
class CssExtractor:
    """CSS 选择器提取器（含 ``selector@attr`` 语法）。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        tree = document.tree
        nodes = tree.cssselect(rule.expression)
        values: list[str] = []
        for node in nodes:
            if rule.attribute is None or rule.attribute == "text":
                values.append(_normalize_text(node.text_content()))
            elif rule.attribute in ("html", "inner_html"):
                values.append(html.tostring(node, encoding="unicode"))
            elif rule.attribute == "own_text":
                values.append(_normalize_text(node.text or ""))
            else:
                attr = node.get(rule.attribute)
                if attr is not None:
                    values.append(attr)
        return ExtractResult(values=values, matched=bool(values), rule=rule)


class XPathExtractor:
    """XPath 提取器。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        tree = document.tree
        result = tree.xpath(rule.expression)
        values: list[str] = []
        for item in result:
            if isinstance(item, str):
                values.append(item.strip())
            elif hasattr(item, "text_content"):
                values.append(_normalize_text(item.text_content()))
            else:
                values.append(str(item))
        return ExtractResult(values=values, matched=bool(values), rule=rule)


class JsonPathExtractor:
    """JSONPath 提取器。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        from jsonpath_ng.ext import parse  # type: ignore[import-untyped]

        matches = parse(rule.expression).find(document.data)
        values = [str(m.value) for m in matches if m.value is not None]
        return ExtractResult(values=values, matched=bool(values), rule=rule)


class RegexExtractor:
    """正则提取器：命中时取第 1 捕获组（无捕获组则取整体）。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        text = document.raw.decode(document.encoding, errors="replace")
        values = [
            (m.group(1) if m.groups() else m.group(0)) for m in re.finditer(rule.expression, text)
        ]
        return ExtractResult(values=values, matched=bool(values), rule=rule)


class AttrExtractor:
    """``@attr`` 提取器：作用于文档根/当前上下文。"""

    def extract(self, document: Document, rule: ExtractRule) -> ExtractResult:
        root = document.tree
        if rule.expression == "text":
            return ExtractResult(
                values=[_normalize_text(root.text_content())], matched=True, rule=rule
            )
        attr = root.get(rule.expression)
        values = [attr] if attr is not None else []
        return ExtractResult(values=values, matched=bool(values), rule=rule)


_EXTRACTORS: dict[RuleType, Extractor] = {
    RuleType.CSS: CssExtractor(),
    RuleType.XPATH: XPathExtractor(),
    RuleType.JSONPATH: JsonPathExtractor(),
    RuleType.REGEX: RegexExtractor(),
    RuleType.ATTR: AttrExtractor(),
    RuleType.TEXT: AttrExtractor(),
}


def get_extractor(rule_type: RuleType) -> Extractor:
    """按规则类型取提取器；未知类型抛 ``ParseError``。"""
    try:
        return _EXTRACTORS[rule_type]
    except KeyError as exc:  # pragma: no cover - 由枚举保证
        from ..errors import ParseError

        raise ParseError(f"不支持的提取规则类型: {rule_type}") from exc


def extract_one(document: Document, rule: ExtractRule) -> str | None:
    """单值提取，返回第一个值或 None。"""
    return get_extractor(rule.type).extract(document, rule).value


def extract_many(
    document: Document,
    list_rule: ExtractRule,
    field_rules: dict[str, ExtractRule],
) -> list[dict[str, str | None]]:
    """列表型提取：先定位列表项，再在每一项内提取字段。

    按 ``list_rule`` 的类型分流：``jsonpath`` 走 JSON 路径，其余走 DOM。
    **不能只按 ``document.kind`` 判断** —— 书源可能对 HTML 响应声明 JSONPath
    （虽然少见），规则类型才是真正的意图。

    Returns:
        与列表项一一对应的字典列表；未命中的字段值为 ``None``。
    """
    if list_rule.type is RuleType.JSONPATH:
        return _extract_many_json(document, list_rule, field_rules)
    return _extract_many_dom(document, list_rule, field_rules)


def _extract_many_dom(
    document: Document,
    list_rule: ExtractRule,
    field_rules: dict[str, ExtractRule],
) -> list[dict[str, str | None]]:
    """DOM 型列表提取。

    实现方式为「逐项下钻」：对每个列表节点构造子树文档，再执行字段规则，
    保证 ``@href`` 等相对规则作用于列表项本身而非整个文档。
    """
    tree = document.tree
    nodes = tree.cssselect(list_rule.expression)
    rows: list[dict[str, str | None]] = []
    for node in nodes:
        # 逐项下钻：把列表项序列化为独立文档，使相对规则（@href 等）
        # 作用于该项本身而非整个文档。统一以 utf-8 序列化并同步声明编码。
        sub = Document(
            raw=cast(bytes, html.tostring(node, encoding="utf-8")),
            encoding="utf-8",
            kind="html",
        )
        row: dict[str, str | None] = {}
        for name, rule in field_rules.items():
            row[name] = extract_one(sub, rule)
        rows.append(row)
    return rows


def _extract_many_json(
    document: Document,
    list_rule: ExtractRule,
    field_rules: dict[str, ExtractRule],
) -> list[dict[str, str | None]]:
    """JSON 型列表提取。

    与 DOM 版同样是「逐项下钻」：把每个列表项包成独立文档，字段规则在
    该项内部求值，所以 ``jsonpath:$.title`` 取的是「该项的 title」。
    """
    from jsonpath_ng.ext import parse  # type: ignore[import-untyped]

    items: list[Any] = []
    for match in parse(list_rule.expression).find(document.data):
        value = match.value
        if value is None:
            continue
        # 匹配到数组时按元素展开，于是 `$.data.list` 和 `$.data.list[*]`
        # 两种写法都成立 —— 前者更贴近「取列表」的直觉，后者更显式。
        if isinstance(value, list):
            items.extend(value)
        else:
            items.append(value)

    rows: list[dict[str, str | None]] = []
    for item in items:
        sub = Document(
            raw=json.dumps(item, ensure_ascii=False).encode("utf-8"),
            encoding="utf-8",
            kind="json",
        )
        rows.append({name: extract_one(sub, rule) for name, rule in field_rules.items()})
    return rows


def _normalize_text(text: str) -> str:
    """折叠空白并去除首尾空格。"""
    return _WS_RE.sub(" ", text).strip()


__all__ = [
    "AttrExtractor",
    "CssExtractor",
    "Document",
    "ExtractResult",
    "Extractor",
    "JsonPathExtractor",
    "RegexExtractor",
    "XPathExtractor",
    "extract_many",
    "extract_one",
    "get_extractor",
]
