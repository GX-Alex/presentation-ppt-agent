"""Packages API — P0 阶段的 registry / manifest 校验 / 安装管理接口。"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.models.database import async_session
from app.services.plugin_registry import (
    compare_registry_package_versions,
    get_registry_package,
    import_plugin_source,
    import_plugin_source_spec,
    install_registry_package,
    list_artifact_variants,
    list_execution_logs,
    list_installed_packages,
    list_registry_packages,
    list_registry_package_versions,
    list_workflow_bindings,
    rollback_installed_package,
    toggle_installed_package,
    upgrade_installed_package,
    validate_manifest_payload,
)
from app.services.remote_package_sources import create_github_remote_source, infer_package_id

router = APIRouter(prefix="/packages", tags=["packages"])

DEFAULT_USER_ID = "default-user-00000000"


class PackageInstallRequest(BaseModel):
    package_id: str = Field(..., min_length=3, max_length=127)
    version: str | None = Field(default=None, min_length=5, max_length=30)


class PackageUpgradeRequest(BaseModel):
    target_version: str | None = Field(default=None, min_length=5, max_length=30)


class PackageToggleRequest(BaseModel):
    enabled: bool


class PackageImportRequest(BaseModel):
    source_id: str | None = Field(default=None, min_length=3, max_length=127)
    owner: str | None = Field(default=None, min_length=1, max_length=127)
    repo: str | None = Field(default=None, min_length=1, max_length=127)
    ref: str = Field(default="main", min_length=1, max_length=127)
    plugin_path: str | None = Field(default=None, min_length=1, max_length=255)
    package_id: str | None = Field(default=None, min_length=3, max_length=127)
    package_kind: Literal["workflow", "tool_adapter"] = "workflow"
    related_skill_path: str | None = Field(default=None, min_length=1, max_length=255)
    adapter_targets: list[str] = Field(default_factory=list)


class ManifestValidationRequest(BaseModel):
    manifest: dict


@router.get("/registry")
async def get_registry():
    async with async_session() as session:
        items = await list_registry_packages(session)
        return {"items": items, "total": len(items)}


@router.get("/registry/{package_id}")
async def get_registry_item(package_id: str):
    async with async_session() as session:
        item = await get_registry_package(session, package_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Package 不存在")
        return {"item": item.model_dump()}


@router.get("/registry/{package_id}/versions")
async def get_registry_item_versions(package_id: str):
    async with async_session() as session:
        items = await list_registry_package_versions(session, package_id)
        if not items:
            raise HTTPException(status_code=404, detail="Package 不存在")
        return {
            "package_id": package_id,
            "latest_version": items[0]["version"],
            "versions": items,
        }


@router.post("/validate-manifest")
async def validate_manifest(data: ManifestValidationRequest):
    try:
        manifest = validate_manifest_payload(data.manifest)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"manifest": manifest, "valid": True}


@router.get("/installed")
async def get_installed():
    async with async_session() as session:
        items = await list_installed_packages(session, DEFAULT_USER_ID)
        return {"items": items, "total": len(items)}


@router.post("/import")
async def import_package_source(data: PackageImportRequest):
    async with async_session() as session:
        try:
            if data.source_id:
                result = await import_plugin_source(session, DEFAULT_USER_ID, data.source_id)
            else:
                if not data.owner or not data.repo or not data.plugin_path:
                    raise HTTPException(
                        status_code=400,
                        detail="自定义 GitHub 导入至少需要 owner、repo 和 plugin_path",
                    )
                package_id = data.package_id or infer_package_id(data.owner, data.repo, data.plugin_path)
                spec = create_github_remote_source(
                    owner=data.owner,
                    repo=data.repo,
                    ref=data.ref,
                    plugin_path=data.plugin_path,
                    package_id=package_id,
                    package_kind=data.package_kind,
                    related_skill_path=data.related_skill_path,
                    adapter_targets=tuple(target.strip() for target in data.adapter_targets if target.strip()),
                )
                result = await import_plugin_source_spec(session, DEFAULT_USER_ID, spec)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return result


@router.post("/install")
async def install_package(data: PackageInstallRequest):
    async with async_session() as session:
        try:
            items = await install_registry_package(
                session,
                DEFAULT_USER_ID,
                data.package_id,
                version=data.version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"installed_packages": items, "total": len(items)}


@router.get("/{package_id}/compare")
async def compare_package_versions(
    package_id: str,
    from_version: str,
    to_version: str,
):
    async with async_session() as session:
        try:
            result = await compare_registry_package_versions(session, package_id, from_version, to_version)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return result


@router.post("/{package_id}/upgrade")
async def upgrade_package(package_id: str, data: PackageUpgradeRequest):
    async with async_session() as session:
        try:
            items = await upgrade_installed_package(
                session,
                DEFAULT_USER_ID,
                package_id,
                target_version=data.target_version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated_packages": items, "total": len(items)}


@router.post("/{package_id}/rollback")
async def rollback_package(package_id: str):
    async with async_session() as session:
        try:
            items = await rollback_installed_package(session, DEFAULT_USER_ID, package_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated_packages": items, "total": len(items)}


@router.post("/{package_id}/toggle")
async def toggle_package(package_id: str, data: PackageToggleRequest):
    async with async_session() as session:
        item = await toggle_installed_package(session, DEFAULT_USER_ID, package_id, data.enabled)
        if item is None:
            raise HTTPException(status_code=404, detail="Package 未安装")
        return {"item": item}


@router.get("/workflow-bindings")
async def get_workflow_bindings(
    package_id: str | None = None,
    presentation_id: str | None = None,
    task_id: str | None = None,
):
    async with async_session() as session:
        items = await list_workflow_bindings(
            session,
            DEFAULT_USER_ID,
            package_id=package_id,
            presentation_id=presentation_id,
            task_id=task_id,
        )
        return {"items": items, "total": len(items)}


@router.get("/execution-logs")
async def get_package_execution_logs(
    package_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
):
    async with async_session() as session:
        items = await list_execution_logs(
            session,
            DEFAULT_USER_ID,
            package_id=package_id,
            status=status,
            limit=limit,
        )
        return {"items": items, "total": len(items)}


@router.get("/artifact-variants")
async def get_package_artifact_variants(
    package_id: str | None = None,
    presentation_id: str | None = None,
    asset_id: str | None = None,
):
    async with async_session() as session:
        items = await list_artifact_variants(
            session,
            DEFAULT_USER_ID,
            package_id=package_id,
            presentation_id=presentation_id,
            asset_id=asset_id,
        )
        return {"items": items, "total": len(items)}