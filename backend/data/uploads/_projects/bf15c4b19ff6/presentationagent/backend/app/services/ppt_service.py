"""
PPT 服务 — 演示文稿持久化与管理。
负责 Presentation、Slide、SlideVersion 的 CRUD 和完整 HTML 组装。
Sprint 3 新增: 单页更新 + 版本控制（get_slide_versions / revert_slide_version）。
"""
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.schemas.deck_spec import DeckSpec
from app.models.tables import Presentation, Slide, SlideVersion
from app.services.deckspec_preview_service import render_deck_to_html_preview
from app.services.native_renderer_service import build_deckspec_from_slides
from app.services.theme_manager import get_theme

logger = logging.getLogger(__name__)


async def create_presentation(
    session: AsyncSession,
    task_id: str,
    presentation_id: str,
    title: str,
    theme_id: str,
    outline: list[dict[str, Any]],
    source_docs: dict[str, Any] | None = None,
) -> Presentation:
    """
    创建演示文稿记录并持久化大纲。

    Args:
        session: 数据库会话
        task_id: 关联的任务 ID
        presentation_id: 预生成的 Presentation ID
        title: 演示文稿标题
        theme_id: 主题 ID
        outline: 大纲 JSON 数据

    Returns:
        创建的 Presentation ORM 对象
    """
    theme = get_theme(theme_id)

    pres = Presentation(
        id=presentation_id,
        task_id=task_id,
        title=title,
        theme={"id": theme_id, "name": theme["name"]},
        outline=outline,
        source_docs=source_docs,
        created_at=datetime.utcnow(),
    )
    session.add(pres)
    await session.commit()

    logger.info(f"[PPTService] 创建演示文稿: id={presentation_id}, title={title}")
    return pres


async def save_slides(
    session: AsyncSession,
    presentation_id: str,
    slides_data: list[dict[str, Any]],
    refresh_canonical: bool = True,
) -> list[Slide]:
    """
    批量保存幻灯片数据。

    Args:
        session: 数据库会话
        presentation_id: 演示文稿 ID
        slides_data: [{index, html, speaker_notes}]

    Returns:
        保存的 Slide ORM 对象列表
    """
    saved_slides = []

    for slide_data in slides_data:
        slide = Slide(
            id=str(uuid.uuid4()),
            presentation_id=presentation_id,
            index=slide_data["index"],
            type=slide_data.get("type", "content"),
            html=slide_data["html"],
            speaker_notes=slide_data.get("speaker_notes", ""),
            version=1,
            created_at=datetime.utcnow(),
        )
        session.add(slide)

        # 同时创建版本记录（V1）
        version = SlideVersion(
            id=str(uuid.uuid4()),
            slide_id=slide.id,
            version=1,
            html=slide_data["html"],
            source="ai",
            created_at=datetime.utcnow(),
        )
        session.add(version)

        saved_slides.append(slide)

    await session.commit()
    if refresh_canonical:
        await refresh_canonical_deckspec(session, presentation_id, source="slide_save")
    logger.info(f"[PPTService] 保存 {len(saved_slides)} 页幻灯片: pres_id={presentation_id}")
    return saved_slides


async def get_presentation(
    session: AsyncSession,
    presentation_id: str,
) -> dict[str, Any] | None:
    """
    获取完整的演示文稿数据（含所有幻灯片）。

    Returns:
        {id, title, theme, outline, slides: [{index, html, speaker_notes, version}]} | None
    """
    stmt = (
        select(Presentation)
        .where(Presentation.id == presentation_id)
        .options(selectinload(Presentation.slides))
    )
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()

    if not pres:
        return None

    # 按 index 排序幻灯片
    sorted_slides = sorted(pres.slides, key=lambda s: s.index)
    slide_metadata = _get_slide_metadata_map(pres.source_docs)
    outline = _merge_outline_metadata(pres.outline or [], slide_metadata)

    return {
        "id": pres.id,
        "task_id": pres.task_id,
        "title": pres.title,
        "theme": pres.theme,
        "outline": outline,
        "source_docs": pres.source_docs,
        "slides": [
            {
                "id": s.id,
                "index": s.index,
                "type": s.type,
                "html": s.html,
                "metadata": slide_metadata.get(str(s.index), {}),
                "speaker_notes": s.speaker_notes,
                "version": s.version,
            }
            for s in sorted_slides
        ],
        "created_at": pres.created_at.isoformat() if pres.created_at else None,
        "updated_at": pres.updated_at.isoformat() if pres.updated_at else None,
    }


