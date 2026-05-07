from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tasks import DEFAULT_USER_ID
from app.models.database import get_session
from app.models.tables import Task
from app.services.diagram_session_service import (
    get_diagram_session_by_version,
    get_latest_diagram_session,
    list_diagram_history,
    persist_diagram_session,
    snapshot_to_wire,
)
from app.services.diagram_visual_review_service import build_validation_payload, review_diagram_snapshot
from app.services.diagram_xml_validator import validate_and_fix_xml


router = APIRouter(prefix="/diagram-sessions", tags=["diagram-sessions"])


async def _get_task_or_404(session: AsyncSession, task_id: str) -> Task:
    result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .where(Task.user_id == DEFAULT_USER_ID)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/task/{task_id}")
async def get_task_diagram_session(task_id: str, session: AsyncSession = Depends(get_session)):
    await _get_task_or_404(session, task_id)
    snapshot = await get_latest_diagram_session(session, task_id)
    if snapshot is None:
        return {"exists": False, "task_id": task_id}
    return {"exists": True, "task_id": task_id, "session": snapshot_to_wire(snapshot)}


@router.get("/task/{task_id}/history")
async def get_task_diagram_history(task_id: str, session: AsyncSession = Depends(get_session)):
    await _get_task_or_404(session, task_id)
    history = await list_diagram_history(session, task_id, limit=20)
    return {
        "task_id": task_id,
        "history": [snapshot_to_wire(item) for item in history],
        "total": len(history),
    }


@router.post("/task/{task_id}/restore")
async def restore_task_diagram_session(
    task_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
):
    await _get_task_or_404(session, task_id)
    version = int(body.get("version") or 0)
    if version <= 0:
        raise HTTPException(status_code=400, detail="缺少要恢复的历史版本号")

    snapshot = await get_diagram_session_by_version(session, task_id, version)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="未找到指定的 diagram 历史版本")

    structural = validate_and_fix_xml(snapshot.xml, allow_fragment=False)
    if not structural.valid:
        raise HTTPException(status_code=409, detail=structural.error or "历史版本 XML 无效，无法恢复")

    review = review_diagram_snapshot(xml=structural.xml, svg=snapshot.svg, png=snapshot.png)
    validation = build_validation_payload(structural, review_result=review)
    restored = await persist_diagram_session(
        session,
        task_id=task_id,
        xml=structural.xml,
        source=f"diagram_restore:v{version}",
        svg=snapshot.svg,
        png=snapshot.png,
        validation=validation,
    )
    return {
        "task_id": task_id,
        "restored_from_version": version,
        "session": snapshot_to_wire(restored),
    }