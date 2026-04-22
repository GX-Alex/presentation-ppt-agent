"""search_memory 工具。"""
from typing import Any

from app.models.database import async_session
from app.services.memory_service import search_memories
from app.services.user_settings_service import DEFAULT_USER_ID, ensure_user

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "搜索与当前问题相关的长期记忆，用于跨任务延续用户偏好和背景。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索记忆的查询语句",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    query = str(params.get("query") or "").strip()
    top_k = int(params.get("top_k", 5) or 5)
    if not query:
        return {"success": False, "error": "query 不能为空"}

    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        results = await search_memories(
            session=session,
            user_id=DEFAULT_USER_ID,
            query=query,
            top_k=max(1, min(top_k, 10)),
            threshold=0.3,
        )

    return {
        "success": True,
        "results": results,
        "total": len(results),
    }