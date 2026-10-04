# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/search`` —— 跨书源搜索（规划书 §29）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(tags=["search"])


class SearchItem(BaseModel):
    """单条搜索结果。"""

    source_id: str
    title: str
    url: str
    author: str | None = None
    cover_url: str | None = None
    intro: str | None = None


class SearchResponse(BaseModel):
    """搜索响应。"""

    keyword: str
    total: int
    items: list[SearchItem] = Field(default_factory=list)
    errors: list[dict[str, str]] = Field(
        default_factory=list,
        description="各书源的失败信息（部分源失败不应导致整体失败）",
    )


@router.get("/search", response_model=SearchResponse, summary="搜索小说")
async def search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    source: list[str] | None = Query(None, description="限定书源 ID（可重复）"),
    limit: int = Query(20, ge=1, le=100, description="每源返回上限"),
) -> SearchResponse:
    """跨书源聚合搜索。

    设计裁决：默认跨源并发搜索，单源失败以 ``errors`` 返回而不影响整体
    （规划书未明确，见评估报告 P1）。
    """
    raise HTTPException(
        status_code=501, detail="search 待 Source Engine + SourceRepository 接入后实现"
    )
