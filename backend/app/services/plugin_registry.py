"""数据库驱动的 P2 Plugin Registry。"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import (
    ArtifactVariant,
    ExecutionLog,
    InstalledPlugin,
    PluginPackage,
    PluginVersion,
    UserSkill,
    WorkflowBinding,
)
from app.schemas.package_manifest import PluginPackageManifest
from app.services.package_registry import (
    _BUILTIN_MANIFESTS,
    _compare_versions,
    _parse_semver,
    _version_satisfies,
)
from app.services.remote_package_sources import (
    GitHubRemoteSource,
    RemotePackageImportError,
    fetch_remote_package_bundle,
    fetch_remote_package_bundle_from_spec,
)


async def ensure_plugin_registry_seeded(session: AsyncSession) -> None:
    for manifest_data in _BUILTIN_MANIFESTS:
        await _upsert_registry_manifest(session, manifest_data, source="builtin", source_ref="builtin")
    await session.commit()


async def list_registry_packages(session: AsyncSession) -> list[dict[str, Any]]:
    await ensure_plugin_registry_seeded(session)
    result = await session.execute(select(PluginPackage).order_by(PluginPackage.package_id))
    packages = result.scalars().all()
    items: list[dict[str, Any]] = []
    for package in packages:
        version_row = await _get_plugin_version_row(session, package.package_id, package.latest_version)
        if version_row is None:
            continue
        items.append(_manifest_from_row(version_row).model_dump())
    return items


async def list_registry_package_versions(session: AsyncSession, package_id: str) -> list[dict[str, Any]]:
    await ensure_plugin_registry_seeded(session)
    version_rows = await _get_package_versions(session, package_id)
    if not version_rows:
        return []

    latest_version = version_rows[-1].version
    return [
        {
            "version": manifest.version,
            "display_name": manifest.display_name,
            "description": manifest.description,
            "release_notes": manifest.metadata.get("release_notes", ""),
            "release_date": manifest.metadata.get("release_date"),
            "is_latest": manifest.version == latest_version,
            "capability_count": len(manifest.capabilities),
            "permission_count": len(manifest.permissions),
            "dependency_count": len(manifest.dependencies),
        }
        for manifest in (_manifest_from_row(row) for row in reversed(version_rows))
    ]


async def get_registry_package(
    session: AsyncSession,
    package_id: str,
    version: str | None = None,
) -> PluginPackageManifest | None:
    await ensure_plugin_registry_seeded(session)
    row = await _get_plugin_version_row(session, package_id, version)
    return _manifest_from_row(row) if row is not None else None


def validate_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = PluginPackageManifest.model_validate(payload)
    return manifest.model_dump()


async def compare_registry_package_versions(
    session: AsyncSession,
    package_id: str,
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    from_manifest = await get_registry_package(session, package_id, from_version)
    to_manifest = await get_registry_package(session, package_id, to_version)
    if from_manifest is None or to_manifest is None:
        raise ValueError("指定版本不存在")

    from_permissions = {item.name: item.rationale for item in from_manifest.permissions}
    to_permissions = {item.name: item.rationale for item in to_manifest.permissions}
    from_dependencies = {item.package_id: item.version_constraint for item in from_manifest.dependencies}
    to_dependencies = {item.package_id: item.version_constraint for item in to_manifest.dependencies}
    version_cmp = _compare_versions(from_version, to_version)

    return {
        "package_id": package_id,
        "from_version": from_version,
        "to_version": to_version,
        "direction": "upgrade" if version_cmp < 0 else "rollback" if version_cmp > 0 else "same",
        "from_manifest": from_manifest.model_dump(),
        "to_manifest": to_manifest.model_dump(),
        "added_capabilities": sorted(set(to_manifest.capabilities) - set(from_manifest.capabilities)),
        "removed_capabilities": sorted(set(from_manifest.capabilities) - set(to_manifest.capabilities)),
        "added_permissions": [
            {"name": name, "rationale": to_permissions[name]}
            for name in sorted(set(to_permissions) - set(from_permissions))
        ],
        "removed_permissions": [
            {"name": name, "rationale": from_permissions[name]}
            for name in sorted(set(from_permissions) - set(to_permissions))
        ],
        "added_dependencies": [
            {"package_id": package_key, "version_constraint": to_dependencies[package_key]}
            for package_key in sorted(set(to_dependencies) - set(from_dependencies))
        ],
        "removed_dependencies": [
            {"package_id": package_key, "version_constraint": from_dependencies[package_key]}
            for package_key in sorted(set(from_dependencies) - set(to_dependencies))
        ],
        "release_notes": to_manifest.metadata.get("release_notes", ""),
        "upgrade_notes": to_manifest.metadata.get("upgrade_notes", ""),
    }


async def import_plugin_source(
    session: AsyncSession,
    user_id: str,
    source_id: str,
) -> dict[str, Any]:
    await ensure_plugin_registry_seeded(session)
    try:
        remote_bundle = await fetch_remote_package_bundle(source_id)
    except ValueError:
        raise
    except RemotePackageImportError as exc:
        raise RuntimeError(str(exc)) from exc

    return await _import_remote_package_bundle(session, user_id, source_id, remote_bundle)


async def import_plugin_source_spec(
    session: AsyncSession,
    user_id: str,
    spec: GitHubRemoteSource,
) -> dict[str, Any]:
    await ensure_plugin_registry_seeded(session)
    try:
        remote_bundle = await fetch_remote_package_bundle_from_spec(spec)
    except RemotePackageImportError as exc:
        raise RuntimeError(str(exc)) from exc

    return await _import_remote_package_bundle(session, user_id, spec.source_id, remote_bundle)


async def _import_remote_package_bundle(
    session: AsyncSession,
    user_id: str,
    source_token: str,
    remote_bundle: Any,
) -> dict[str, Any]:

    resolved_version = await _resolve_import_version(
        session,
        remote_bundle.package_id,
        remote_bundle.upstream_version,
        remote_bundle.integrity_hash,
    )
    manifest_data = dict(remote_bundle.manifest)
    metadata = dict(manifest_data.get("metadata") or {})
    metadata["upstream_version"] = remote_bundle.upstream_version
    metadata["source_commit"] = remote_bundle.commit_sha[:12] if remote_bundle.commit_sha else metadata.get("source_commit")
    if resolved_version != remote_bundle.upstream_version:
        metadata["local_version"] = resolved_version
        metadata["release_notes"] = (
            f"{metadata.get('release_notes', '')} Local snapshot version {resolved_version} was created "
            "because the upstream content changed without a semver bump."
        ).strip()
    manifest_data["version"] = resolved_version
    manifest_data["metadata"] = metadata

    row = await _upsert_registry_manifest(
        session,
        manifest_data,
        source="imported",
        source_ref=remote_bundle.source_ref,
        resource_manifest=remote_bundle.resource_manifest,
        is_imported=True,
        integrity_hash=remote_bundle.integrity_hash,
    )

    package_id = row.package_id
    versions = [row.version]
    await record_execution_log(
        session,
        user_id=user_id,
        package_id=package_id,
        package_version=row.version,
        execution_kind="import",
        target_type="package",
        target_id=source_token,
        input_payload={"source_id": source_token, "source_ref": remote_bundle.source_ref},
        output_payload={
            "versions": sorted(versions, key=_parse_semver),
            "upstream_version": remote_bundle.upstream_version,
            "source_commit": remote_bundle.commit_sha[:12] if remote_bundle.commit_sha else None,
        },
    )
    await session.commit()

    latest_manifest = await get_registry_package(session, package_id)
    return {
        "source_id": source_token,
        "source_ref": remote_bundle.source_ref,
        "package_ids": [package_id],
        "versions": sorted(versions, key=_parse_semver),
        "latest_manifest": latest_manifest.model_dump() if latest_manifest else None,
    }


async def resolve_registry_dependencies(
    session: AsyncSession,
    package_id: str,
    version: str | None = None,
) -> list[PluginVersion]:
    await ensure_plugin_registry_seeded(session)
    resolved: list[PluginVersion] = []
    visiting: set[str] = set()
    selected_versions: dict[str, str] = {}

    async def dfs(
        current_id: str,
        requested_version: str | None = None,
        constraint: str | None = None,
    ) -> None:
        selected_version = selected_versions.get(current_id)
        if selected_version is not None:
            if requested_version and selected_version != requested_version:
                raise ValueError(f"Package 版本冲突: {current_id} -> {selected_version} / {requested_version}")
            if constraint and not _version_satisfies(selected_version, constraint):
                raise ValueError(f"Package 版本不满足约束: {current_id} {constraint}")
            return

        if current_id in visiting:
            raise ValueError(f"检测到循环依赖: {current_id}")

        if requested_version is not None:
            row = await _get_plugin_version_row(session, current_id, requested_version)
        elif constraint is not None:
            row = await _select_version_row_for_constraint(session, current_id, constraint)
        else:
            row = await _get_plugin_version_row(session, current_id)

        if row is None:
            raise ValueError(f"未找到 package: {current_id}")

        visiting.add(current_id)
        manifest = _manifest_from_row(row)
        for dependency in manifest.dependencies:
            if dependency.optional:
                continue
            await dfs(dependency.package_id, constraint=dependency.version_constraint)
        visiting.remove(current_id)

        selected_versions[current_id] = row.version
        resolved.append(row)

    await dfs(package_id, requested_version=version)
    return resolved


async def list_installed_packages(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    await ensure_plugin_registry_seeded(session)
    result = await session.execute(
        select(InstalledPlugin)
        .where(InstalledPlugin.user_id == user_id)
        .order_by(InstalledPlugin.package_id)
    )
    rows = result.scalars().all()
    return [await _installed_plugin_to_dict(session, row) for row in rows]


async def install_registry_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    version: str | None = None,
    *,
    action: str = "install",
) -> list[dict[str, Any]]:
    version_rows = await resolve_registry_dependencies(session, package_id, version)
    installed_rows: list[InstalledPlugin] = []

    for version_row in version_rows:
        manifest = _manifest_from_row(version_row)
        package_row = await _get_plugin_package_row(session, manifest.package_id)
        existing = await get_installed_plugin_row(session, user_id, manifest.package_id)
        history = _build_installed_history(existing, manifest.version, action)
        status = _status_for_action(action, existing is None or existing.version != manifest.version)

        if existing is None:
            installed = InstalledPlugin(
                user_id=user_id,
                plugin_package_id=package_row.id,
                active_version_id=version_row.id,
                package_id=manifest.package_id,
                display_name=manifest.display_name,
                package_kind=manifest.kind,
                version=manifest.version,
                source=package_row.source,
                manifest_snapshot=manifest.model_dump(),
                granted_permissions=[permission.model_dump() for permission in manifest.permissions],
                installed_history=history,
                status=status,
                is_enabled=True,
                metadata_={},
            )
            session.add(installed)
            await session.flush()
        else:
            installed = existing
            installed.plugin_package_id = package_row.id
            installed.active_version_id = version_row.id
            installed.package_id = manifest.package_id
            installed.display_name = manifest.display_name
            installed.package_kind = manifest.kind
            installed.version = manifest.version
            installed.source = package_row.source
            installed.manifest_snapshot = manifest.model_dump()
            installed.granted_permissions = [permission.model_dump() for permission in manifest.permissions]
            installed.installed_history = history
            installed.status = status
            installed.is_enabled = True
            installed.updated_at = datetime.utcnow()

        await _sync_skill_resources(session, user_id, installed, version_row, enabled=True)
        await record_execution_log(
            session,
            user_id=user_id,
            package_id=manifest.package_id,
            package_version=manifest.version,
            installed_plugin_id=installed.id,
            plugin_version_id=version_row.id,
            execution_kind=action,
            target_type="package",
            target_id=manifest.package_id,
            input_payload={"requested_version": version, "action": action},
            output_payload={"installed_version": manifest.version},
        )
        installed_rows.append(installed)

    await session.commit()
    return [await _installed_plugin_to_dict(session, row) for row in installed_rows]


async def upgrade_installed_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    target_version: str | None = None,
) -> list[dict[str, Any]]:
    package = await get_installed_plugin_row(session, user_id, package_id)
    if package is None:
        raise LookupError("Package 未安装")

    manifest = await get_registry_package(session, package_id, target_version)
    if manifest is None:
        raise ValueError("目标版本不存在")
    if _compare_versions(package.version, manifest.version) >= 0:
        raise ValueError("当前已是最新版本")

    return await install_registry_package(
        session,
        user_id,
        package_id,
        version=manifest.version,
        action="upgrade",
    )


async def rollback_installed_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
) -> list[dict[str, Any]]:
    package = await get_installed_plugin_row(session, user_id, package_id)
    if package is None:
        raise LookupError("Package 未安装")

    history = _installed_history_entries(package)
    if len(history) < 2:
        raise ValueError("没有可回滚的历史版本")

    target_version = history[-2]["version"]
    return await install_registry_package(
        session,
        user_id,
        package_id,
        version=target_version,
        action="rollback",
    )


async def toggle_installed_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    enabled: bool,
) -> dict[str, Any] | None:
    package = await get_installed_plugin_row(session, user_id, package_id)
    if package is None:
        return None

    package.is_enabled = enabled
    package.status = "installed" if enabled else "disabled"
    package.updated_at = datetime.utcnow()
    await _toggle_materialized_skills(session, package, enabled)
    await record_execution_log(
        session,
        user_id=user_id,
        package_id=package.package_id,
        package_version=package.version,
        installed_plugin_id=package.id,
        plugin_version_id=package.active_version_id,
        execution_kind="toggle",
        target_type="package",
        target_id=package.package_id,
        input_payload={"enabled": enabled},
        output_payload={"status": package.status},
    )
    await session.commit()
    await session.refresh(package)
    return await _installed_plugin_to_dict(session, package)


async def get_installed_plugin_row(
    session: AsyncSession,
    user_id: str,
    package_id: str,
) -> InstalledPlugin | None:
    result = await session.execute(
        select(InstalledPlugin)
        .where(InstalledPlugin.user_id == user_id)
        .where(InstalledPlugin.package_id == package_id)
    )
    return result.scalar_one_or_none()


async def upsert_workflow_binding(
    session: AsyncSession,
    user_id: str,
    installed_plugin: InstalledPlugin,
    *,
    binding_type: str = "presentation",
    task_id: str | None = None,
    presentation_id: str | None = None,
    asset_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> WorkflowBinding:
    target_token = presentation_id or task_id or asset_id or "default"
    binding_key = f"{installed_plugin.package_id}:{binding_type}:{target_token}"
    result = await session.execute(
        select(WorkflowBinding)
        .where(WorkflowBinding.user_id == user_id)
        .where(WorkflowBinding.binding_key == binding_key)
    )
    binding = result.scalar_one_or_none()

    if binding is None:
        binding = WorkflowBinding(
            user_id=user_id,
            installed_plugin_id=installed_plugin.id,
            package_id=installed_plugin.package_id,
            binding_key=binding_key,
            binding_type=binding_type,
            task_id=task_id,
            presentation_id=presentation_id,
            asset_id=asset_id,
            config=config or {},
            is_enabled=True,
            last_used_at=datetime.utcnow(),
        )
        session.add(binding)
    else:
        binding.installed_plugin_id = installed_plugin.id
        binding.package_id = installed_plugin.package_id
        binding.task_id = task_id
        binding.presentation_id = presentation_id
        binding.asset_id = asset_id
        binding.config = config or binding.config or {}
        binding.is_enabled = True
        binding.last_used_at = datetime.utcnow()
        binding.updated_at = datetime.utcnow()

    await session.flush()
    return binding


async def list_workflow_bindings(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str | None = None,
    presentation_id: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    query = select(WorkflowBinding).where(WorkflowBinding.user_id == user_id)
    if package_id:
        query = query.where(WorkflowBinding.package_id == package_id)
    if presentation_id:
        query = query.where(WorkflowBinding.presentation_id == presentation_id)
    if task_id:
        query = query.where(WorkflowBinding.task_id == task_id)
    query = query.order_by(WorkflowBinding.updated_at.desc())

    result = await session.execute(query)
    bindings = result.scalars().all()
    return [
        {
            "id": binding.id,
            "package_id": binding.package_id,
            "binding_key": binding.binding_key,
            "binding_type": binding.binding_type,
            "task_id": binding.task_id,
            "presentation_id": binding.presentation_id,
            "asset_id": binding.asset_id,
            "config": binding.config or {},
            "is_enabled": binding.is_enabled,
            "last_used_at": binding.last_used_at.isoformat() if binding.last_used_at else None,
            "created_at": binding.created_at.isoformat() if binding.created_at else None,
            "updated_at": binding.updated_at.isoformat() if binding.updated_at else None,
        }
        for binding in bindings
    ]


async def record_artifact_variant(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str,
    package_version: str | None,
    variant_type: str,
    file_url: str | None,
    presentation_id: str | None = None,
    asset_id: str | None = None,
    installed_plugin_id: str | None = None,
    execution_log_id: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactVariant:
    target_token = presentation_id or asset_id or "global"
    variant_key = f"{package_id}:{package_version or 'latest'}:{variant_type}:{target_token}"
    result = await session.execute(
        select(ArtifactVariant)
        .where(ArtifactVariant.user_id == user_id)
        .where(ArtifactVariant.variant_key == variant_key)
    )
    variant = result.scalar_one_or_none()

    if variant is None:
        variant = ArtifactVariant(
            user_id=user_id,
            variant_key=variant_key,
            asset_id=asset_id,
            presentation_id=presentation_id,
            installed_plugin_id=installed_plugin_id,
            execution_log_id=execution_log_id,
            package_id=package_id,
            package_version=package_version,
            variant_type=variant_type,
            mime_type=mime_type,
            file_url=file_url,
            metadata_=metadata or {},
        )
        session.add(variant)
    else:
        variant.asset_id = asset_id
        variant.presentation_id = presentation_id
        variant.installed_plugin_id = installed_plugin_id
        variant.execution_log_id = execution_log_id
        variant.package_version = package_version
        variant.mime_type = mime_type
        variant.file_url = file_url
        variant.metadata_ = metadata or variant.metadata_ or {}
        variant.updated_at = datetime.utcnow()

    await session.flush()
    return variant


async def list_artifact_variants(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str | None = None,
    presentation_id: str | None = None,
    asset_id: str | None = None,
) -> list[dict[str, Any]]:
    query = select(ArtifactVariant).where(ArtifactVariant.user_id == user_id)
    if package_id:
        query = query.where(ArtifactVariant.package_id == package_id)
    if presentation_id:
        query = query.where(ArtifactVariant.presentation_id == presentation_id)
    if asset_id:
        query = query.where(ArtifactVariant.asset_id == asset_id)
    query = query.order_by(ArtifactVariant.updated_at.desc())

    result = await session.execute(query)
    variants = result.scalars().all()
    return [
        {
            "id": variant.id,
            "variant_key": variant.variant_key,
            "package_id": variant.package_id,
            "package_version": variant.package_version,
            "variant_type": variant.variant_type,
            "presentation_id": variant.presentation_id,
            "asset_id": variant.asset_id,
            "file_url": variant.file_url,
            "mime_type": variant.mime_type,
            "metadata": variant.metadata_ or {},
            "created_at": variant.created_at.isoformat() if variant.created_at else None,
            "updated_at": variant.updated_at.isoformat() if variant.updated_at else None,
        }
        for variant in variants
    ]


async def record_execution_log(
    session: AsyncSession,
    *,
    user_id: str,
    package_id: str,
    execution_kind: str,
    status: str = "succeeded",
    package_version: str | None = None,
    installed_plugin_id: str | None = None,
    plugin_version_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
    output_payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    duration_ms: int | None = None,
) -> ExecutionLog:
    started_at = datetime.utcnow()
    log = ExecutionLog(
        user_id=user_id,
        installed_plugin_id=installed_plugin_id,
        plugin_version_id=plugin_version_id,
        package_id=package_id,
        package_version=package_version,
        execution_kind=execution_kind,
        target_type=target_type,
        target_id=target_id,
        status=status,
        input_payload=input_payload,
        output_payload=output_payload,
        error_message=error_message,
        duration_ms=duration_ms,
        started_at=started_at,
        completed_at=datetime.utcnow() if status != "running" else None,
    )
    session.add(log)
    await session.flush()
    return log


async def list_execution_logs(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = select(ExecutionLog).where(ExecutionLog.user_id == user_id)
    if package_id:
        query = query.where(ExecutionLog.package_id == package_id)
    if status:
        query = query.where(ExecutionLog.status == status)
    query = query.order_by(ExecutionLog.started_at.desc()).limit(limit)

    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "package_id": log.package_id,
            "package_version": log.package_version,
            "execution_kind": log.execution_kind,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "status": log.status,
            "duration_ms": log.duration_ms,
            "error_message": log.error_message,
            "input_payload": log.input_payload,
            "output_payload": log.output_payload,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "completed_at": log.completed_at.isoformat() if log.completed_at else None,
        }
        for log in logs
    ]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _status_for_action(action: str, version_changed: bool) -> str:
    if action == "rollback":
        return "rolled_back"
    if action == "upgrade" and version_changed:
        return "upgraded"
    return "installed"


async def _select_version_row_for_constraint(
    session: AsyncSession,
    package_id: str,
    constraint: str,
) -> PluginVersion | None:
    version_rows = await _get_package_versions(session, package_id)
    for row in reversed(version_rows):
        if _version_satisfies(row.version, constraint):
            return row
    return None


def _installed_history_entries(package: InstalledPlugin | None) -> list[dict[str, Any]]:
    if package is None or not isinstance(package.installed_history, list):
        return []

    history: list[dict[str, Any]] = []
    for item in package.installed_history:
        if not isinstance(item, dict) or not isinstance(item.get("version"), str):
            continue
        history.append(
            {
                "version": item["version"],
                "changed_at": item.get("changed_at") or _utcnow_iso(),
                "action": item.get("action") or "install",
            }
        )
    return history


def _build_installed_history(
    existing: InstalledPlugin | None,
    version: str,
    action: str,
) -> list[dict[str, Any]]:
    history = _installed_history_entries(existing)
    if history and history[-1]["version"] == version:
        history[-1] = {
            "version": version,
            "changed_at": _utcnow_iso(),
            "action": action,
        }
    else:
        history.append(
            {
                "version": version,
                "changed_at": _utcnow_iso(),
                "action": action,
            }
        )
    return history[-10:]


async def _upsert_registry_manifest(
    session: AsyncSession,
    manifest_data: dict[str, Any],
    *,
    source: str,
    source_ref: str | None,
    resource_manifest: dict[str, Any] | None = None,
    is_imported: bool = False,
    integrity_hash: str | None = None,
) -> PluginVersion:
    manifest = PluginPackageManifest.model_validate(manifest_data)
    package_row = await _get_plugin_package_row(session, manifest.package_id)
    if package_row is None:
        package_row = PluginPackage(
            package_id=manifest.package_id,
            display_name=manifest.display_name,
            package_kind=manifest.kind,
            description=manifest.description,
            publisher=manifest.publisher,
            tags=list(manifest.tags),
            source=source,
            source_ref=source_ref,
            latest_version=manifest.version,
            is_public=True,
            metadata_=manifest.metadata,
        )
        session.add(package_row)
        await session.flush()
    else:
        package_row.display_name = manifest.display_name
        package_row.package_kind = manifest.kind
        package_row.description = manifest.description
        package_row.publisher = manifest.publisher
        package_row.tags = list(manifest.tags)
        package_row.source = source
        package_row.source_ref = source_ref
        package_row.metadata_ = manifest.metadata
        if package_row.latest_version is None or _compare_versions(package_row.latest_version, manifest.version) < 0:
            package_row.latest_version = manifest.version
        package_row.updated_at = datetime.utcnow()

    result = await session.execute(
        select(PluginVersion)
        .where(PluginVersion.package_id == manifest.package_id)
        .where(PluginVersion.version == manifest.version)
    )
    version_row = result.scalar_one_or_none()
    if version_row is None:
        version_row = PluginVersion(
            plugin_package_id=package_row.id,
            package_id=manifest.package_id,
            version=manifest.version,
            manifest=manifest.model_dump(),
            capabilities=list(manifest.capabilities),
            permissions=[permission.model_dump() for permission in manifest.permissions],
            dependencies=[dependency.model_dump() for dependency in manifest.dependencies],
            entrypoints=[entrypoint.model_dump() for entrypoint in manifest.entrypoints],
            resource_manifest=resource_manifest or {},
            release_notes=manifest.metadata.get("release_notes"),
            upgrade_notes=manifest.metadata.get("upgrade_notes"),
            integrity_hash=integrity_hash or hashlib.sha256(f"{manifest.package_id}@{manifest.version}".encode("utf-8")).hexdigest(),
            is_imported=is_imported,
        )
        session.add(version_row)
    else:
        version_row.plugin_package_id = package_row.id
        version_row.manifest = manifest.model_dump()
        version_row.capabilities = list(manifest.capabilities)
        version_row.permissions = [permission.model_dump() for permission in manifest.permissions]
        version_row.dependencies = [dependency.model_dump() for dependency in manifest.dependencies]
        version_row.entrypoints = [entrypoint.model_dump() for entrypoint in manifest.entrypoints]
        version_row.resource_manifest = resource_manifest or version_row.resource_manifest or {}
        version_row.release_notes = manifest.metadata.get("release_notes")
        version_row.upgrade_notes = manifest.metadata.get("upgrade_notes")
        version_row.integrity_hash = integrity_hash or version_row.integrity_hash
        version_row.is_imported = is_imported
        version_row.updated_at = datetime.utcnow()

    await session.flush()
    return version_row


async def _resolve_import_version(
    session: AsyncSession,
    package_id: str,
    upstream_version: str,
    integrity_hash: str,
) -> str:
    existing_versions = await _get_package_versions(session, package_id)
    for row in existing_versions:
        if row.version == upstream_version:
            if row.integrity_hash == integrity_hash:
                return upstream_version
            major, minor, patch = _parse_semver(upstream_version)
            next_patch = patch + 1
            while True:
                candidate = f"{major}.{minor}.{next_patch}"
                duplicate = next((item for item in existing_versions if item.version == candidate), None)
                if duplicate is None:
                    return candidate
                if duplicate.integrity_hash == integrity_hash:
                    return candidate
                next_patch += 1
    return upstream_version


async def _get_plugin_package_row(session: AsyncSession, package_id: str) -> PluginPackage | None:
    result = await session.execute(
        select(PluginPackage).where(PluginPackage.package_id == package_id)
    )
    return result.scalar_one_or_none()


async def _get_package_versions(session: AsyncSession, package_id: str) -> list[PluginVersion]:
    result = await session.execute(
        select(PluginVersion).where(PluginVersion.package_id == package_id)
    )
    rows = result.scalars().all()
    return sorted(rows, key=lambda item: _parse_semver(item.version))


async def _get_plugin_version_row(
    session: AsyncSession,
    package_id: str,
    version: str | None = None,
) -> PluginVersion | None:
    if version is not None:
        result = await session.execute(
            select(PluginVersion)
            .where(PluginVersion.package_id == package_id)
            .where(PluginVersion.version == version)
        )
        return result.scalar_one_or_none()

    package_row = await _get_plugin_package_row(session, package_id)
    if package_row and package_row.latest_version:
        result = await session.execute(
            select(PluginVersion)
            .where(PluginVersion.package_id == package_id)
            .where(PluginVersion.version == package_row.latest_version)
        )
        latest = result.scalar_one_or_none()
        if latest is not None:
            return latest

    version_rows = await _get_package_versions(session, package_id)
    return version_rows[-1] if version_rows else None


def _manifest_from_row(version_row: PluginVersion) -> PluginPackageManifest:
    return PluginPackageManifest.model_validate(version_row.manifest)


def _skill_name(package_id: str, skill_id: str) -> str:
    base = re.sub(r"[^a-z0-9_]+", "_", f"{package_id}_{skill_id}".lower()).strip("_")
    if len(base) <= 63:
        return base
    suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"{base[:52]}_{suffix}"


async def _sync_skill_resources(
    session: AsyncSession,
    user_id: str,
    installed: InstalledPlugin,
    version_row: PluginVersion,
    *,
    enabled: bool,
) -> None:
    resources = version_row.resource_manifest or {}
    skills = resources.get("skills") if isinstance(resources, dict) else []
    if not isinstance(skills, list):
        skills = []

    skill_names: list[str] = []
    for skill_spec in skills:
        if not isinstance(skill_spec, dict):
            continue

        skill_id = str(skill_spec.get("skill_id") or skill_spec.get("display_name") or "skill")
        skill_name = _skill_name(installed.package_id, skill_id)
        skill_names.append(skill_name)

        result = await session.execute(
            select(UserSkill)
            .where(UserSkill.user_id == user_id)
            .where(UserSkill.name == skill_name)
        )
        skill = result.scalar_one_or_none()
        payload = {
            "display_name": skill_spec.get("display_name") or skill_name,
            "description": skill_spec.get("description") or installed.display_name,
            "tags": ",".join(skill_spec.get("tags") or []),
            "body": skill_spec.get("body") or "# Plugin Skill\nImported from plugin package.",
            "required_tools": ",".join(skill_spec.get("required_tools") or []),
            "status": "validated",
            "is_enabled": enabled,
            "is_public": False,
            "scope": "auto",
            "validation_result": {
                "source": "plugin_package",
                "package_id": installed.package_id,
                "package_version": installed.version,
                "skill_id": skill_id,
            },
            "validated_at": datetime.utcnow(),
            "source_skill_id": skill_id,
            "updated_at": datetime.utcnow(),
        }

        if skill is None:
            skill = UserSkill(
                user_id=user_id,
                name=skill_name,
                created_at=datetime.utcnow(),
                **payload,
            )
            session.add(skill)
        else:
            for key, value in payload.items():
                setattr(skill, key, value)

    existing_names = set((installed.metadata_ or {}).get("skill_names") or [])
    for skill_name in existing_names - set(skill_names):
        result = await session.execute(
            select(UserSkill)
            .where(UserSkill.user_id == user_id)
            .where(UserSkill.name == skill_name)
        )
        old_skill = result.scalar_one_or_none()
        if old_skill is not None:
            old_skill.is_enabled = False
            old_skill.updated_at = datetime.utcnow()

    metadata = dict(installed.metadata_ or {})
    metadata["skill_names"] = skill_names
    installed.metadata_ = metadata
    await session.flush()


async def _toggle_materialized_skills(
    session: AsyncSession,
    installed: InstalledPlugin,
    enabled: bool,
) -> None:
    skill_names = list((installed.metadata_ or {}).get("skill_names") or [])
    for skill_name in skill_names:
        result = await session.execute(
            select(UserSkill)
            .where(UserSkill.user_id == installed.user_id)
            .where(UserSkill.name == skill_name)
        )
        skill = result.scalar_one_or_none()
        if skill is not None:
            skill.is_enabled = enabled
            skill.updated_at = datetime.utcnow()
    await session.flush()


async def _installed_plugin_to_dict(session: AsyncSession, package: InstalledPlugin) -> dict[str, Any]:
    manifest = package.manifest_snapshot if isinstance(package.manifest_snapshot, dict) else {}
    latest_manifest = await get_registry_package(session, package.package_id)
    latest_version = latest_manifest.version if latest_manifest else package.version
    history = _installed_history_entries(package)
    previous_version = history[-2]["version"] if len(history) >= 2 else None
    available_versions = [row.version for row in reversed(await _get_package_versions(session, package.package_id))]

    return {
        "id": package.id,
        "package_id": package.package_id,
        "display_name": package.display_name,
        "package_kind": package.package_kind,
        "version": package.version,
        "source": package.source,
        "manifest": manifest,
        "granted_permissions": package.granted_permissions,
        "status": package.status,
        "is_enabled": package.is_enabled,
        "installed_at": package.installed_at.isoformat() if package.installed_at else None,
        "updated_at": package.updated_at.isoformat() if package.updated_at else None,
        "latest_version": latest_version,
        "previous_version": previous_version,
        "available_versions": available_versions,
        "upgrade_available": _compare_versions(package.version, latest_version) < 0,
        "installed_history": history,
        "release_notes": manifest.get("metadata", {}).get("release_notes") if isinstance(manifest, dict) else None,
        "latest_release_notes": latest_manifest.metadata.get("release_notes") if latest_manifest else None,
    }