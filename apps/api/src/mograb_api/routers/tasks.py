# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/tasks`` —— 任务控制（规划书 §29）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from mograb.domain.enums import TaskStatus, TaskType

from ..deps import ApplicationDep

router = APIRouter(prefix="/tasks", tags=["tasks"])

TaskTypeLiteral = Literal["download_book", "update_book", "export_book", "refresh_source"]


class TaskCreate(BaseModel):
    """创建任务请求。

    下载任务有两种给法：给 ``book_id``（书已在库里），
    或者给 ``source_id`` + ``url``（只有一个详情页 URL，先登记成书再下）。
    后者是桌面端从搜索结果直接点下载的路径。
    """

    type: TaskTypeLiteral
    book_id: str | None = None
    source_id: str | None = None
    url: str | None = Field(default=None, description="书籍详情页 URL，配合 source_id 使用")
    priority: int = Field(default=0, ge=0, le=100)
    params: dict[str, Any] = Field(default_factory=dict)


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
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _to_out(task) -> TaskOut:
    return TaskOut(
        id=task.id,
        type=task.type.value,
        status=task.status.value,
        priority=task.priority,
        book_id=task.book_id,
        source_id=task.source_id,
        total=task.total,
        completed=task.completed,
        failed=task.failed,
        progress=round(task.progress, 4),
        error_code=task.error_code,
        error_message=task.error_message,
        params=task.params,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskOut, summary="创建任务")
async def create_task(payload: TaskCreate, application: ApplicationDep) -> TaskOut:
    """创建任务并入队，由 worker 池执行。

    引用的书或书源不存在时返回 404，而不是等到 worker 执行时才失败 ——
    任务已经排进队列了才发现下不了，调用方拿着 201 无从判断。
    """
    params = dict(payload.params)
    if payload.url:
        params["url"] = payload.url

    task = await application.create_task(
        TaskType(payload.type),
        book_id=payload.book_id,
        source_id=payload.source_id,
        priority=payload.priority,
        params=params,
    )
    return _to_out(task)


@router.get("", response_model=list[TaskOut], summary="列出任务")
async def list_tasks(
    application: ApplicationDep,
    status_filter: TaskStatus | None = Query(None, alias="status", description="按状态过滤"),
    limit: int = Query(50, ge=1, le=200),
) -> list[TaskOut]:
    """列出任务，最新的在前。"""
    tasks = await application.tasks.list_all(status=status_filter)
    return [_to_out(t) for t in tasks[:limit]]


@router.get("/{task_id}", response_model=TaskOut, summary="任务详情")
async def get_task(task_id: str, application: ApplicationDep) -> TaskOut:
    """查看任务详情。"""
    return _to_out(await application.task_manager.get(task_id))


@router.post("/{task_id}/pause", response_model=TaskOut, summary="暂停任务")
async def pause_task(task_id: str, application: ApplicationDep) -> TaskOut:
    """暂停任务。"""
    return _to_out(await application.task_manager.pause(task_id))


@router.post("/{task_id}/resume", response_model=TaskOut, summary="继续任务")
async def resume_task(task_id: str, application: ApplicationDep) -> TaskOut:
    """继续任务。"""
    return _to_out(await application.task_manager.resume(task_id))


@router.post("/{task_id}/cancel", response_model=TaskOut, summary="取消任务")
async def cancel_task(task_id: str, application: ApplicationDep) -> TaskOut:
    """取消任务。"""
    return _to_out(await application.task_manager.cancel(task_id))


@router.post("/{task_id}/retry", response_model=TaskOut, summary="重试任务")
async def retry_task(task_id: str, application: ApplicationDep) -> TaskOut:
    """重试失败的任务。

    终态不可逆，所以返回的是**新任务**而不是复活旧的那个。
    """
    return _to_out(await application.task_manager.retry(task_id))
