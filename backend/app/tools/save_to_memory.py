"""save_to_memory 工具。"""
from typing import Any

from app.models.database import async_session
from app.services.memory_service import capture_memory
from app.services.user_settings_service import DEFAULT_USER_ID, ensure_user

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "save_to_memory",
        "description": (
            "将值得长期记住的用户偏好、事实、指令或反馈写入长期记忆。"
            "仅用于稳定信息，不要保存一次性任务细节。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["preference", "fact", "instruction", "feedback"],
                    "description": "记忆分类",
                },
                "content": {
                    "type": "string",
                    "description": "要保存的记忆内容，应简洁明确",
                },
                "confidence": {
                    "type": "number",
                    "description": "记忆置信度，范围 0-1",
                    "default": 0.8,
                },
            },
            "required": ["category", "content"],
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    category = str(params.get("category") or "").strip()
    content = str(params.get("content") or "").strip()
    confidence = float(params.get("confidence", 0.8) or 0.8)

    if category not in {"preference", "fact", "instruction", "feedback"}:
        return {"success": False, "error": "无效的记忆分类"}
    if not content:
        return {"success": False, "error": "记忆内容不能为空"}

    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        result = await capture_memory(
            session=session,
            user_id=DEFAULT_USER_ID,
            category=category,
            content=content,
            source="agent_inferred",
            confidence=max(0.0, min(confidence, 1.0)),
        )

    return {
        "success": True,
        "memory_id": result.get("id"),
        "action": result.get("action"),
        "category": category,
        "content": content,
    }