# SPDX-License-Identifier: GPL-3.0-only
"""Source 领域模型 —— MoGrab Source Specification v1 的 Python 映射。

这是整个项目最重要的契约。字段一经冻结，破坏性变更必须提升
``spec_version`` 并同步 docs/source-spec/source-spec-v1.md。

对规划书的两处修正
------------------

**修正 1：``version`` 语义冲突（P0）**

规划书在三个位置使用了同名但含义不同的 ``version``：

- §7  示例：``version: 1``（Schema 版本）+ ``version_name: 1.0.0``（书源版本）
- §13 manifest：``version: 1.2.0``（书源版本）
- §53 manifest：``version: 1``（Schema 版本）+ ``engine.min_version``

本实现将其彻底拆分为两个字段，语义唯一：

- :attr:`SourceSpec.spec_version` —— Source Specification 的版本（整数，v1 = 1）
- :attr:`SourceSpec.version`      —— 书源自身的语义化版本（字符串，如 ``1.2.0``）

**修正 2：能力判断（P2）**

规划书 §9 的表述「而不是 ``source.search()``」有歧义。正确规则是：
*不得假定能力存在*，因此调用前必须 ``source.supports(Capability.SEARCH)``；
具备能力时调用 ``engine.search(source, ...)`` 完全合法。
本模型通过 :meth:`SourceSpec.supports` 提供该判断。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_serializer,
    model_validator,
)

from .enums import HealthStatus, SourceCapability

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
SPEC_VERSION: int = 1
"""当前引擎实现的 Source Specification 版本。"""

SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
"""书源 ID 规则：小写字母开头，允许小写字母/数字，分隔符 - 或 _。"""

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


# ---------------------------------------------------------------------------
# 变换（Transformer，规划书 §8.3）
# ---------------------------------------------------------------------------
class TransformOp(StrEnum):
    """v1 支持的变换算子。"""

    TRIM = "trim"
    REPLACE = "replace"
    REGEX_REPLACE = "regex_replace"
    JOIN = "join"
    PREPEND = "prepend"
    APPEND = "append"
    URL_JOIN = "url_join"
    DEFAULT = "default"
    REMOVE_HTML = "remove_html"
    NORMALIZE_WHITESPACE = "normalize_whitespace"


class Transform(BaseModel):
    """单个变换步骤。

    支持两种 YAML 写法（在 :meth:`_coerce` 中归一化）::

        transform:
          - trim                       # 无参
          - regex_replace:             # 带参
              pattern: "\\\\s+"
              replacement: " "
    """

    model_config = ConfigDict(extra="forbid")

    op: TransformOp
    pattern: str | None = None
    replacement: str | None = None
    value: str | None = None
    separator: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        """把字符串 / 单键字典写法归一化为标准对象。"""
        if isinstance(data, str):
            return {"op": data}
        if isinstance(data, dict) and "op" not in data and len(data) == 1:
            ((key, params),) = data.items()
            if isinstance(params, dict):
                return {"op": key, **params}
            return {"op": key, "value": params}
        return data

    @model_validator(mode="after")
    def _check_params(self) -> Transform:
        """参数完备性校验。"""
        if self.op is TransformOp.REGEX_REPLACE and not self.pattern:
            raise ValueError("regex_replace 需要 pattern 参数")
        if self.op is TransformOp.REPLACE and self.pattern is None:
            raise ValueError("replace 需要 pattern 参数")
        return self


# ---------------------------------------------------------------------------
# 提取规则（Extractor，规划书 §8.2）
# ---------------------------------------------------------------------------
class RuleType(StrEnum):
    """提取规则类型。"""

    CSS = "css"
    XPATH = "xpath"
    JSONPATH = "jsonpath"
    REGEX = "regex"
    ATTR = "attr"  # 形如 @href / @text，作用于当前节点
    TEXT = "text"


class ExtractRule(BaseModel):
    """提取规则。

    统一字符串语法（在 :meth:`parse` 中解析）::

        ".book-item"                 -> CSS 选择器
        "a@href"                     -> CSS + 取 href 属性
        "@text"                      -> 当前节点文本
        "xpath://div[@id='c']"       -> XPath
        "jsonpath:$.data[*].title"   -> JSONPath
        "regex:第(\\d+)章"           -> 正则（取第 1 捕获组）
    """

    model_config = ConfigDict(extra="forbid")

    type: RuleType
    expression: str
    attribute: str | None = Field(
        default=None,
        description="当 type=css 时，要提取的属性名；text 表示取文本",
    )

    @classmethod
    def parse(cls, raw: str) -> ExtractRule:
        """把 DSL 字符串解析为结构化规则。"""
        text = raw.strip()
        if not text:
            raise ValueError("提取规则不能为空")

        for prefix, rule_type in (
            ("xpath:", RuleType.XPATH),
            ("jsonpath:", RuleType.JSONPATH),
            ("regex:", RuleType.REGEX),
        ):
            if text.lower().startswith(prefix):
                return cls(type=rule_type, expression=text[len(prefix) :])

        if text.startswith("@"):
            return cls(type=RuleType.ATTR, expression=text[1:])

        if "@" in text:
            selector, _, attr = text.rpartition("@")
            if selector:
                return cls(type=RuleType.CSS, expression=selector, attribute=attr)

        return cls(type=RuleType.CSS, expression=text)

    @property
    def raw(self) -> str:
        """还原为 DSL 字符串形式。"""
        if self.type is RuleType.ATTR:
            return f"@{self.expression}"
        if self.type is RuleType.CSS and self.attribute:
            return f"{self.expression}@{self.attribute}"
        if self.type is RuleType.CSS:
            return self.expression
        return f"{self.type.value}:{self.expression}"

    @model_serializer(mode="plain")
    def _to_dsl_string(self) -> str:
        """序列化回 DSL 字符串（``a@href``），而不是 ``{type, expression}`` 字典。

        书源是要给人看、给人改的。存回 YAML 时如果变成一坨嵌套字典，
        就没法手工维护了，所以这里保持原样。
        """
        return self.raw


def _parse_rule(value: Any) -> Any:
    """validator 辅助：字符串 -> ExtractRule。"""
    return ExtractRule.parse(value) if isinstance(value, str) else value


def _parse_rule_map(value: Any) -> Any:
    """validator 辅助：字段映射 -> {name: ExtractRule}。"""
    if isinstance(value, dict):
        return {k: _parse_rule(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# 请求 / 响应（规划书 §8.1）
# ---------------------------------------------------------------------------
class RequestSpec(BaseModel):
    """统一的请求描述。Source 只描述「请求什么」，不负责重试/并发/缓存。"""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: str | dict[str, Any] | None = None
    cookies: dict[str, str] = Field(default_factory=dict)
    encoding: str | None = Field(
        default=None,
        description="强制响应编码；为 None 时由引擎按响应头/内容自动探测",
    )
    timeout_ms: int | None = Field(default=None, ge=100, le=120_000)

    @field_validator("method", mode="before")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper() if isinstance(v, str) else v


class ResponseSpec(BaseModel):
    """响应格式声明。"""

    model_config = ConfigDict(extra="forbid")

    format: Literal["html", "json", "text"] = "html"


# ---------------------------------------------------------------------------
# 各能力的具体规格
# ---------------------------------------------------------------------------
class PaginationSpec(BaseModel):
    """列表型响应的翻页规格（可选）。

    只支持**跟着「下一页」链接走**这一种翻页方式：站点的分页 URL 形态各异
    （``?page=2`` / ``/list_2.html`` / 带 token 的路径），靠猜规律很容易
    在某次改版后静默失效。让页面自己告诉我们下一页在哪，是最稳的做法。

    ``next`` 提取不到值时即为最后一页 —— 这正是站点表达「没有下一页」的
    自然方式（链接消失）。
    """

    model_config = ConfigDict(extra="forbid")

    next: ExtractRule = Field(description="指向「下一页」的提取规则，如 '.pager a@href'")
    max_pages: int = Field(
        default=20,
        ge=2,
        le=200,
        description="翻页上限，防止规则写错时无限抓取",
    )

    @field_validator("next", mode="before")
    @classmethod
    def _v_next(cls, v: Any) -> Any:
        return _parse_rule(v)


class ResultSpec(BaseModel):
    """列表型响应（搜索、目录）的提取规格。"""

    model_config = ConfigDict(extra="forbid")

    list: ExtractRule
    fields: dict[str, ExtractRule] = Field(default_factory=dict)
    reverse: bool = Field(
        default=False,
        description="目录倒序修正（部分站点最新章节在前）",
    )
    paginate: PaginationSpec | None = Field(
        default=None,
        description="翻页规格；为 None 时只抓第一页",
    )

    @field_validator("list", mode="before")
    @classmethod
    def _v_list(cls, v: Any) -> Any:
        return _parse_rule(v)

    @field_validator("fields", mode="before")
    @classmethod
    def _v_fields(cls, v: Any) -> Any:
        return _parse_rule_map(v)


class SearchSpec(BaseModel):
    """搜索能力规格（规划书 §7）。"""

    model_config = ConfigDict(extra="forbid")

    request: RequestSpec
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    result: ResultSpec
    transform: list[Transform] = Field(default_factory=list)


class BookSpec(BaseModel):
    """书籍详情能力规格。"""

    model_config = ConfigDict(extra="forbid")

    request: RequestSpec
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    fields: dict[str, ExtractRule] = Field(default_factory=dict)
    transform: list[Transform] = Field(default_factory=list)

    @field_validator("fields", mode="before")
    @classmethod
    def _v_fields(cls, v: Any) -> Any:
        return _parse_rule_map(v)


class ChapterSpec(BaseModel):
    """章节目录能力规格。"""

    model_config = ConfigDict(extra="forbid")

    request: RequestSpec
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    result: ResultSpec
    transform: list[Transform] = Field(default_factory=list)


class CleanSpec(BaseModel):
    """正文清洗规格（规划书 §21）。"""

    model_config = ConfigDict(extra="forbid")

    remove: list[str] = Field(
        default_factory=lambda: ["script", "style"],
        description="要移除的 CSS 选择器列表（DOM 级删除）",
    )


class ContentSpec(BaseModel):
    """正文能力规格。"""

    model_config = ConfigDict(extra="forbid")

    request: RequestSpec
    response: ResponseSpec = Field(default_factory=ResponseSpec)
    body: ExtractRule
    clean: CleanSpec = Field(default_factory=CleanSpec)
    transform: list[Transform] = Field(default_factory=list)

    @field_validator("body", mode="before")
    @classmethod
    def _parse_body(cls, v: Any) -> Any:
        """支持两种写法：``body: "#content"`` 或 ``body: {selector: "#content"}``。"""
        if isinstance(v, dict):
            if "selector" not in v:
                raise ValueError("content.body 使用字典写法时必须提供 selector")
            return ExtractRule.parse(str(v["selector"]))
        return _parse_rule(v)


# ---------------------------------------------------------------------------
# 网络与权限策略
# ---------------------------------------------------------------------------
class NetworkPolicy(BaseModel):
    """按书源隔离的网络策略（规划书 §15、§38）。

    每个书源持有独立限流器；**禁止**多个来源共用一个全局限制器。
    """

    model_config = ConfigDict(extra="forbid")

    concurrency: int = Field(default=2, ge=1, le=32)
    request_interval_ms: int = Field(default=500, ge=0, le=60_000)
    timeout_ms: int = Field(default=15_000, ge=100, le=120_000)
    retry: int = Field(default=3, ge=0, le=10)
    headers: dict[str, str] = Field(default_factory=dict)


class Permissions(BaseModel):
    """书源权限声明（规划书 §41）。

    v1 策略：network 必需，cookies/script/filesystem 一律 false。
    引擎在加载时强制校验，任何越权声明直接拒绝。
    """

    model_config = ConfigDict(extra="forbid")

    network: list[str] = Field(default_factory=list, description="允许访问的域名白名单")
    cookies: bool = False
    filesystem: bool = False
    script: bool = False

    @model_validator(mode="after")
    def _enforce_v1(self) -> Permissions:
        if self.script:
            raise ValueError("v1 不允许书源声明 script 权限（禁止任意代码执行）")
        if self.filesystem:
            raise ValueError("v1 不允许书源声明 filesystem 权限")
        return self


# ---------------------------------------------------------------------------
# 顶层 Source
# ---------------------------------------------------------------------------
class SourceSpec(BaseModel):
    """一份完整、经过校验的书源定义。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    # --- 清单 ---
    spec_version: int = Field(
        default=SPEC_VERSION,
        description="Source Specification 版本（整数）。当前为 1。",
    )
    id: str = Field(description="书源唯一 ID")
    name: str
    version: str = Field(description="书源自身的语义化版本，如 1.2.0")
    homepage: str | None = Field(default=None, description="被采集站点的首页")
    repository: str | None = Field(
        default=None,
        description="书源自身的发布地址（仓库 / 发布页），供用户自行获取新版",
    )
    description: str | None = None
    license: str | None = Field(default=None, description="书源自身的许可证标识")
    authors: list[str] = Field(default_factory=list)

    # --- 能力 ---
    capabilities: list[SourceCapability] = Field(default_factory=list)

    # --- 策略 ---
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    permissions: Permissions = Field(default_factory=Permissions)

    # --- 各能力规格（按 capabilities 决定是否必需）---
    search: SearchSpec | None = None
    book: BookSpec | None = None
    chapters: ChapterSpec | None = None
    content: ContentSpec | None = None

    # --- 全局变换（作用于所有提取结果）---
    transforms: list[Transform] = Field(default_factory=list)

    # --- 引擎兼容性（规划书 §53）---
    engine_min_version: str | None = None
    engine_max_version: str | None = None

    # ---- 校验 ----
    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        if not SOURCE_ID_RE.match(v):
            raise ValueError(f"非法书源 ID: {v!r}（要求小写字母开头，仅含 a-z0-9-_）")
        return v

    @field_validator("version")
    @classmethod
    def _check_version(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError(f"非法版本号: {v!r}（要求语义化版本，如 1.0.0）")
        return v

    @field_validator("spec_version")
    @classmethod
    def _check_spec_version(cls, v: int) -> int:
        if v != SPEC_VERSION:
            from ..errors import SourceUnsupportedError

            raise SourceUnsupportedError(
                f"不支持的 Source Specification 版本: {v}（当前引擎支持 {SPEC_VERSION}）"
            )
        return v

    @model_validator(mode="after")
    def _check_capability_consistency(self) -> SourceSpec:
        """声明了能力就必须提供对应规格，反之亦然。"""
        mapping: dict[SourceCapability, Any] = {
            SourceCapability.SEARCH: self.search,
            SourceCapability.BOOK: self.book,
            SourceCapability.CHAPTERS: self.chapters,
            SourceCapability.CONTENT: self.content,
        }
        for capability, spec in mapping.items():
            declared = capability in self.capabilities
            provided = spec is not None
            if declared and not provided:
                raise ValueError(f"声明了能力 {capability.value} 但未提供对应规格")
            if provided and not declared:
                raise ValueError(f"提供了 {capability.value} 规格但未在 capabilities 中声明")
        return self

    # ---- 便捷方法 ----
    def supports(self, capability: SourceCapability) -> bool:
        """判断书源是否具备某项能力（规划书 §9）。"""
        return capability in self.capabilities

    @property
    def qualified_id(self) -> str:
        """带版本的完整标识，如 ``example@1.2.0``。"""
        return f"{self.id}@{self.version}"


@dataclass(slots=True)
class InstalledSource:
    """一份已安装的书源：定义本身 + 安装状态。

    为什么要单独一个类型：:class:`SourceSpec` 是书源作者写的东西，
    只包含规范里定义的字段。而「装没装、启没启用、上次体检什么结果、
    从哪个版本升上来的」这些是 MoGrab 自己的记账，不该混进书源定义里 ——
    否则导出书源时会把本机状态也带出去。

    存储层返回这个类型，调度器用 ``.spec`` 取定义即可。
    """

    spec: SourceSpec
    enabled: bool = True
    health: HealthStatus = HealthStatus.UNKNOWN
    installed_version: str = ""
    """当前安装的版本，用于回滚（§56）。"""
    previous_version: str | None = None
    installed_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def is_usable(self) -> bool:
        """启用且未失效。调度器挑书源时用这个判断。"""
        return self.enabled and self.health not in (
            HealthStatus.BROKEN,
            HealthStatus.UNSUPPORTED,
        )


__all__ = [
    "SPEC_VERSION",
    "BookSpec",
    "ChapterSpec",
    "CleanSpec",
    "ContentSpec",
    "ExtractRule",
    "InstalledSource",
    "NetworkPolicy",
    "PaginationSpec",
    "Permissions",
    "RequestSpec",
    "ResponseSpec",
    "ResultSpec",
    "RuleType",
    "SearchSpec",
    "SourceSpec",
    "Transform",
    "TransformOp",
]
