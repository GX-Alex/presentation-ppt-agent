from __future__ import annotations

from typing import Any

from app.models.database import async_session
from app.services.diagram_runtime import emit_runtime_event, get_runtime_task_id
from app.services.diagram_session_service import get_latest_diagram_session, persist_diagram_session, snapshot_to_wire
from app.services.diagram_visual_review_service import build_validation_payload, next_retry_count, review_diagram_snapshot
from app.services.diagram_xml_validator import validate_and_fix_xml


TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "display_diagram",
        "description": "创建或整体替换当前任务的 draw.io 图。输入完整 XML 或 mxCell fragment。",
        "parameters": {
            "type": "object",
            "required": ["xml"],
            "properties": {
                "task_id": {"type": "string", "description": "可选。当前任务 ID；通常由运行时自动注入。"},
                "xml": {"type": "string", "description": "完整的 draw.io XML 或 mxCell fragment。"},
                "title": {"type": "string", "description": "可选。图的标题或摘要。"},
            },
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    task_id = str(params.get("task_id") or get_runtime_task_id() or "").strip()
    xml = str(params.get("xml") or "").strip()
    if not task_id:
        return {"error": "display_diagram 缺少 task_id"}
    if not xml:
        return {"error": "display_diagram 缺少 xml"}

    validation = validate_and_fix_xml(xml, allow_fragment=True)
    if not validation.valid:
        return {"error": validation.error or "draw.io XML 无效", "validation": validation.to_dict()}

    async with async_session() as session:
        latest = await get_latest_diagram_session(session, task_id)
        retry_count = next_retry_count(
            latest.validation if latest else None,
            previous_xml=latest.xml if latest else None,
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
            source="display_diagram",
            validation=reviewed_validation,
        )

    payload = snapshot_to_wire(snapshot)
    await emit_runtime_event({"type": "diagram_load", "session": payload, "reason": "display_diagram"})
    return {
        "ok": True,
        "diagram_session": payload,
        "validation": reviewed_validation,
        "retry_recommended": reviewed_validation.get("retry_recommended", False),
    }