# SPDX-License-Identifier: GPL-3.0-only
"""``/api/v1/sources`` —— 书源管理（规划书 §29）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from mograb.domain.enums import HealthStatus
from mograb.errors import SourceNotFoundError, SourceSchemaError
from mograb.source import lint, load_source_dict, load_source_file

from ..deps import ApplicationDep

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceOut(BaseModel):
    """书源视图。"""

    id: str
    name: str
    version: str
    spec_version: int
    homepage: str | None = None
    description: str | None = None
    capabilities: list[str]
    enabled: bool
    health: str
    installed_version: str
    previous_version: str | None = None


class SourceDetail(SourceOut):
    """书源详情，多带权限和文件位置。"""

    permissions: dict[str, Any]
    path: str


class SourceInstallRequest(BaseModel):
    """安装书源。

    规划书 §29 只写了 ``POST /sources``，§13 又描述了 Registry 安装流程，
    没说两者关系。这里裁决为**同一个端点**，用 ``mode`` 区分。
    """

    mode: Literal["yaml", "file"] = "yaml"
    content: str | None = Field(default=None, description="mode=yaml 时的 YAML 文本")
    path: str | None = Field(default=None, description="mode=file 时的本地路径")
    force: bool = Field(default=False, description="即使 lint 有 ERROR 也装")


class SourceInstallResult(BaseModel):
    """安装结果。"""

    id: str
    version: str
    replaced: bool
    path: str
    warnings: list[str] = Field(default_factory=list)


def _to_out(entry: Any) -> SourceOut:
    return SourceOut(
        id=entry.id,
        name=entry.spec.name,
        version=entry.spec.version,
        spec_version=entry.spec.spec_version,
        homepage=entry.spec.homepage,
        description=entry.spec.description,
        capabilities=[c.value for c in entry.spec.capabilities],
        enabled=entry.enabled,
        health=entry.health.value,
        installed_version=entry.installed_version,
        previous_version=entry.previous_version,
    )


def _require(entry: Any, source_id: str) -> Any:
    if entry is None:
        raise SourceNotFoundError(f"书源未安装: {source_id}", details={"source_id": source_id})
    return entry


@router.get("", response_model=list[SourceOut], summary="列出已安装书源")
async def list_sources(application: ApplicationDep) -> list[SourceOut]:
    """列出书源及其能力、版本与健康状态。"""
    return [_to_out(entry) for entry in await application.sources.list_all()]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceInstallResult,
    summary="安装书源",
)
async def create_source(
    payload: SourceInstallRequest, application: ApplicationDep
) -> SourceInstallResult:
    """安装书源。

    装之前先 lint。有 ERROR 且没给 ``force`` 就拒绝 —— 装一个跑不起来的书源，
    问题要等到真下载时才暴露。
    """
    if payload.mode == "file":
        if not payload.path:
            raise SourceSchemaError("mode=file 时必须提供 path")
        spec = load_source_file(Path(payload.path))
    else:
        if not payload.content:
            raise SourceSchemaError("mode=yaml 时必须提供 content")
        try:
            raw = yaml.safe_load(payload.content)
        except yaml.YAMLError as exc:
            raise SourceSchemaError("YAML 解析失败", details={"reason": str(exc)}) from exc
        if not isinstance(raw, dict):
            raise SourceSchemaError("书源根节点必须是映射")
        spec = load_source_dict(raw, origin="<api>")

    report = lint(spec)
    if not report.is_ready and not payload.force:
        raise SourceSchemaError(
            "书源未通过校验",
            details={"errors": [d.format() for d in report.errors]},
        )

    existing = await application.sources.get(spec.id)
    await application.sources.save(spec)

    return SourceInstallResult(
        id=spec.id,
        version=spec.version,
        replaced=existing is not None,
        path=str(application.sources.source_path(spec.id)),
        warnings=[d.message for d in report.warnings],
    )


@router.post("/rescan", response_model=list[SourceOut], summary="重建书源索引")
async def rescan_sources(application: ApplicationDep) -> list[SourceOut]:
    """用磁盘上的定义重建索引。

    手动改过 ``source.yaml``、或把 data 目录拷到另一台机器上时用。
    声明在 ``/{source_id}`` 之前，免得被当成一个叫 rescan 的书源。
    """
    return [_to_out(entry) for entry in await application.sources.rescan()]


@router.get("/{source_id}", response_model=SourceDetail, summary="查看书源详情")
async def get_source(source_id: str, application: ApplicationDep) -> SourceDetail:
    """查看单个书源。"""
    entry = _require(await application.sources.get(source_id), source_id)
    return SourceDetail(
        **_to_out(entry).model_dump(),
        permissions=entry.spec.permissions.model_dump(mode="json"),
        path=str(application.sources.source_path(source_id)),
    )


@router.delete("/{source_id}", summary="卸载书源")
async def delete_source(source_id: str, application: ApplicationDep) -> dict[str, bool]:
    """卸载书源，连同本地定义文件。"""
    removed = await application.sources.delete(source_id)
    if not removed:
        _require(None, source_id)
    return {"removed": removed}


@router.post("/{source_id}/enable", response_model=SourceOut, summary="启用书源")
async def enable_source(source_id: str, application: ApplicationDep) -> SourceOut:
    """启用书源。"""
    await application.sources.set_enabled(source_id, True)
    return _to_out(_require(await application.sources.get(source_id), source_id))


@router.post("/{source_id}/disable", response_model=SourceOut, summary="禁用书源")
async def disable_source(source_id: str, application: ApplicationDep) -> SourceOut:
    """禁用书源（保留定义，只是不再被调度）。"""
    await application.sources.set_enabled(source_id, False)
    return _to_out(_require(await application.sources.get(source_id), source_id))


@router.post("/{source_id}/doctor", response_model=SourceOut, summary="书源体检")
async def doctor_source(
    source_id: str,
    application: ApplicationDep,
    live: bool = False,
) -> SourceOut:
    """体检并把结果写回索引（规划书 §54）。

    默认离线检查；``live=true`` 会额外访问一次主页。
    """
    entry = _require(await application.sources.get(source_id), source_id)

    problems: list[str] = []
    if lint(entry.spec).errors:
        problems.append("lint 未通过")

    if live and entry.spec.homepage:
        try:
            await application.http.fetch(
                "GET",
                entry.spec.homepage,
                source_id=entry.id,
                allowed_domains=entry.spec.permissions.network,
                use_cache=False,
            )
        except Exception:
            problems.append("主页不可达")

    if not problems:
        health = HealthStatus.HEALTHY
    elif any("lint" in p for p in problems):
        health = HealthStatus.BROKEN
    else:
        health = HealthStatus.DEGRADED

    await application.sources.set_health(source_id, health)
    return _to_out(_require(await application.sources.get(source_id), source_id))
