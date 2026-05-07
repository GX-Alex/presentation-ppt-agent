from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.services.diagram_session_service import get_latest_diagram_session
from app.services.diagram_visual_review_service import build_validation_payload, review_diagram_snapshot
from app.services.diagram_xml_validator import validate_and_fix_xml


router = APIRouter(prefix="/diagram", tags=["diagram-validation"])


@router.post("/validate")
async def validate_diagram(
    body: dict[str, Any] = Body(default_factory=dict),
    session: AsyncSession = Depends(get_session),
):
    task_id = str(body.get("task_id") or "").strip()
    xml = str(body.get("xml") or "").strip()
    svg = str(body.get("svg") or "").strip() or None
    png = str(body.get("png") or "").strip() or None

    if not xml and task_id:
        snapshot = await get_latest_diagram_session(session, task_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="当前任务不存在 diagram session")
        xml = snapshot.xml
        svg = svg or snapshot.svg
        png = png or snapshot.png

    if not xml:
        raise HTTPException(status_code=400, detail="缺少待校验的 draw.io XML")

    structural = validate_and_fix_xml(xml, allow_fragment=False)
    if not structural.valid:
        return {
            "ok": False,
            "task_id": task_id or None,
            "xml": xml,
            "validation": build_validation_payload(structural),
        }

    review = review_diagram_snapshot(xml=structural.xml, svg=svg, png=png)
    validation = build_validation_payload(structural, review_result=review)
    return {
        "ok": True,
        "task_id": task_id or None,
        "xml": structural.xml,
        "validation": validation,
    }
