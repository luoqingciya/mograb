# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/sources`` —— 书源管理（规划书 §29）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", summary="列出已安装书源")
async def list_sources() -> list[dict[str, object]]:
    """列出书源及其能力、版本与健康状态。"""
    # TODO(storage): 接入 SourceRepository
    return []


@router.post("", status_code=status.HTTP_201_CREATED, summary="安装书源")
async def create_source(payload: dict[str, object]) -> dict[str, object]:
    """安装书源（YAML 内容或 Registry ID）。

    Note:
        规划书 §29 列出 ``POST /sources``，但 §13 的 Registry 安装流程
        是否复用该端点未说明；此处裁决为**复用**，Registry 安装作为
        ``payload.mode = "registry"`` 的一种形式。
    """
    raise HTTPException(status_code=501, detail="尚未实现")


@router.get("/{source_id}", summary="查看书源详情")
async def get_source(source_id: str) -> dict[str, object]:
    """查看单个书源。"""
    raise HTTPException(status_code=404, detail=f"书源不存在: {source_id}")


@router.delete("/{source_id}", summary="卸载书源")
async def delete_source(source_id: str) -> dict[str, object]:
    """卸载书源。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{source_id}/enable", summary="启用书源")
async def enable_source(source_id: str) -> dict[str, object]:
    """启用书源。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{source_id}/disable", summary="禁用书源")
async def disable_source(source_id: str) -> dict[str, object]:
    """禁用书源。"""
    raise HTTPException(status_code=501, detail="尚未实现")


@router.post("/{source_id}/doctor", summary="书源健康检查")
async def doctor_source(source_id: str) -> dict[str, object]:
    """执行健康检查（规划书 §54）。"""
    raise HTTPException(status_code=501, detail="尚未实现")
