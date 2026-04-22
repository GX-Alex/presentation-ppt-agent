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


class DeckPublishResponse(BaseModel):
    """发布产物响应"""
    project_id: str
    version: int
    html: str


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
    """导出 Web Deck 为 PPTX 可编辑格式（文本框幻灯片）"""
    from app.services import export_service

    project = await deck_state_store.get_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    pages = await deck_state_store.get_pages(session, project_id)
    ready_pages = [p for p in pages if p.html]

    if not ready_pages:
        raise HTTPException(status_code=400, detail="没有已完成的页面可导出，请等待所有页面生成完成")

    slides_data = [
        {
            "index": p.page_index,
            "html": p.html,
            "speaker_notes": "",
        }
        for p in sorted(ready_pages, key=lambda p: p.page_index)
    ]

    title = (project.manifest or {}).get("topic") or project.title or "Web Deck"

    try:
        file_path = await export_service.export_pptx_editable(slides_data, title)
    except Exception as exc:
        logger.exception("[WebDeck] PPTX 导出失败: %s", exc)
        raise HTTPException(status_code=500, detail="PPTX 导出失败，请稍后重试") from exc

    return {
        "success": True,
        "format": "pptx-editable",
        "file_path": file_path,
        "download_url": f"/static/{file_path}",
    }
