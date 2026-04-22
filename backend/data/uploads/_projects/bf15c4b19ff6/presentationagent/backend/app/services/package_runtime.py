"""Package runtime dispatch for native renderer and workflow packages."""

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
from app.services.native_renderer_service import build_deckspec_from_slides, render_deck_to_pptx
from app.services.ppt_service import get_or_build_canonical_deckspec, get_presentation, persist_canonical_deckspec
from app.services.plugin_registry import (
    record_artifact_variant,
    get_installed_plugin_row,
    get_registry_package,
    install_registry_package,
    record_execution_log,
    upsert_workflow_binding,
)

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXPORT_DIR = BACKEND_ROOT / "data" / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_RUNTIME_USER_ID = "default-user-00000000"
OFFICIAL_NATIVE_RENDERER = "official.native-pptx-renderer"
OFFICIAL_HTML_PREVIEW_RENDERER = "official.html-preview-renderer"
OFFICIAL_NATIVE_ORCHESTRATOR = "official.native-pptx-orchestrator"
MINIMAX_PPTX_PLUGIN = "minimax.pptx-plugin"

WORKFLOW_ENTRYPOINT_TARGETS = {
    OFFICIAL_NATIVE_ORCHESTRATOR: "workflows/native-pptx-orchestrator",
    MINIMAX_PPTX_PLUGIN: "workflows/minimax-pptx-plugin",
}


class PackageRuntimeError(RuntimeError):
    """Raised when a package runtime dependency is missing or disabled."""


