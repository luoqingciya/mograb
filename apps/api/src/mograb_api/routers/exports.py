# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/exports`` —— 导出（规划书 §29）。

规划书 §26 把导出器定义成同步接口，§29 又给了 ``POST /exports`` +
``GET /exports/{id}`` 的异步作业语义 —— 两处对不上。这里裁决为**异步作业**：
大书生成 EPUB 要几十秒，同步接口会把请求挂到超时。

做法是先建一条 PENDING 记录，把 id 塞进任务参数，再交给 worker 池跑。
调用方拿到 id 就能查状态。
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from mograb.domain.enums import ExportFormat, ExportStatus, TaskType
from mograb.domain.export import ExportRecord
from mograb.domain.ids import new_id
from mograb.errors import EntityNotFoundError

from ..deps import ApplicationDep

router = APIRouter(prefix="/exports", tags=["exports"])


class ExportCreate(BaseModel):
    """创建导出作业。"""

    book_id: str
    format: ExportFormat = ExportFormat.EPUB
    output: str | None = Field(default=None, description="目标文件路径；不传按配置推导")


class ExportOut(BaseModel):
    """导出作业视图。"""

    id: str
    book_id: str
    format: str
    status: str
    path: str | None = None
    size_bytes: int = 0
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None


def _to_out(record: ExportRecord) -> ExportOut:
    return ExportOut(
        id=record.id,
        book_id=record.book_id,
        format=record.format.value,
        status=record.status.value,
        path=record.path,
        size_bytes=record.size_bytes,
        error_message=record.error_message,
        created_at=record.created_at,
        finished_at=record.finished_at,
    )


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ExportOut, summary="创建导出作业"
)
async def create_export(payload: ExportCreate, application: ApplicationDep) -> ExportOut:
    """创建导出作业，立即返回 id，导出在后台跑。"""
    book = await application.books.get(payload.book_id)
    if book is None:
        raise EntityNotFoundError(
            f"书籍不存在: {payload.book_id}", details={"book_id": payload.book_id}
        )

    record = ExportRecord(
        id=new_id("export"),
        book_id=book.id,
        format=payload.format,
        status=ExportStatus.PENDING,
        created_at=datetime.now(UTC),
    )
    await application.exports.save(record)

    await application.create_task(
        TaskType.EXPORT_BOOK,
        book_id=book.id,
        params={
            "export_id": record.id,
            "format": payload.format.value,
            "target": payload.output,
        },
    )
    return _to_out(record)


@router.get("/{export_id}", response_model=ExportOut, summary="导出作业状态")
async def get_export(export_id: str, application: ApplicationDep) -> ExportOut:
    """查询导出作业。完成后 ``path`` 才有值。"""
    record = await application.exports.get(export_id)
    if record is None:
        raise EntityNotFoundError(f"导出作业不存在: {export_id}", details={"export_id": export_id})
    return _to_out(record)


@router.get("", response_model=list[ExportOut], summary="最近的导出作业")
async def list_exports(application: ApplicationDep, limit: int = 50) -> list[ExportOut]:
    """列出最近的导出作业。"""
    return [_to_out(r) for r in await application.exports.list_recent(limit=limit)]
