# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/tasks`` —— 任务控制（规划书 §29）。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/tasks", tags=["tasks"])

TaskTypeLiteral = Literal["download_book", "update_book", "export_book", "refresh_source"]
TaskStatusLiteral = Literal[
    "pending", "running", "paused", "retrying", "success", "failed", "cancelled"
]


class TaskCreate(BaseModel):
    """创建任务请求。"""

    type: TaskTypeLiteral
    book_id: str | None = None
    source_id: str | None = None
    url: str | None = Field(default=None, description="直接以 URL 创建（下载任务）")
    priority: int = Field(default=0, ge=0, le=100)
    concurrency: int | None = Field(default=None, ge=1, le=32)


class TaskOut(BaseModel):
    """任务视图。"""

    id: str
    type: str
    status: str
    priority: int
    book_id: str | None = None
    source_id: str | None = None
    total: int = 0
    completed: int = 0
    failed: int = 0
    progress: float = 0.0
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


@router.post("", status_code=201, response_model=TaskOut, summary="创建任务")
async def create_task(payload: TaskCreate) -> TaskOut:
    """创建下载 / 更新 / 导出任务。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.get("", response_model=list[TaskOut], summary="列出任务")
async def list_tasks(
    status: TaskStatusLiteral | None = Query(None, description="按状态过滤"),
) -> list[TaskOut]:
    """列出任务。"""
    return []


@router.get("/{task_id}", response_model=TaskOut, summary="任务详情")
async def get_task(task_id: str) -> TaskOut:
    """查看任务详情。"""
    raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")


@router.post("/{task_id}/pause", summary="暂停任务")
async def pause_task(task_id: str) -> dict[str, object]:
    """暂停任务。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{task_id}/resume", summary="继续任务")
async def resume_task(task_id: str) -> dict[str, object]:
    """继续任务。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{task_id}/cancel", summary="取消任务")
async def cancel_task(task_id: str) -> dict[str, object]:
    """取消任务。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{task_id}/retry", summary="重试任务")
async def retry_task(task_id: str) -> dict[str, object]:
    """重试失败任务。"""
    raise HTTPException(status_code=501, detail="尚未实现")