async def invoke_native_renderer_package(
    session: AsyncSession,
    user_id: str,
    deck_spec: DeckSpec,
    *,
    author: str = "GeneralAgent Native Renderer",
    company: str = "GeneralAgent",
    subject: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    return await _invoke_registered_native_renderer_package(
        session,
        user_id,
        OFFICIAL_NATIVE_RENDERER,
        deck_spec,
        author=author,
        company=company,
        subject=subject,
    )


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


async def invoke_pptx_workflow_package(
    session: AsyncSession,
    user_id: str,
    *,
    presentation_id: str,
    title: str,
    theme_id: str,
    slides_data: list[dict[str, Any]],
    package_id: str = OFFICIAL_NATIVE_ORCHESTRATOR,
) -> dict[str, Any]:
    installed, manifest = await _ensure_package_enabled(session, user_id, package_id)
    entrypoint = _resolve_workflow_entrypoint(manifest, package_id)
    binding = await upsert_workflow_binding(
        session,
        user_id,
        installed,
        binding_type="presentation",
        presentation_id=presentation_id,
        config={"theme_id": theme_id, "entrypoint": entrypoint.target},
    )

    deck_spec = await get_or_build_canonical_deckspec(session, presentation_id)
    if deck_spec is None:
        deck_spec = build_deckspec_from_slides(
            presentation_id=presentation_id,
            title=title,
            theme_id=theme_id,
            slides_data=slides_data,
            artifact_mode="dual_render",
        )
    deck_spec = _annotate_deckspec(deck_spec, manifest, binding_id=binding.id)
    await persist_canonical_deckspec(
        session,
        presentation_id,
        deck_spec,
        source="workflow_runtime",
        metadata={"package_id": manifest.package_id, "package_version": manifest.version},
    )

    started = perf_counter()
    workflow_error: Exception | None = None
    render_result: tuple[bytes, dict[str, Any]] | None = None
    preview_result: tuple[str, dict[str, Any]] | None = None
    try:
        render_result = await invoke_native_renderer_package(
            session,
            user_id,
            deck_spec,
            subject=title,
        )
        preview_result = await invoke_html_preview_renderer_package(
            session,
            user_id,
            deck_spec,
        )
    except Exception as exc:
        workflow_error = exc

    workflow_log = await record_execution_log(
        session,
        user_id=user_id,
        package_id=manifest.package_id,
        package_version=manifest.version,
        installed_plugin_id=installed.id,
        plugin_version_id=installed.active_version_id,
        execution_kind="workflow",
        status="failed" if workflow_error else "succeeded",
        target_type="presentation",
        target_id=presentation_id,
        input_payload={
            "slide_count": len(slides_data),
            "theme_id": theme_id,
            "entrypoint": entrypoint.target,
        },
        output_payload=(
            {
                "renderer_package_id": render_result[1].get("package_id"),
                "renderer_execution_log_id": render_result[1].get("execution_log_id"),
                "preview_package_id": preview_result[1].get("package_id") if preview_result is not None else None,
                "preview_execution_log_id": preview_result[1].get("execution_log_id") if preview_result is not None else None,
                "slide_count": len(deck_spec.slides),
            }
            if render_result is not None
            else None
        ),
        error_message=str(workflow_error) if workflow_error else None,
        duration_ms=int((perf_counter() - started) * 1000),
    )
    await session.commit()

    if workflow_error is not None:
        raise workflow_error

    pptx_content, render_meta = render_result
    html_preview_content, preview_meta = preview_result if preview_result is not None else ("", {})
    return {
        "deck_spec": deck_spec,
        "pptx_content": pptx_content,
        "html_preview_content": html_preview_content,
        "workflow": {
            "package_id": manifest.package_id,
            "package_version": manifest.version,
            "entrypoint": entrypoint.target,
            "slide_count": len(deck_spec.slides),
            "installed_plugin_id": installed.id,
            "binding_id": binding.id,
            "execution_log_id": workflow_log.id,
        },
        "renderer": render_meta,
        "preview": preview_meta,
    }


async def invoke_native_orchestrator_package(
    session: AsyncSession,
    user_id: str,
    *,
    presentation_id: str,
    title: str,
    theme_id: str,
    slides_data: list[dict[str, Any]],
) -> dict[str, Any]:
    return await invoke_pptx_workflow_package(
        session,
        user_id,
        package_id=OFFICIAL_NATIVE_ORCHESTRATOR,
        presentation_id=presentation_id,
        title=title,
        theme_id=theme_id,
        slides_data=slides_data,
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

    if adapter_target == "render.native_pptx":
        presentation = await _require_presentation(session, presentation_id)
        deck_spec = await _require_presentation_deckspec(session, presentation_id)
        pptx_content, meta = await _invoke_registered_native_renderer_package(
            session,
            user_id,
            package_id,
            deck_spec,
            subject=presentation.get("title") or presentation_id,
        )
        file_url, download_url = _write_export_bytes(
            presentation.get("title") or presentation_id,
            ".pptx",
            pptx_content,
        )
        artifact = await record_artifact_variant(
            session,
            user_id,
            package_id=meta.get("package_id") or package_id,
            package_version=meta.get("package_version"),
            variant_type="pptx-native",
            file_url=file_url,
            presentation_id=presentation_id,
            installed_plugin_id=meta.get("installed_plugin_id"),
            execution_log_id=meta.get("execution_log_id"),
            mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            metadata={
                "download_url": download_url,
                "warning_count": len(meta.get("warnings", [])),
                "renderer_execution_log_id": meta.get("execution_log_id"),
            },
        )
        return (
            {
                "presentation_id": presentation_id,
                "file_url": file_url,
                "download_url": download_url,
                "artifact_variant_id": artifact.id,
                "slide_count": meta.get("slideCount"),
                "warnings": meta.get("warnings", []),
            },
            {
                "variant_type": "pptx-native",
                "slide_count": meta.get("slideCount"),
                "warning_count": len(meta.get("warnings", [])),
                "renderer_execution_log_id": meta.get("execution_log_id"),
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


async def _invoke_registered_native_renderer_package(
    session: AsyncSession,
    user_id: str,
    package_id: str,
    deck_spec: DeckSpec,
    *,
    author: str = "GeneralAgent Native Renderer",
    company: str = "GeneralAgent",
    subject: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    installed, manifest = await _ensure_package_enabled(session, user_id, package_id)
    entrypoint = _resolve_entrypoint(manifest, "render.native_pptx")
    started = perf_counter()

    try:
        pptx_content, meta = await render_deck_to_pptx(
            deck_spec,
            author=author,
            company=company,
            subject=subject,
        )
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
            input_payload={"slide_count": len(deck_spec.slides), "entrypoint": entrypoint.target},
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
        input_payload={"slide_count": len(deck_spec.slides), "entrypoint": entrypoint.target},
        output_payload={
            "slide_count": meta.get("slideCount"),
            "warning_count": len(meta.get("warnings", [])),
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
    return pptx_content, meta


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


def _write_export_bytes(title: str, extension: str, content: bytes) -> tuple[str, str]:
    filename = f"{_sanitize_export_title(title)}_{uuid.uuid4().hex[:8]}{extension}"
    filepath = EXPORT_DIR / filename
    filepath.write_bytes(content)
    return f"exports/{filename}", f"/static/exports/{filename}"


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


def _resolve_workflow_entrypoint(
    manifest: PluginPackageManifest,
    package_id: str,
):
    target = WORKFLOW_ENTRYPOINT_TARGETS.get(package_id)
    if target is not None:
        return _resolve_entrypoint(manifest, target)
    for entrypoint in manifest.entrypoints:
        if entrypoint.kind == "workflow":
            return entrypoint
    raise PackageRuntimeError(f"Package {manifest.package_id} 缺少 workflow entrypoint")


def _annotate_deckspec(
    deck_spec: DeckSpec,
    manifest: PluginPackageManifest,
    *,
    binding_id: str | None = None,
) -> DeckSpec:
    payload = deck_spec.model_dump(mode="python")
    metadata = dict(payload.get("metadata") or {})
    metadata["workflow_runtime"] = {
        "package_id": manifest.package_id,
        "package_version": manifest.version,
        "capabilities": list(manifest.capabilities),
        "binding_id": binding_id,
    }
    if manifest.package_id == MINIMAX_PPTX_PLUGIN:
        metadata["workflow_runtime"]["mode"] = "minimax_plugin"
    payload["metadata"] = metadata
    return DeckSpec.model_validate(payload)