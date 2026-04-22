"""声明式 Package Registry — P0 阶段的官方内置包目录与安装管理。"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import InstalledPackage
from app.schemas.package_manifest import PluginPackageManifest


_INSTALLED_STATE_KEY = "_installed_state"
_SEMVER_CORE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def _parse_semver(version: str) -> tuple[int, int, int]:
    match = _SEMVER_CORE_RE.match(version)
    if match is None:
        raise ValueError(f"非法 semver: {version}")
    return tuple(int(part) for part in match.groups())


def _compare_versions(left: str, right: str) -> int:
    left_tuple = _parse_semver(left)
    right_tuple = _parse_semver(right)
    if left_tuple < right_tuple:
        return -1
    if left_tuple > right_tuple:
        return 1
    return 0

_BUILTIN_MANIFESTS: tuple[dict[str, Any], ...] = (
    {
        "schema_version": "1.0.0",
        "package_id": "official.deckspec-contract",
        "display_name": "DeckSpec Contract",
        "kind": "foundation",
        "version": "0.1.0",
        "description": "提供 Native PPTX-first 与 HTML 预览双产物共享的 DeckSpec 统一结构契约。",
        "publisher": "GeneralAgent",
        "tags": ["pptx", "deckspec", "foundation"],
        "capabilities": ["deckspec.contract"],
        "permissions": [
            {"name": "registry.read", "rationale": "读取平台内置契约元数据"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "deckspec.v1",
                "description": "为渲染器、工作流和 QA 提供共享数据约束。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-21",
            "release_notes": "首个公开版本，提供 DeckSpec 基础约束与渲染共享契约。",
            "upgrade_notes": "无。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.deckspec-contract",
        "display_name": "DeckSpec Contract",
        "kind": "foundation",
        "version": "0.2.0",
        "description": "提供 Native PPTX-first 与 HTML 预览双产物共享的 DeckSpec 统一结构契约，并补充审查元数据。",
        "publisher": "GeneralAgent",
        "tags": ["pptx", "deckspec", "foundation"],
        "capabilities": ["deckspec.contract", "deckspec.qa_metadata"],
        "permissions": [
            {"name": "registry.read", "rationale": "读取平台内置契约元数据"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "deckspec.v1",
                "description": "为渲染器、工作流和 QA 提供共享数据约束。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-30",
            "release_notes": "新增对象级 QA 元数据与布局诊断字段，便于升级后的版本对比和回滚审计。",
            "upgrade_notes": "建议与 0.2.x 渲染器及工作流一起升级，避免旧版依赖缺少 QA 字段。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.native-pptx-renderer",
        "display_name": "Native PPTX Renderer",
        "kind": "tool_adapter",
        "version": "0.1.0",
        "description": "将 DeckSpec 渲染为 Native PPTX，可作为未来原生可编辑导出的权威渲染器。",
        "publisher": "GeneralAgent",
        "tags": ["pptx", "renderer", "native"],
        "capabilities": ["pptx.render.native"],
        "permissions": [
            {"name": "pptx.render", "rationale": "执行 Native PPTX 渲染任务"},
            {"name": "asset.write", "rationale": "保存渲染产物到平台资产库"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.1.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "render.native_pptx",
                "description": "将 DeckSpec 渲染为可编辑 PPTX。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-21",
            "release_notes": "提供基础 Native PPTX 导出链路。",
            "upgrade_notes": "无。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.native-pptx-renderer",
        "display_name": "Native PPTX Renderer",
        "kind": "tool_adapter",
        "version": "0.2.0",
        "description": "将 DeckSpec 渲染为 Native PPTX，并补充母版映射与对象级回溯信息。",
        "publisher": "GeneralAgent",
        "tags": ["pptx", "renderer", "native"],
        "capabilities": ["pptx.render.native", "pptx.render.master_mapping"],
        "permissions": [
            {"name": "pptx.render", "rationale": "执行 Native PPTX 渲染任务"},
            {"name": "asset.write", "rationale": "保存渲染产物到平台资产库"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.2.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "render.native_pptx",
                "description": "将 DeckSpec 渲染为可编辑 PPTX。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-30",
            "release_notes": "新增母版映射与对象级 trace id，便于导出后比对与问题回溯。",
            "upgrade_notes": "升级后建议重导出最近一版 deck，以补齐 trace id。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.html-preview-renderer",
        "display_name": "HTML Preview Renderer",
        "kind": "tool_adapter",
        "version": "0.1.0",
        "description": "将 DeckSpec 渲染为受约束的 HTML 预览产物，用于协作审阅和快速预览。",
        "publisher": "GeneralAgent",
        "tags": ["preview", "html", "renderer"],
        "capabilities": ["preview.render.html"],
        "permissions": [
            {"name": "preview.render", "rationale": "生成 Web 预览内容"},
            {"name": "asset.write", "rationale": "保存预览产物和缩略图"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.1.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "render.html_preview",
                "description": "将 DeckSpec 渲染为平台预览 HTML。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-21",
            "release_notes": "基础 HTML 预览输出，覆盖常用页面类型。",
            "upgrade_notes": "无。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.html-preview-renderer",
        "display_name": "HTML Preview Renderer",
        "kind": "tool_adapter",
        "version": "0.2.0",
        "description": "将 DeckSpec 渲染为受约束的 HTML 预览产物，并输出布局诊断标记。",
        "publisher": "GeneralAgent",
        "tags": ["preview", "html", "renderer"],
        "capabilities": ["preview.render.html", "preview.render.overlay_debug"],
        "permissions": [
            {"name": "preview.render", "rationale": "生成 Web 预览内容"},
            {"name": "asset.write", "rationale": "保存预览产物和缩略图"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.2.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["dual_render"],
        },
        "entrypoints": [
            {
                "kind": "adapter",
                "target": "render.html_preview",
                "description": "将 DeckSpec 渲染为平台预览 HTML。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-30",
            "release_notes": "新增布局诊断 overlay，支持版本对比时快速定位版式变化。",
            "upgrade_notes": "若依赖前端截图回归，建议重新采样缩略图。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "minimax.pptx-generator-skillset",
        "display_name": "MiniMax PPTX Generator Skillset",
        "kind": "skill",
        "version": "0.1.0",
        "description": "引入 MiniMax 成熟的 PPTX 内容组织与页面类型知识库，以 Skill 包形式注入平台。",
        "publisher": "MiniMax-Compatible",
        "tags": ["minimax", "pptx", "skill"],
        "capabilities": ["skill.storylining", "skill.page_archetypes", "skill.design_constraints"],
        "permissions": [
            {"name": "registry.read", "rationale": "读取依赖包与平台能力说明"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.1.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "skill_set",
                "target": "skills/minimax-pptx-generator",
                "description": "提供 PPT 页面模式、叙事结构和风格约束。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-21",
            "release_notes": "导入 MiniMax 的基础 PPTX 页面类型与叙事结构知识。",
            "upgrade_notes": "无。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "minimax.pptx-generator-skillset",
        "display_name": "MiniMax PPTX Generator Skillset",
        "kind": "skill",
        "version": "0.2.0",
        "description": "引入 MiniMax 成熟的 PPTX 内容组织与页面类型知识库，并补充内容密度与版式风险约束。",
        "publisher": "MiniMax-Compatible",
        "tags": ["minimax", "pptx", "skill"],
        "capabilities": [
            "skill.storylining",
            "skill.page_archetypes",
            "skill.design_constraints",
            "skill.density_guardrails",
        ],
        "permissions": [
            {"name": "registry.read", "rationale": "读取依赖包与平台能力说明"},
        ],
        "dependencies": [
            {"package_id": "official.deckspec-contract", "version_constraint": "=0.2.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "skill_set",
                "target": "skills/minimax-pptx-generator",
                "description": "提供 PPT 页面模式、叙事结构和风格约束。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-30",
            "release_notes": "新增页面密度护栏与版式风险约束，减少生成后期返工。",
            "upgrade_notes": "升级后建议重新生成大纲，以便新约束充分生效。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.native-pptx-orchestrator",
        "display_name": "Native PPTX Orchestrator",
        "kind": "workflow",
        "version": "0.1.0",
        "description": "官方 Native PPTX-first 工作流编排包，统一处理澄清、规划、渲染与审查。",
        "publisher": "GeneralAgent",
        "tags": ["workflow", "pptx", "native"],
        "capabilities": ["workflow.requirement_clarification", "workflow.deck_planning", "workflow.review_repair"],
        "permissions": [
            {"name": "model.invoke", "rationale": "执行规划、审查与修复阶段的模型调用"},
            {"name": "asset.read", "rationale": "读取用户上传的参考资料与模板资产"},
            {"name": "document.parse", "rationale": "解析上传文档形成结构化输入"},
        ],
        "dependencies": [
            {"package_id": "official.native-pptx-renderer", "version_constraint": "=0.1.0"},
            {"package_id": "official.html-preview-renderer", "version_constraint": "=0.1.0"},
            {"package_id": "minimax.pptx-generator-skillset", "version_constraint": "=0.1.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "workflow",
                "target": "workflows/native-pptx-orchestrator",
                "description": "以插件工作流取代 legacy HTML 大纲/逐页生成链。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-21",
            "release_notes": "原生 PPTX-first 的首个官方工作流版本。",
            "upgrade_notes": "无。",
        },
    },
    {
        "schema_version": "1.0.0",
        "package_id": "official.native-pptx-orchestrator",
        "display_name": "Native PPTX Orchestrator",
        "kind": "workflow",
        "version": "0.2.0",
        "description": "官方 Native PPTX-first 工作流编排包，补充澄清闭环、版本审查和回滚感知。",
        "publisher": "GeneralAgent",
        "tags": ["workflow", "pptx", "native"],
        "capabilities": [
            "workflow.requirement_clarification",
            "workflow.deck_planning",
            "workflow.review_repair",
            "workflow.version_audit",
        ],
        "permissions": [
            {"name": "model.invoke", "rationale": "执行规划、审查与修复阶段的模型调用"},
            {"name": "asset.read", "rationale": "读取用户上传的参考资料与模板资产"},
            {"name": "document.parse", "rationale": "解析上传文档形成结构化输入"},
        ],
        "dependencies": [
            {"package_id": "official.native-pptx-renderer", "version_constraint": "=0.2.0"},
            {"package_id": "official.html-preview-renderer", "version_constraint": "=0.2.0"},
            {"package_id": "minimax.pptx-generator-skillset", "version_constraint": "=0.2.0"},
        ],
        "compatibility": {
            "min_platform_version": "0.1.0",
            "target_artifact_mode": ["native_pptx_first", "dual_render"],
        },
        "entrypoints": [
            {
                "kind": "workflow",
                "target": "workflows/native-pptx-orchestrator",
                "description": "以插件工作流取代 legacy HTML 大纲/逐页生成链。",
            }
        ],
        "metadata": {
            "release_date": "2026-03-30",
            "release_notes": "新增版本审查与回滚感知编排，前端可直接展示一键升级和版本对比。",
            "upgrade_notes": "升级后建议同步升级依赖包，并重新开启工作流以加载新编排节点。",
        },
    },
)

BUILTIN_RELEASES: dict[tuple[str, str], PluginPackageManifest] = {}
BUILTIN_REGISTRY: dict[str, list[PluginPackageManifest]] = {}
for _manifest in (PluginPackageManifest.model_validate(item) for item in _BUILTIN_MANIFESTS):
    BUILTIN_RELEASES[(_manifest.package_id, _manifest.version)] = _manifest
    BUILTIN_REGISTRY.setdefault(_manifest.package_id, []).append(_manifest)

for package_id, manifests in BUILTIN_REGISTRY.items():
    BUILTIN_REGISTRY[package_id] = sorted(manifests, key=lambda item: _parse_semver(item.version))


def list_registry_packages() -> list[dict[str, Any]]:
    return [manifests[-1].model_dump() for manifests in BUILTIN_REGISTRY.values()]


def list_registry_package_versions(package_id: str) -> list[dict[str, Any]]:
    manifests = BUILTIN_REGISTRY.get(package_id)
    if not manifests:
        return []

    latest_version = manifests[-1].version
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
        for manifest in reversed(manifests)
    ]


def get_registry_package(package_id: str, version: str | None = None) -> PluginPackageManifest | None:
    manifests = BUILTIN_REGISTRY.get(package_id)
    if not manifests:
        return None
    if version is None:
        return manifests[-1]
    return BUILTIN_RELEASES.get((package_id, version))


def validate_manifest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = PluginPackageManifest.model_validate(payload)
    return manifest.model_dump()


def compare_registry_package_versions(
    package_id: str,
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    from_manifest = get_registry_package(package_id, from_version)
    to_manifest = get_registry_package(package_id, to_version)
    if from_manifest is None or to_manifest is None:
        raise ValueError("指定版本不存在")

    from_permissions = {item.name: item.rationale for item in from_manifest.permissions}
    to_permissions = {item.name: item.rationale for item in to_manifest.permissions}
    from_dependencies = {
        item.package_id: item.version_constraint for item in from_manifest.dependencies
    }
    to_dependencies = {
        item.package_id: item.version_constraint for item in to_manifest.dependencies
    }
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


def resolve_registry_dependencies(
    package_id: str,
    version: str | None = None,
) -> list[PluginPackageManifest]:
    resolved: list[PluginPackageManifest] = []
    visiting: set[str] = set()
    selected_versions: dict[str, str] = {}

    def dfs(
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
            manifest = get_registry_package(current_id, requested_version)
        elif constraint is not None:
            manifest = _select_manifest_for_constraint(current_id, constraint)
        else:
            manifest = get_registry_package(current_id)

        if manifest is None:
            raise ValueError(f"未找到 package: {current_id}")

        visiting.add(current_id)
        for dependency in manifest.dependencies:
            if dependency.optional:
                continue
            dfs(dependency.package_id, constraint=dependency.version_constraint)
        visiting.remove(current_id)

        selected_versions[current_id] = manifest.version
        resolved.append(manifest)

    dfs(package_id, requested_version=version)
    return resolved


async def list_installed_packages(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    result = await session.execute(
        select(InstalledPackage)
        .where(InstalledPackage.user_id == user_id)
        .order_by(InstalledPackage.package_id)
    )
    return [_installed_package_to_dict(row) for row in result.scalars().all()]


async def install_registry_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    version: str | None = None,
    *,
    action: str = "install",
) -> list[dict[str, Any]]:
    manifests = resolve_registry_dependencies(package_id, version)
    installed_packages: list[InstalledPackage] = []

    for manifest in manifests:
        result = await session.execute(
            select(InstalledPackage)
            .where(InstalledPackage.user_id == user_id)
            .where(InstalledPackage.package_id == manifest.package_id)
        )
        existing = result.scalar_one_or_none()

        if existing:
            status = _status_for_action(action, existing.version != manifest.version)
            existing.version = manifest.version
            existing.display_name = manifest.display_name
            existing.package_kind = manifest.kind
            existing.manifest = _build_stored_manifest(manifest, existing, action)
            existing.granted_permissions = [
                permission.model_dump() for permission in manifest.permissions
            ]
            existing.status = status
            existing.is_enabled = True
            installed_packages.append(existing)
            continue

        created = InstalledPackage(
            user_id=user_id,
            package_id=manifest.package_id,
            display_name=manifest.display_name,
            package_kind=manifest.kind,
            version=manifest.version,
            source="registry",
            manifest=_build_stored_manifest(manifest, None, action),
            granted_permissions=[
                permission.model_dump() for permission in manifest.permissions
            ],
            status=_status_for_action(action, version_changed=True),
            is_enabled=True,
        )
        session.add(created)
        await session.flush()
        installed_packages.append(created)

    await session.commit()
    return [_installed_package_to_dict(item) for item in installed_packages]


async def upgrade_installed_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    target_version: str | None = None,
) -> list[dict[str, Any]]:
    result = await session.execute(
        select(InstalledPackage)
        .where(InstalledPackage.user_id == user_id)
        .where(InstalledPackage.package_id == package_id)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise LookupError("Package 未安装")

    manifest = get_registry_package(package_id, target_version)
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
    result = await session.execute(
        select(InstalledPackage)
        .where(InstalledPackage.user_id == user_id)
        .where(InstalledPackage.package_id == package_id)
    )
    package = result.scalar_one_or_none()
    if package is None:
        raise LookupError("Package 未安装")

    history = _get_installed_history(package)
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
    result = await session.execute(
        select(InstalledPackage)
        .where(InstalledPackage.user_id == user_id)
        .where(InstalledPackage.package_id == package_id)
    )
    package = result.scalar_one_or_none()
    if package is None:
        return None

    package.is_enabled = enabled
    package.status = "installed" if enabled else "disabled"
    await session.commit()
    await session.refresh(package)
    return _installed_package_to_dict(package)
def _version_satisfies(version: str, constraint: str) -> bool:
    parts = [part.strip() for part in constraint.split(",") if part.strip()]
    if not parts:
        return True

    for part in parts:
        operator = "=="
        target = part
        for prefix in (">=", "<=", "==", ">", "<", "="):
            if part.startswith(prefix):
                operator = "==" if prefix == "=" else prefix
                target = part[len(prefix) :].strip()
                break

        comparison = _compare_versions(version, target)
        if operator == "==" and comparison != 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == "<" and comparison >= 0:
            return False

    return True


def _select_manifest_for_constraint(
    package_id: str,
    constraint: str,
) -> PluginPackageManifest | None:
    manifests = BUILTIN_REGISTRY.get(package_id, [])
    for manifest in reversed(manifests):
        if _version_satisfies(manifest.version, constraint):
            return manifest
    return None


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _status_for_action(action: str, version_changed: bool) -> str:
    if action == "rollback":
        return "rolled_back"
    if action == "upgrade" and version_changed:
        return "upgraded"
    return "installed"


def _strip_installed_state(manifest: dict[str, Any]) -> dict[str, Any]:
    clean = deepcopy(manifest)
    clean.pop(_INSTALLED_STATE_KEY, None)
    return clean


def _get_installed_history(package: InstalledPackage) -> list[dict[str, Any]]:
    if not isinstance(package.manifest, dict):
        return []

    raw_state = package.manifest.get(_INSTALLED_STATE_KEY)
    if isinstance(raw_state, dict):
        history = raw_state.get("history")
        if isinstance(history, list) and history:
            normalized_history: list[dict[str, Any]] = []
            for item in history:
                if not isinstance(item, dict) or not isinstance(item.get("version"), str):
                    continue
                normalized_history.append(
                    {
                        "version": item["version"],
                        "changed_at": item.get("changed_at") or _utcnow_iso(),
                        "action": item.get("action") or "install",
                        "manifest": item.get("manifest")
                        if isinstance(item.get("manifest"), dict)
                        else _strip_installed_state(package.manifest),
                    }
                )
            if normalized_history:
                return normalized_history

    fallback_timestamp = (
        package.updated_at.isoformat()
        if package.updated_at
        else package.installed_at.isoformat()
        if package.installed_at
        else _utcnow_iso()
    )
    return [
        {
            "version": package.version,
            "changed_at": fallback_timestamp,
            "action": "install",
            "manifest": _strip_installed_state(package.manifest),
        }
    ]


def _build_stored_manifest(
    manifest: PluginPackageManifest,
    existing: InstalledPackage | None,
    action: str,
) -> dict[str, Any]:
    base_manifest = manifest.model_dump()
    history = _get_installed_history(existing) if existing is not None else []

    if not history or history[-1].get("version") != manifest.version:
        history.append(
            {
                "version": manifest.version,
                "changed_at": _utcnow_iso(),
                "action": action,
                "manifest": deepcopy(base_manifest),
            }
        )
    else:
        history[-1] = {
            "version": manifest.version,
            "changed_at": _utcnow_iso(),
            "action": action,
            "manifest": deepcopy(base_manifest),
        }

    base_manifest[_INSTALLED_STATE_KEY] = {
        "history": history[-10:],
        "previous_version": history[-2]["version"] if len(history) >= 2 else None,
        "last_action": action,
    }
    return base_manifest


def _installed_package_to_dict(package: InstalledPackage) -> dict[str, Any]:
    manifest = _strip_installed_state(package.manifest) if isinstance(package.manifest, dict) else {}
    latest_manifest = get_registry_package(package.package_id)
    latest_version = latest_manifest.version if latest_manifest else package.version
    history = _get_installed_history(package)
    previous_version = history[-2]["version"] if len(history) >= 2 else None

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
        "available_versions": [
            item.version for item in reversed(BUILTIN_REGISTRY.get(package.package_id, []))
        ],
        "upgrade_available": _compare_versions(package.version, latest_version) < 0,
        "installed_history": [
            {
                "version": item["version"],
                "changed_at": item.get("changed_at"),
                "action": item.get("action"),
            }
            for item in history
        ],
        "release_notes": manifest.get("metadata", {}).get("release_notes") if isinstance(manifest, dict) else None,
        "latest_release_notes": latest_manifest.metadata.get("release_notes") if latest_manifest else None,
    }