"""Package runtime dispatch for HTML preview and generic package adapters."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from time import perf_counter
from typing import Any
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.deck_spec import DeckSpec
from app.schemas.package_manifest import PluginPackageManifest
from app.services.deckspec_preview_service import render_deck_to_html_preview
from app.services.ppt_service import get_or_build_canonical_deckspec, get_presentation
from app.services.plugin_registry import (
    record_artifact_variant,
    get_installed_plugin_row,
    get_registry_package,
    install_registry_package,
    record_execution_log,
)

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = BACKEND_ROOT / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RUNTIME_USER_ID = "default-user-00000000"
OFFICIAL_HTML_PREVIEW_RENDERER = "official.html-preview-renderer"


class PackageRuntimeError(RuntimeError):
    """Raised when a package runtime dependency is missing or disabled."""


async def invoke_html_preview_renderer_package(
    session: AsyncSession,
    user_id: str,
    deck_spec: DeckSpec,
) -> tuple[str, dict[str, Any]]:
    return await _invoke_registered_html_preview_package(
        session,
        user_id,
        OFFICIAL_HTML_PREVIEW_RENDERER,
        deck_spec,
    )


async def invoke_tool_adapter_package(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str,
    adapter_target: str,
    params: dict[str, Any],
    tool_name: str | None = None,
) -> dict[str, Any]:
    installed, manifest = await _ensure_package_enabled(session, user_id, package_id)
    entrypoint = _resolve_entrypoint(manifest, adapter_target)
    target_type, target_id = _extract_runtime_target(params)
    input_payload = {
        "tool_name": tool_name or adapter_target,
        "adapter_target": adapter_target,
        "entrypoint": entrypoint.target,
        "params": params,
    }
    started = perf_counter()

    try:
        result, output_payload = await _execute_tool_adapter_entrypoint(
            session,
            user_id,
            package_id=package_id,
            adapter_target=adapter_target,
            params=params,
        )
    except Exception as exc:
        await record_execution_log(
            session,
            user_id=user_id,
            package_id=manifest.package_id,
            package_version=manifest.version,
            installed_plugin_id=installed.id,
            plugin_version_id=installed.active_version_id,
            execution_kind="tool",
            status="failed",
            target_type=target_type,
            target_id=target_id,
            input_payload=input_payload,
            error_message=str(exc),
            duration_ms=int((perf_counter() - started) * 1000),
        )
        await session.commit()
        raise

    execution_log = await record_execution_log(
        session,
        user_id=user_id,
        package_id=manifest.package_id,
        package_version=manifest.version,
        installed_plugin_id=installed.id,
        plugin_version_id=installed.active_version_id,
        execution_kind="tool",
        target_type=target_type,
        target_id=target_id,
        input_payload=input_payload,
        output_payload=output_payload,
        duration_ms=int((perf_counter() - started) * 1000),
    )
    await session.commit()

    result.update(
        {
            "package_id": manifest.package_id,
            "package_version": manifest.version,
            "entrypoint": entrypoint.target,
            "installed_plugin_id": installed.id,
            "execution_log_id": execution_log.id,
            "tool_name": tool_name or adapter_target,
        }
    )
    return result


async def _execute_tool_adapter_entrypoint(
    session: AsyncSession,
    user_id: str,
    *,
    package_id: str,
    adapter_target: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    presentation_id = str(params.get("presentation_id") or "").strip()

    if adapter_target == "deckspec.v1":
        deck_spec = await _require_presentation_deckspec(session, presentation_id)
        return (
            {
                "presentation_id": presentation_id,
                "deck_spec": deck_spec.model_dump(mode="python"),
                "slide_count": len(deck_spec.slides),
            },
            {
                "slide_count": len(deck_spec.slides),
                "artifact_mode": deck_spec.artifact_mode,
            },
        )

    if adapter_target == "render.html_preview":
        presentation = await _require_presentation(session, presentation_id)
        deck_spec = await _require_presentation_deckspec(session, presentation_id)
        html_content, meta = await _invoke_registered_html_preview_package(
            session,
            user_id,
            package_id,
            deck_spec,
        )
        file_url, download_url = _write_export_text(
            presentation.get("title") or presentation_id,
            ".html",
            html_content,
        )
        artifact = await record_artifact_variant(
            session,
            user_id,
            package_id=meta.get("package_id") or package_id,
            package_version=meta.get("package_version"),
            variant_type="html-preview",
            file_url=file_url,
            presentation_id=presentation_id,
            installed_plugin_id=meta.get("installed_plugin_id"),
            execution_log_id=meta.get("execution_log_id"),
            mime_type="text/html",
            metadata={
                "download_url": download_url,
                "node_count": meta.get("nodeCount"),
                "preview_execution_log_id": meta.get("execution_log_id"),
            },
        )
        result = {
            "presentation_id": presentation_id,
            "file_url": file_url,
            "download_url": download_url,
            "artifact_variant_id": artifact.id,
            "slide_count": meta.get("slideCount"),
            "node_count": meta.get("nodeCount"),
        }
        if params.get("include_html"):
            result["html"] = html_content
        return (
            result,
            {
                "variant_type": "html-preview",
                "slide_count": meta.get("slideCount"),
                "node_count": meta.get("nodeCount"),
                "preview_execution_log_id": meta.get("execution_log_id"),
            },
        )

    raise PackageRuntimeError(f"Package {package_id} 的 adapter target 暂不支持动态 Tool 调用: {adapter_target}")


async def _invoke_registered_html_preview_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    deck_spec: DeckSpec,
) -> tuple[str, dict[str, Any]]:
    installed, manifest = await _ensure_package_enabled(session, user_id, package_id)
    entrypoint = _resolve_entrypoint(manifest, "render.html_preview")
    started = perf_counter()

    try:
        html_content, meta = render_deck_to_html_preview(deck_spec)
    except Exception as exc:
        await record_execution_log(
            session,
            user_id=user_id,
            package_id=manifest.package_id,
            package_version=manifest.version,
            installed_plugin_id=installed.id,
            plugin_version_id=installed.active_version_id,
            execution_kind="render",
            status="failed",
            target_type="presentation",
            target_id=deck_spec.deck_id,
            input_payload={
                "slide_count": len(deck_spec.slides),
                "entrypoint": entrypoint.target,
                "artifact_mode": deck_spec.artifact_mode,
            },
            error_message=str(exc),
            duration_ms=int((perf_counter() - started) * 1000),
        )
        await session.commit()
        raise

    execution_log = await record_execution_log(
        session,
        user_id=user_id,
        package_id=manifest.package_id,
        package_version=manifest.version,
        installed_plugin_id=installed.id,
        plugin_version_id=installed.active_version_id,
        execution_kind="render",
        target_type="presentation",
        target_id=deck_spec.deck_id,
        input_payload={
            "slide_count": len(deck_spec.slides),
            "entrypoint": entrypoint.target,
            "artifact_mode": deck_spec.artifact_mode,
        },
        output_payload={
            "slide_count": meta.get("slideCount"),
            "node_count": meta.get("nodeCount"),
            "html_bytes": len(html_content.encode("utf-8")),
        },
        duration_ms=int((perf_counter() - started) * 1000),
    )
    await session.commit()

    meta.update(
        {
            "package_id": manifest.package_id,
            "package_version": manifest.version,
            "entrypoint": entrypoint.target,
            "installed_plugin_id": installed.id,
            "execution_log_id": execution_log.id,
        }
    )
    return html_content, meta


async def _require_presentation(session: AsyncSession, presentation_id: str) -> dict[str, Any]:
    if not presentation_id:
        raise PackageRuntimeError("presentation_id 不能为空")
    presentation = await get_presentation(session, presentation_id)
    if presentation is None:
        raise PackageRuntimeError(f"演示文稿不存在: {presentation_id}")
    return presentation


async def _require_presentation_deckspec(session: AsyncSession, presentation_id: str) -> DeckSpec:
    if not presentation_id:
        raise PackageRuntimeError("presentation_id 不能为空")
    deck_spec = await get_or_build_canonical_deckspec(session, presentation_id)
    if deck_spec is None:
        raise PackageRuntimeError(f"演示文稿缺少 canonical DeckSpec: {presentation_id}")
    return deck_spec


def _extract_runtime_target(params: dict[str, Any]) -> tuple[str | None, str | None]:
    presentation_id = str(params.get("presentation_id") or "").strip()
    if presentation_id:
        return "presentation", presentation_id
    return None, None


def _sanitize_export_title(title: str) -> str:
    safe_title = re.sub(r"[^\w\u4e00-\u9fff-]", "_", title or "artifact")[:50]
    return safe_title.strip("_") or "artifact"


def _write_export_text(title: str, extension: str, content: str) -> tuple[str, str]:
    filename = f"{_sanitize_export_title(title)}_{uuid.uuid4().hex[:8]}{extension}"
    filepath = EXPORT_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    return f"exports/{filename}", f"/static/exports/{filename}"


async def _ensure_package_enabled(
    session: AsyncSession,
    user_id: str,
    package_id: str,
) -> tuple[Any, PluginPackageManifest]:
    package = await get_installed_plugin_row(session, user_id, package_id)
    if package is None:
        logger.info("[PackageRuntime] bootstrap package: %s", package_id)
        await install_registry_package(session, user_id, package_id)
        package = await get_installed_plugin_row(session, user_id, package_id)

    if package is None:
        raise PackageRuntimeError(f"Package {package_id} 安装失败")
    if not package.is_enabled:
        raise PackageRuntimeError(f"Package {package_id} 已禁用")

    manifest = await get_registry_package(session, package.package_id, package.version)
    if manifest is None:
        raise PackageRuntimeError(f"Package {package.package_id}@{package.version} 未在 registry 中注册")
    return package, manifest


def _resolve_entrypoint(
    manifest: PluginPackageManifest,
    target: str,
):
    for entrypoint in manifest.entrypoints:
        if entrypoint.target == target:
            return entrypoint
    raise PackageRuntimeError(f"Package {manifest.package_id} 缺少 entrypoint: {target}")

