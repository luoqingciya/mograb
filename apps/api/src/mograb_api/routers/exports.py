# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/exports`` —— 导出（规划书 §29）。

Note:
    规划书 §26 把导出接口定义为同步 ``async def export(book, target)``，
    但 §29 又给出 ``POST /exports`` + ``GET /exports/{id}`` 的异步作业语义。
    此处裁决为**异步作业**：导出可能耗时（EPUB 生成、大书），
    且与 Task Engine 复用同一套状态机更一致。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/exports", tags=["exports"])


class ExportCreate(BaseModel):
    """创建导出请求。"""

    book_id: str
    format: str = Field(default="epub", description="txt / markdown / epub")
    output_dir: str | None = None
    template: str | None = None


class ExportOut(BaseModel):
    """导出作业视图。"""

    id: str
    book_id: str
    format: str
    status: str
    path: str | None = None
    size_bytes: int = 0
    error_message: str | None = None


@router.post("", status_code=201, response_model=ExportOut, summary="创建导出作业")
async def create_export(payload: ExportCreate) -> ExportOut:
    """创建导出作业。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.get("/{export_id}", response_model=ExportOut, summary="导出作业状态")
async def get_export(export_id: str) -> ExportOut:
    """查询导出作业。"""
    raise HTTPException(status_code=404, detail=f"导出作业不存在: {export_id}")