async def get_presentation_by_task(
    session: AsyncSession,
    task_id: str,
) -> dict[str, Any] | None:
    """通过 task_id 获取演示文稿。"""
    stmt = (
        select(Presentation)
        .where(Presentation.task_id == task_id)
        .options(selectinload(Presentation.slides))
        .order_by(Presentation.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()

    if not pres:
        return None

    sorted_slides = sorted(pres.slides, key=lambda s: s.index)
    slide_metadata = _get_slide_metadata_map(pres.source_docs)
    outline = _merge_outline_metadata(pres.outline or [], slide_metadata)

    return {
        "id": pres.id,
        "task_id": pres.task_id,
        "title": pres.title,
        "theme": pres.theme,
        "outline": outline,
        "source_docs": pres.source_docs,
        "slides": [
            {
                "id": s.id,
                "index": s.index,
                "type": s.type,
                "html": s.html,
                "metadata": slide_metadata.get(str(s.index), {}),
                "speaker_notes": s.speaker_notes,
                "version": s.version,
            }
            for s in sorted_slides
        ],
        "created_at": pres.created_at.isoformat() if pres.created_at else None,
        "updated_at": pres.updated_at.isoformat() if pres.updated_at else None,
    }


async def update_outline(
    session: AsyncSession,
    presentation_id: str,
    outline: list[dict[str, Any]],
) -> bool:
    """更新演示文稿大纲。"""
    stmt = select(Presentation).where(Presentation.id == presentation_id)
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()

    if not pres:
        return False

    pres.outline = outline
    pres.updated_at = datetime.utcnow()
    await session.commit()
    return True


async def get_latest_presentation_record_by_task(
    session: AsyncSession,
    task_id: str,
) -> Presentation | None:
    stmt = (
        select(Presentation)
        .where(Presentation.task_id == task_id)
        .order_by(Presentation.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_source_docs(
    session: AsyncSession,
    presentation_id: str,
    source_docs: dict[str, Any],
) -> bool:
    stmt = select(Presentation).where(Presentation.id == presentation_id)
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()

    if not pres:
        return False

    pres.source_docs = source_docs
    pres.updated_at = datetime.utcnow()
    await session.commit()
    return True


def _get_slide_metadata_map(source_docs: dict[str, Any] | None) -> dict[str, Any]:
    raw = (source_docs or {}).get("slide_metadata")
    return raw if isinstance(raw, dict) else {}


def _merge_outline_metadata(outline: list[dict[str, Any]], slide_metadata: dict[str, Any]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in outline:
        if not isinstance(item, dict):
            continue
        metadata = slide_metadata.get(str(item.get("index") or 0), {})
        merged.append({**item, "metadata": metadata})
    return merged


async def build_full_html(
    session: AsyncSession,
    presentation_id: str,
) -> str | None:
    """
    组装完整的 reveal.js HTML 页面。

    Returns:
        完整 HTML 字符串 | None
    """
    deck_spec = await get_or_build_canonical_deckspec(session, presentation_id)
    if deck_spec is None:
        return None
    html, _meta = render_deck_to_html_preview(deck_spec)
    return html


async def get_canonical_deckspec(
    session: AsyncSession,
    presentation_id: str,
) -> DeckSpec | None:
    stmt = select(Presentation).where(Presentation.id == presentation_id)
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()
    if not pres:
        return None

    source_docs = pres.source_docs or {}
    payload = source_docs.get("canonical_deckspec")
    if not payload:
        return None
    return DeckSpec.model_validate(payload)


async def persist_canonical_deckspec(
    session: AsyncSession,
    presentation_id: str,
    deck_spec: DeckSpec,
    *,
    source: str,
    metadata: dict[str, Any] | None = None,
) -> DeckSpec | None:
    stmt = select(Presentation).where(Presentation.id == presentation_id)
    result = await session.execute(stmt)
    pres = result.scalar_one_or_none()
    if not pres:
        return None

    source_docs = dict(pres.source_docs or {})
    source_docs["canonical_deckspec"] = deck_spec.model_dump(mode="python")
    source_docs["canonical_source"] = source
    source_docs["canonical_updated_at"] = datetime.utcnow().isoformat()
    if metadata:
        source_docs["canonical_metadata"] = metadata
    pres.source_docs = source_docs
    pres.updated_at = datetime.utcnow()
    await session.commit()
    return deck_spec


async def get_or_build_canonical_deckspec(
    session: AsyncSession,
    presentation_id: str,
) -> DeckSpec | None:
    existing = await get_canonical_deckspec(session, presentation_id)
    if existing is not None:
        return existing
    return await refresh_canonical_deckspec(session, presentation_id, source="presentation_read")


async def refresh_canonical_deckspec(
    session: AsyncSession,
    presentation_id: str,
    *,
    source: str,
) -> DeckSpec | None:
    pres_data = await get_presentation(session, presentation_id)
    if not pres_data:
        return None

    title = pres_data.get("title") or "演示文稿"
    theme_id = pres_data.get("theme", {}).get("id", "tech_dark")
    slides = pres_data.get("slides") or []
    if not slides:
        return None

    deck_spec = build_deckspec_from_slides(
        presentation_id=presentation_id,
        title=title,
        theme_id=theme_id,
        slides_data=slides,
        artifact_mode="dual_render",
    )
    await persist_canonical_deckspec(
        session,
        presentation_id,
        deck_spec,
        source=source,
        metadata={"slide_count": len(slides), "theme_id": theme_id},
    )
    return deck_spec


# ═══════════════  Sprint 3: 单页更新 + 版本控制  ═══════════════

