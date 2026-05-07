from __future__ import annotations

from typing import Any

from app.models.database import async_session
from app.services.diagram_runtime import emit_runtime_event, get_runtime_task_id
from app.services.diagram_session_service import get_latest_diagram_session, persist_diagram_session, snapshot_to_wire
from app.services.diagram_visual_review_service import build_validation_payload, next_retry_count, review_diagram_snapshot
from app.services.diagram_xml_validator import append_cells_to_xml


TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "append_diagram",
        "description": "向当前 draw.io 图追加新的 mxCell fragment，用于续写或补充复杂图。",
        "parameters": {
            "type": "object",
            "required": ["fragment"],
            "properties": {
                "task_id": {"type": "string", "description": "可选。当前任务 ID；通常由运行时自动注入。"},
                "fragment": {"type": "string", "description": "要追加的 mxCell fragment 或 draw.io XML 片段。"},
            },
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    task_id = str(params.get("task_id") or get_runtime_task_id() or "").strip()
    fragment = str(params.get("fragment") or "").strip()
    if not task_id:
        return {"error": "append_diagram 缺少 task_id"}
    if not fragment:
        return {"error": "append_diagram 缺少 fragment"}

    async with async_session() as session:
        latest = await get_latest_diagram_session(session, task_id)
        if latest is None:
            return {"error": "当前任务还没有 diagram session，请先调用 display_diagram"}

        validation = append_cells_to_xml(latest.xml, fragment)
        if not validation.valid:
            return {"error": validation.error or "追加图节点失败", "validation": validation.to_dict()}

        retry_count = next_retry_count(
            latest.validation,
            previous_xml=latest.xml,
            current_xml=validation.xml,
        )
        review = review_diagram_snapshot(xml=validation.xml)
        reviewed_validation = build_validation_payload(
            validation,
            review_result=review,
            retry_count=retry_count,
        )

        snapshot = await persist_diagram_session(
            session,
            task_id=task_id,
            xml=validation.xml,
            source="append_diagram",
            validation=reviewed_validation,
        )

    payload = snapshot_to_wire(snapshot)
    await emit_runtime_event({"type": "diagram_load", "session": payload, "reason": "append_diagram"})
    return {
        "ok": True,
        "diagram_session": payload,
        "validation": reviewed_validation,
        "retry_recommended": reviewed_validation.get("retry_recommended", False),
    }