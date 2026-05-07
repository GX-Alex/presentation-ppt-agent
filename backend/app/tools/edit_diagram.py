from __future__ import annotations

from typing import Any

from app.models.database import async_session
from app.services.diagram_operations import apply_diagram_operations
from app.services.diagram_runtime import emit_runtime_event, get_runtime_task_id
from app.services.diagram_session_service import get_latest_diagram_session, persist_diagram_session, snapshot_to_wire
from app.services.diagram_visual_review_service import build_validation_payload, next_retry_count, review_diagram_snapshot
from app.services.diagram_xml_validator import validate_and_fix_xml


TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_diagram",
        "description": "对当前 draw.io 图做局部编辑。支持 add、update、delete 三类操作。",
        "parameters": {
            "type": "object",
            "required": ["operations"],
            "properties": {
                "task_id": {"type": "string", "description": "可选。当前任务 ID；通常由运行时自动注入。"},
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["action"],
                        "properties": {
                            "action": {"type": "string", "enum": ["add", "update", "delete"]},
                            "cell_id": {"type": "string"},
                            "parent_id": {"type": "string"},
                            "cell_xml": {"type": "string"},
                            "cell": {"type": "object"},
                            "value": {"type": "string"},
                            "style": {"type": "string"},
                            "geometry": {"type": "object"},
                            "attributes": {"type": "object"},
                        },
                    },
                },
            },
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    task_id = str(params.get("task_id") or get_runtime_task_id() or "").strip()
    if not task_id:
        return {"error": "edit_diagram 缺少 task_id"}

    operations = params.get("operations")
    if not isinstance(operations, list) or not operations:
        return {"error": "edit_diagram 缺少 operations"}

    async with async_session() as session:
        latest = await get_latest_diagram_session(session, task_id)
        if latest is None:
            return {"error": "当前任务还没有 diagram session，请先调用 display_diagram"}

        apply_result = apply_diagram_operations(latest.xml, operations)
        if not apply_result.success:
            return {"error": apply_result.errors[0], "apply_result": apply_result.to_dict()}

        structural = validate_and_fix_xml(apply_result.xml, allow_fragment=False)
        if not structural.valid:
            return {"error": structural.error or "编辑后的 draw.io XML 无效", "validation": structural.to_dict()}

        retry_count = next_retry_count(
            latest.validation,
            previous_xml=latest.xml,
            current_xml=structural.xml,
        )
        review = review_diagram_snapshot(xml=structural.xml)
        reviewed_validation = build_validation_payload(
            {
                **structural.to_dict(),
                "warnings": [*(structural.warnings or []), *(apply_result.warnings or [])],
            },
            review_result=review,
            retry_count=retry_count,
        )

        snapshot = await persist_diagram_session(
            session,
            task_id=task_id,
            xml=structural.xml,
            source="edit_diagram",
            validation=reviewed_validation,
        )

    payload = snapshot_to_wire(snapshot)
    await emit_runtime_event({"type": "diagram_load", "session": payload, "reason": "edit_diagram"})
    return {
        "ok": True,
        "diagram_session": payload,
        "apply_result": apply_result.to_dict(),
        "validation": reviewed_validation,
        "retry_recommended": reviewed_validation.get("retry_recommended", False),
    }