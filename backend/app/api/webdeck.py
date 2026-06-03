"""
Web Deck REST API — Deck 项目管理接口。
对齐 high.md §8.1: ws/chat 保留通用对话，新增 webdeck 相关 API。
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.services.webdeck_runtime.state_store import deck_state_store
from app.services.webdeck_runtime.reviewer import DeckReviewer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webdeck", tags=["webdeck"])


# ────────────── 请求 / 响应模型 ──────────────

class DeckProjectResponse(BaseModel):
    """Deck 项目摘要响应"""
    project_id: str
    title: str | None
    status: str
    version: int
    total_pages: int
    completed_pages: int
    failed_pages: int
    pages: list[dict[str, Any]]


class DeckManifestResponse(BaseModel):
    """DeckManifest 响应"""
    project_id: str
    manifest: dict[str, Any] | None


class DeckPageResponse(BaseModel):
    """单页响应"""
    page_id: str
    page_index: int
    title: str | None
    page_kind: str
    status: str
    html: str | None
    page_bundle: dict[str, Any] | None = None


class DeckPublishResponse(BaseModel):
    """发布产物响应"""
    project_id: str
    version: int
    html: str


class DeckPageSaveRequest(BaseModel):
    """页面保存请求"""
    html: str
    source: str = "manual"
    change_summary: str | None = None
    page_bundle: dict[str, Any] | None = None


class DeckPageRollbackRequest(BaseModel):
    """页面回滚请求"""
    change_summary: str | None = None


class DeckPageVersionResponse(BaseModel):
    """页面版本响应"""
    version: int
    source: str
    change_summary: str | None
    created_at: str | None


class DeckPageSaveResponse(BaseModel):
    """页面保存结果响应"""
    project_id: str
    page_id: str
    page_version: int
    publish_version: int
    html: str
    full_html: str
    page_bundle: dict[str, Any] | None = None


# ────────────── 接口 ──────────────

@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeckProjectResponse:
    """获取 Deck 项目状态汇总"""
    summary = await deck_state_store.get_project_summary(session, project_id)
    if not summary:
        raise HTTPException(status_code=404, detail="项目不存在")

    return DeckProjectResponse(**summary)


@router.get("/projects/{project_id}/manifest")
async def get_manifest(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeckManifestResponse:
    """获取 DeckManifest"""
    project = await deck_state_store.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    return DeckManifestResponse(
        project_id=project.id,
        manifest=project.manifest,
    )


@router.get("/projects/{project_id}/pages")
async def get_pages(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[DeckPageResponse]:
    """获取项目的所有页面"""
    pages = await deck_state_store.get_pages(session, project_id)
    return [
        DeckPageResponse(
            page_id=p.page_id,
            page_index=p.page_index,
            title=p.title,
            page_kind=p.page_kind or "content",
            status=p.status or "pending",
            html=p.html,
            page_bundle=p.page_bundle,
        )
        for p in pages
    ]


@router.get("/projects/{project_id}/pages/{page_id}")
async def get_page(
    project_id: str,
    page_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeckPageResponse:
    """获取单页详情（包含 HTML）"""
    pages = await deck_state_store.get_pages(session, project_id)
    target = None
    for p in pages:
        if p.page_id == page_id:
            target = p
            break

    if not target:
        raise HTTPException(status_code=404, detail="页面不存在")

    return DeckPageResponse(
        page_id=target.page_id,
        page_index=target.page_index,
        title=target.title,
        page_kind=target.page_kind or "content",
        status=target.status or "pending",
        html=target.html,
        page_bundle=target.page_bundle,
    )


@router.get("/projects/{project_id}/pages/{page_id}/versions")
async def get_page_versions(
    project_id: str,
    page_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[DeckPageVersionResponse]:
    """获取单页历史版本（倒序）。"""
    page = await deck_state_store.get_page_by_page_id(session, project_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    versions = await deck_state_store.list_page_versions(session, page.id, limit=50)
    return [
        DeckPageVersionResponse(
            version=item.version,
            source=item.source,
            change_summary=item.change_summary,
            created_at=item.created_at.isoformat() if item.created_at else None,
        )
        for item in versions
    ]


@router.post("/projects/{project_id}/pages/{page_id}/save")
async def save_page(
    project_id: str,
    page_id: str,
    body: DeckPageSaveRequest,
    session: AsyncSession = Depends(get_session),
) -> DeckPageSaveResponse:
    """保存单页手工编辑并触发整稿重发布。"""
    from app.services.webdeck_runtime.contracts import PageStatus
    from app.services.webdeck_runtime.editor_bundle import build_page_bundle_payload
    from app.services.webdeck_runtime.publish_service import republish_project

    page = await deck_state_store.get_page_by_page_id(session, project_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    html = (body.html or "").strip()
    if not html:
        raise HTTPException(status_code=400, detail="页面 HTML 不能为空")

    source = (body.source or "manual").strip()[:20] or "manual"
    page_bundle = build_page_bundle_payload(
        page_id=page_id,
        html=html,
        base_payload=body.page_bundle or getattr(page, "page_bundle", None) or {},
    )
    await deck_state_store.save_page_html(
        session=session,
        page_db_id=page.id,
        html=html,
        bundle=page_bundle,
        status=PageStatus.COMPLETED.value,
    )

    page_version = await deck_state_store.create_page_version(
        session=session,
        project_id=project_id,
        page_db_id=page.id,
        html=html,
        source=source,
        change_summary=body.change_summary,
        metadata={"source": source, "mode": "manual_save"},
    )

    publish, full_html = await republish_project(
        session=session,
        project_id=project_id,
        metadata={"source": source, "page_id": page_id},
    )

    return DeckPageSaveResponse(
        project_id=project_id,
        page_id=page_id,
        page_version=page_version.version,
        publish_version=publish.version,
        html=html,
        full_html=full_html,
        page_bundle=page_bundle,
    )


@router.post("/projects/{project_id}/pages/{page_id}/versions/{version}/rollback")
async def rollback_page_version(
    project_id: str,
    page_id: str,
    version: int,
    body: DeckPageRollbackRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> DeckPageSaveResponse:
    """回滚页面到指定历史版本，并写入新的回滚版本快照。"""
    from app.services.webdeck_runtime.contracts import PageStatus
    from app.services.webdeck_runtime.editor_bundle import build_page_bundle_payload
    from app.services.webdeck_runtime.publish_service import republish_project

    page = await deck_state_store.get_page_by_page_id(session, project_id, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="页面不存在")

    target_version = await deck_state_store.get_page_version_by_number(
        session=session,
        page_db_id=page.id,
        version=version,
    )
    if not target_version:
        raise HTTPException(status_code=404, detail="目标版本不存在")

    rollback_html = target_version.html or ""
    if not rollback_html.strip():
        raise HTTPException(status_code=400, detail="目标版本内容为空，无法回滚")

    page_bundle = build_page_bundle_payload(
        page_id=page_id,
        html=rollback_html,
        base_payload=getattr(page, "page_bundle", None) or {},
    )
    await deck_state_store.save_page_html(
        session=session,
        page_db_id=page.id,
        html=rollback_html,
        bundle=page_bundle,
        status=PageStatus.COMPLETED.value,
    )

    change_summary = (body.change_summary if body else None) or f"回滚到版本 v{version}"
    rollback_snapshot = await deck_state_store.create_page_version(
        session=session,
        project_id=project_id,
        page_db_id=page.id,
        html=rollback_html,
        source="rollback",
        change_summary=change_summary,
        metadata={"rollback_from": version},
    )

    publish, full_html = await republish_project(
        session=session,
        project_id=project_id,
        metadata={"source": "rollback", "page_id": page_id, "version": version},
    )

    return DeckPageSaveResponse(
        project_id=project_id,
        page_id=page_id,
        page_version=rollback_snapshot.version,
        publish_version=publish.version,
        html=rollback_html,
        full_html=full_html,
        page_bundle=page_bundle,
    )


@router.post("/projects/{project_id}/publish")
async def publish_project(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeckPublishResponse:
    """强制重新组装并发布整稿，返回最新 full_html。"""
    from app.services.webdeck_runtime.publish_service import republish_project

    try:
        publish, full_html = await republish_project(
            session=session,
            project_id=project_id,
            metadata={"source": "manual_publish"},
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "不存在" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return DeckPublishResponse(
        project_id=project_id,
        version=publish.version,
        html=full_html,
    )


@router.get("/projects/{project_id}/html")
async def get_full_deck_html(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取完整 Deck HTML（最新发布版本）"""
    from sqlalchemy import select
    from app.models.tables import DeckPublish

    result = await session.execute(
        select(DeckPublish)
        .where(DeckPublish.project_id == project_id)
        .order_by(DeckPublish.version.desc())
    )
    pub = result.scalars().first()

    if not pub or not pub.full_html:
        raise HTTPException(status_code=404, detail="尚未发布")

    return DeckPublishResponse(
        project_id=project_id,
        version=pub.version,
        html=pub.full_html,
    )


