# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/search`` —— 跨书源搜索（规划书 §29）。

规划书没说 ``GET /search`` 是不是跨源。裁决：**默认跨源并发聚合**，
单源失败不影响整体，失败信息放在响应的 ``errors`` 里。

这里还有 ``GET /search/local`` —— 在**已下载**的正文里搜，纯本地。
它和跨书源搜索是两件事，所以分成两个端点而不是一个端点加开关：
前者找「哪本书」，要去站点；后者找「哪一章」，一行网络请求都不发。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from mograb.domain.enums import SourceCapability

from ..deps import ApplicationDep

router = APIRouter(tags=["search"])


class SearchItem(BaseModel):
    """单条搜索结果。"""

    source_id: str
    title: str
    url: str
    author: str | None = None
    cover_url: str | None = None
    intro: str | None = None


class SearchError(BaseModel):
    """某个书源的失败信息。"""

    source_id: str
    code: str
    message: str


class SearchResponse(BaseModel):
    """搜索响应。"""

    keyword: str
    total: int
    items: list[SearchItem] = Field(default_factory=list)
    errors: list[SearchError] = Field(
        default_factory=list,
        description="各书源的失败信息。部分源失败不应导致整体失败",
    )


@router.get("/search", response_model=SearchResponse, summary="搜索小说")
async def search(
    application: ApplicationDep,
    q: str = Query(..., min_length=1, description="搜索关键词"),
    source: list[str] | None = Query(None, description="限定书源 ID（可重复）"),
    limit: int = Query(20, ge=1, le=100, description="每源返回上限"),
) -> SearchResponse:
    """跨书源搜索。"""
    entries = await application.sources.list_enabled()
    if source:
        wanted = set(source)
        entries = [e for e in entries if e.id in wanted]

    searchable = [e for e in entries if e.spec.supports(SourceCapability.SEARCH)]
    if not searchable:
        return SearchResponse(keyword=q, total=0)

    async def one(entry):
        try:
            hits = await application.engine.search(entry.spec, q)
            return entry, hits[:limit], None
        except Exception as exc:
            return entry, [], exc

    gathered = await asyncio.gather(*(one(e) for e in searchable))

    items: list[SearchItem] = []
    errors: list[SearchError] = []
    for entry, hits, error in gathered:
        if error is not None:
            errors.append(
                SearchError(
                    source_id=entry.id,
                    code=getattr(error, "code", type(error).__name__),
                    message=str(error),
                )
            )
            continue
        items.extend(
            SearchItem(
                source_id=hit.source_id,
                title=hit.title,
                url=hit.url,
                author=hit.author,
                cover_url=hit.cover_url,
                intro=hit.intro,
            )
            for hit in hits
        )

    return SearchResponse(keyword=q, total=len(items), items=items, errors=errors)


class LocalHit(BaseModel):
    """本地正文搜索的一条命中。"""

    book_id: str
    book_title: str
    chapter_id: str
    chapter_title: str
    chapter_index: int
    snippet: str = Field(description="命中位置附近的片段，**不是整章正文**")


class LocalSearchResponse(BaseModel):
    """本地搜索响应。"""

    keyword: str
    total: int
    items: list[LocalHit] = Field(default_factory=list)


@router.get(
    "/search/local",
    response_model=LocalSearchResponse,
    summary="在已下载的正文里搜索",
)
async def search_local(
    application: ApplicationDep,
    q: str = Query(..., min_length=1, description="搜索关键词（字面子串，不解析正则）"),
    book_id: str | None = Query(None, description="限定某一本书"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
) -> LocalSearchResponse:
    """在**已下载**的章节正文里搜关键词。**不访问网络。**

    和 ``GET /search`` 的区别：那个去书源上搜书（找「哪本书」），
    这个只查本地库（找「哪一章」）。

    只返回命中处的片段而不是整章正文 —— 一本几千章的书，搜一次就把
    几十兆正文读进内存是不可接受的。
    """
    hits = await application.chapters.search_content(q, book_id=book_id, limit=limit)
    return LocalSearchResponse(
        keyword=q,
        total=len(hits),
        items=[
            LocalHit(
                book_id=hit.book_id,
                book_title=hit.book_title,
                chapter_id=hit.chapter_id,
                chapter_title=hit.chapter_title,
                chapter_index=hit.chapter_index,
                snippet=hit.snippet,
            )
            for hit in hits
        ],
    )
