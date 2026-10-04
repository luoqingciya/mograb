# SPDX-License-Identifier: GPL-3.0-only
"""导出记录（规划书 §26、§29）。

导出是**异步作业**：`POST /exports` 立刻返回一个 id，之后用 `GET /exports/{id}`
查状态。所以这条记录要能表达「排队中 → 进行中 → 完成/失败」的全过程，
而不只是一条历史流水。

`path` 在作业完成前是 None —— 这也是当初把导出裁决成异步的原因之一：
同步接口在创建时还拿不到产物路径。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import ExportFormat, ExportStatus


class ExportRecord(BaseModel):
    """一次导出作业。"""

    model_config = ConfigDict(extra="forbid")

    id: str
    book_id: str
    format: ExportFormat
    status: ExportStatus = ExportStatus.PENDING

    path: str | None = Field(default=None, description="产物路径，完成前为 None")
    size_bytes: int = 0

    error_message: str | None = None

    created_at: datetime
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        """是否已结束（成功或失败）。"""
        return self.status in (ExportStatus.SUCCESS, ExportStatus.FAILED)


__all__ = ["ExportRecord"]