@router.get("/projects/{project_id}/summary")
async def get_project_runtime_summary(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """获取项目运行时状态汇总 — 供前端状态面板消费"""
    summary = await deck_state_store.get_project_summary(session, project_id)
    if not summary:
        raise HTTPException(status_code=404, detail="项目不存在")
    return summary


@router.get("/task/{task_id}")
async def get_project_by_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """根据 task_id 获取最新的 Deck 项目"""
    project = await deck_state_store.get_project_by_task(session, task_id)
    if not project:
        return {}

    summary = await deck_state_store.get_project_summary(session, project.id)
    return summary


@router.get("/projects/{project_id}/reviews")
async def get_reviews(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """获取项目所有审稿报告"""
    reports = await deck_state_store.get_reviews(session, project_id)
    return [
        {
            "level": r.level,
            "targetId": r.page_id or project_id,
            "passed": r.passed,
            "score": r.score,
            "issues": r.issues or [],
            "suggestions": r.suggestions or [],
        }
        for r in reports
    ]


@router.post("/projects/{project_id}/review")
async def review_deck(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """触发 Deck 级审稿"""
    reviewer = DeckReviewer()
    report = await reviewer.review_deck(session, project_id)
    return report.to_dict()


@router.post("/projects/{project_id}/export/pptx")
async def export_deck_pptx(
    project_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """导出 Web Deck 为 PPTX 可编辑格式（native DrawingML 形状/文本）。"""
    from app.services.webdeck_runtime.native_pptx_export_service import (
        export_webdeck_native_pptx,
    )
    from app.services.webdeck_runtime.artifact_composer import DeckComposer
    from app.services.webdeck_runtime.contracts import DeckManifest

    project = await deck_state_store.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    pages = await deck_state_store.get_pages(session, project_id)
    ready_pages = [p for p in pages if p.html]

    if not ready_pages:
        still_running = any(p.status not in ("completed", "failed") for p in pages)
        detail = (
            "没有已完成的页面可导出，请等待页面生成完成"
            if still_running
            else "所有页面均已失败，无法导出，请先重试失败页面后再导出"
        )
        raise HTTPException(status_code=400, detail=detail)

    title = (project.manifest or {}).get("topic") or project.title or "Web Deck"
    manifest = DeckManifest.from_dict(project.manifest or {})

    try:
        # 仅用有 HTML 的页面组装导出，跳过空页避免导出空白幻灯片
        full_html = DeckComposer().compose(manifest, ready_pages)
        file_path = await export_webdeck_native_pptx(full_html, title)
    except Exception as exc:
        logger.exception("[WebDeck] PPTX 导出失败: %s", exc)
        raise HTTPException(status_code=500, detail="PPTX 导出失败，请稍后重试") from exc

    return {
        "success": True,
        "format": "pptx-native",
        "file_path": file_path,
        "download_url": f"/static/{file_path}",
        "exported_pages": len(ready_pages),
        "total_pages": len(pages),
    }
