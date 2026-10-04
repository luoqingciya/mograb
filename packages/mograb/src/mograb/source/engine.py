# SPDX-License-Identifier: GPL-3.0-only
"""Source Engine —— 执行书源规则，产出领域对象（规划书 §3.2、§3.3）。

职责边界（**严格遵守**）：

- 引擎负责：构造请求、调用网络层、执行提取与变换、组装草稿对象。
- 引擎**不**负责：重试、并发调度、缓存、任务状态、数据库、导出。
  这些属于 Network / Task / Storage / Export 层。

因此引擎是「纯函数式」的：给定书源 + 上下文 + HTTP 客户端，产出确定结果。
这使得它可以在 fixture 测试中完全离线运行（规划书 §12）。
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field, replace
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin

from ..domain.enums import BookStatus, SourceCapability
from ..domain.source import ResultSpec, SourceSpec
from ..errors import SourceExecutionError, SourceUnsupportedError
from ..logging.setup import get_logger
from .extractor import Document, extract_many, extract_one
from .request import RenderedRequest, TemplateContext, build_request
from .transformer import apply_transforms, apply_transforms_many

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 引擎产出的草稿对象（尚未分配 MoGrab 内部 ID）
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class SearchResult:
    """一条搜索结果。"""

    source_id: str
    title: str
    url: str
    author: str | None = None
    cover_url: str | None = None
    intro: str | None = None
    extra: dict[str, str | None] = field(default_factory=dict)


@dataclass(slots=True)
class BookDraft:
    """书籍详情草稿。"""

    source_id: str
    source_book_id: str
    url: str
    title: str
    author: str | None = None
    intro: str | None = None
    cover_url: str | None = None
    latest_chapter: str | None = None
    status: BookStatus = BookStatus.UNKNOWN
    extra: dict[str, str | None] = field(default_factory=dict)


@dataclass(slots=True)
class ChapterDraft:
    """章节目录项草稿。"""

    title: str
    url: str
    index: int
    source_chapter_id: str | None = None


# ---------------------------------------------------------------------------
# 网络依赖抽象（依赖倒置：引擎只依赖协议，不依赖 httpx）
# ---------------------------------------------------------------------------
@runtime_checkable
class ResponseLike(Protocol):
    """网络层返回的最小响应契约。"""

    content: bytes
    encoding: str | None
    status_code: int
    url: str


@runtime_checkable
class Fetcher(Protocol):
    """引擎所需的网络能力。由 :mod:`mograb.network.client` 实现。"""

    async def fetch(
        self,
        method: str,
        url: str,
        *,
        source_id: str = ...,
        headers: dict[str, str] | None = ...,
        params: dict[str, str] | None = ...,
        data: object = ...,
        cookies: dict[str, str] | None = ...,
        encoding: str | None = ...,
        timeout_ms: int | None = ...,
        allowed_domains: Collection[str] | None = ...,
        concurrency: int | None = ...,
        min_interval: float | None = ...,
        max_retries: int | None = ...,
    ) -> ResponseLike: ...


# ---------------------------------------------------------------------------
# 引擎
# ---------------------------------------------------------------------------
class SourceEngine:
    """按书源规则执行搜索 / 详情 / 目录 / 正文。"""

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    # ---- 能力守卫 ----
    @staticmethod
    def _require(source: SourceSpec, capability: SourceCapability) -> None:
        """能力守卫：未声明能力时立即失败（规划书 §9）。"""
        if not source.supports(capability):
            raise SourceUnsupportedError(
                f"书源 {source.id} 不支持能力 {capability.value}",
                details={"source_id": source.id, "capability": capability.value},
            )

    # ---- 搜索 ----
    async def search(
        self, source: SourceSpec, keyword: str, *, page: int = 1
    ) -> list[SearchResult]:
        """执行搜索。"""
        self._require(source, SourceCapability.SEARCH)
        assert source.search is not None  # 由 _require 保证

        context = TemplateContext({"keyword": keyword, "page": page})
        request = build_request(
            source.search.request, context, default_headers=source.network.headers
        )
        rows = await self._collect_rows(
            source, request, source.search.result, source.search.response.format
        )
        rows = apply_transforms_many(
            rows, [*source.transforms, *source.search.transform], base_url=request.url
        )

        results: list[SearchResult] = []
        for row in rows:
            title = row.get("title")
            url = row.get("url")
            if not title or not url:
                continue  # 列表项缺关键字段则跳过，而非整体失败
            results.append(
                SearchResult(
                    source_id=source.id,
                    title=title,
                    url=url,
                    author=row.get("author"),
                    cover_url=row.get("cover"),
                    intro=row.get("intro"),
                    extra={k: v for k, v in row.items() if k not in _SEARCH_KNOWN},
                )
            )
        return results

    async def _collect_rows(
        self,
        source: SourceSpec,
        request: RenderedRequest,
        result: ResultSpec,
        fmt: str,
    ) -> list[dict[str, str | None]]:
        """抓取列表项；声明了 ``result.paginate`` 时跟着「下一页」链接继续抓。

        循环的三个终止条件：取不到 ``next``（站点表示「没有下一页」的自然方式）、
        下一页地址已经抓过（防止站点把链接永远指向自己）、
        或者到达 ``max_pages`` 上限。

        到达上限会**记一条 WARNING**。不能静默截断 —— 用户会以为整本书下完了。
        """
        rows: list[dict[str, str | None]] = []
        pagination = result.paginate
        visited = {request.url}
        current = request
        page_no = 0

        while True:
            page_no += 1
            document = await self._fetch_document(source, current, fmt)
            rows.extend(extract_many(document, result.list, result.fields))

            if pagination is None:
                break

            if page_no >= pagination.max_pages:
                _logger.warning(
                    "source.pagination_limit_reached",
                    source_id=source.id,
                    max_pages=pagination.max_pages,
                    url=current.url,
                    rows=len(rows),
                )
                break

            next_href = extract_one(document, pagination.next)
            if not next_href:
                break

            next_url = urljoin(current.url, next_href.strip())
            if next_url in visited:
                _logger.warning(
                    "source.pagination_loop_detected",
                    source_id=source.id,
                    url=next_url,
                    page=page_no,
                )
                break
            visited.add(next_url)

            # 下一页地址按站点给的原样用，不再合并首页的 query ——
            # 「下一页」链接本来就是站点对该页的完整表述，再叠一次首页参数
            # 会出现 page=1&page=2 这种重复。所以书源里的 next 必须指向
            # 自包含的完整地址（规范 §5.4 有说明）。
            #
            # 这里必须是 `params=None` 而不是 `params={}`：httpx 遇到空 dict
            # 会先清掉 URL 自带的查询串再赋空参数 —— 等于把 `?page=2` 抹掉，
            # 又抓回第一页。真实站点上踩过，而且离线快照测不出来
            # （假 fetcher 不看 params）。
            current = replace(current, url=next_url, params=None)

        return rows

    # ---- 书籍详情 ----
    async def fetch_book(self, source: SourceSpec, book_url: str) -> BookDraft:
        """抓取书籍详情。"""
        self._require(source, SourceCapability.BOOK)
        assert source.book is not None

        context = TemplateContext({"book.url": book_url})
        request = build_request(
            source.book.request, context, default_headers=source.network.headers
        )
        document = await self._fetch_document(source, request, source.book.response.format)

        fields: dict[str, str | None] = {}
        for name, rule in source.book.fields.items():
            value = extract_one(document, rule)
            fields[name] = apply_transforms(
                value, [*source.transforms, *source.book.transform], base_url=request.url
            )

        title = fields.get("title")
        if not title:
            raise SourceExecutionError(
                "未能提取书籍标题",
                details={"source_id": source.id, "url": book_url},
            )

        return BookDraft(
            source_id=source.id,
            source_book_id=fields.get("id") or _derive_book_id(book_url),
            url=book_url,
            title=title,
            author=fields.get("author"),
            intro=fields.get("intro"),
            cover_url=fields.get("cover"),
            latest_chapter=fields.get("latest_chapter"),
            # 认不出来时返回 UNKNOWN，不会因为状态字段有问题就让整本书登记失败
            status=BookStatus.parse(fields.get("status")),
            extra={k: v for k, v in fields.items() if k not in _BOOK_KNOWN},
        )

    # ---- 章节目录 ----
    async def fetch_chapters(self, source: SourceSpec, book_url: str) -> list[ChapterDraft]:
        """抓取章节目录。"""
        self._require(source, SourceCapability.CHAPTERS)
        assert source.chapters is not None

        context = TemplateContext({"book.url": book_url})
        request = build_request(
            source.chapters.request, context, default_headers=source.network.headers
        )
        rows = await self._collect_rows(
            source, request, source.chapters.result, source.chapters.response.format
        )
        rows = apply_transforms_many(
            rows, [*source.transforms, *source.chapters.transform], base_url=request.url
        )
        if source.chapters.result.reverse:
            rows = list(reversed(rows))

        drafts: list[ChapterDraft] = []
        for idx, row in enumerate(rows):
            title = row.get("title")
            url = row.get("url")
            if not title or not url:
                continue
            drafts.append(
                ChapterDraft(
                    title=title,
                    url=url,
                    index=idx,
                    source_chapter_id=row.get("id"),
                )
            )
        return drafts

    # ---- 正文 ----
    async def fetch_content(
        self, source: SourceSpec, chapter_url: str, *, chapter_index: int | None = None
    ) -> str:
        """抓取并清洗单章正文。"""
        self._require(source, SourceCapability.CONTENT)
        assert source.content is not None

        context = TemplateContext({"chapter.url": chapter_url, "chapter.index": chapter_index or 0})
        request = build_request(
            source.content.request, context, default_headers=source.network.headers
        )
        document = await self._fetch_document(source, request, source.content.response.format)

        # 1) DOM 级清洗：移除噪声节点
        for selector in source.content.clean.remove:
            for node in document.tree.cssselect(selector):
                node.getparent().remove(node)

        # 2) 正文提取
        raw_content = extract_one(document, source.content.body)
        if raw_content is None:
            raise SourceExecutionError(
                "未匹配到正文节点",
                details={"source_id": source.id, "url": chapter_url},
            )

        # 3) 变换
        result = apply_transforms(
            raw_content, [*source.transforms, *source.content.transform], base_url=request.url
        )
        return result or ""

    # ---- 内部 ----
    async def _fetch_document(
        self, source: SourceSpec, request: RenderedRequest, fmt: str
    ) -> Document:
        """发起请求并把响应包装为 :class:`Document`。"""
        response = await self._fetcher.fetch(
            request.method,
            request.url,
            source_id=source.id,
            headers=request.headers,
            params=request.params,
            data=request.data,
            cookies=request.cookies,
            encoding=request.encoding,
            timeout_ms=request.timeout_ms or source.network.timeout_ms,
            # 书源声明能访问哪些域名，运行时就得真的只能访问这些
            allowed_domains=source.permissions.network,
            # 限速也照书源自己声明的来，而不是用全局默认值
            concurrency=source.network.concurrency,
            min_interval=source.network.request_interval_ms / 1000,
            max_retries=source.network.retry,
        )
        return Document(
            raw=response.content,
            encoding=response.encoding or request.encoding or "utf-8",
            kind=fmt,
        )


_SEARCH_KNOWN = frozenset({"title", "url", "author", "cover", "intro"})
_BOOK_KNOWN = frozenset({"id", "title", "author", "intro", "cover", "latest_chapter", "status"})


def _derive_book_id(book_url: str) -> str:
    """从 URL 派生书籍标识（书源未提供 id 字段时的兜底）。"""
    from ..domain.chapter import normalize_url

    return normalize_url(book_url)


__all__ = [
    "BookDraft",
    "ChapterDraft",
    "Fetcher",
    "ResponseLike",
    "SearchResult",
    "SourceEngine",
]
