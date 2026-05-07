from __future__ import annotations

from typing import Any

from app.models.database import async_session
from app.services.diagram_runtime import emit_runtime_event, get_runtime_task_id
from app.services.diagram_session_service import get_latest_diagram_session, snapshot_to_wire


TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_current_diagram",
        "description": "读取当前任务的最新 draw.io 图，返回 XML、版本号和摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "可选。当前任务 ID；通常由运行时自动注入。"},
                "emit_to_workspace": {"type": "boolean", "description": "若为 true，则同时向前端工作区下发 diagram_load。"},
            },
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    task_id = str(params.get("task_id") or get_runtime_task_id() or "").strip()
    if not task_id:
        return {"error": "get_current_diagram 缺少 task_id"}

    async with async_session() as session:
        snapshot = await get_latest_diagram_session(session, task_id)

    if snapshot is None:
        return {"ok": True, "has_diagram": False}

    payload = snapshot_to_wire(snapshot)
    if params.get("emit_to_workspace"):
        await emit_runtime_event({"type": "diagram_load", "session": payload, "reason": "get_current_diagram"})
    return {"ok": True, "has_diagram": True, "diagram_session": payload}