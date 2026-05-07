from __future__ import annotations

from typing import Any


_LIBRARIES: dict[str, dict[str, Any]] = {
    "generic": {
        "description": "通用流程图和架构图节点，适合业务流程、系统分层和数据流。",
        "keywords": ["process", "decision", "database", "service", "queue", "api"],
        "guidance": "优先使用标准矩形、菱形、数据库和圆角矩形；不要为简单图引入复杂图标库。",
    },
    "cloud": {
        "description": "云架构场景常见组件命名建议。当前版本返回语义约束，不直接注入第三方私有 shape。",
        "keywords": ["aws", "azure", "gcp", "load balancer", "vpc", "bucket"],
        "guidance": "先用通用节点表达职责，再在 label 中写明云组件名称，避免硬猜 draw.io 专有 shape 名。",
    },
}


TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_shape_library",
        "description": "获取 draw.io 图形库使用建议，帮助模型选择合适的节点和图标表达。",
        "parameters": {
            "type": "object",
            "properties": {
                "library": {"type": "string", "description": "可选。generic 或 cloud。默认 generic。"},
            },
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    library = str(params.get("library") or "generic").strip().lower()
    payload = _LIBRARIES.get(library) or _LIBRARIES["generic"]
    return {"ok": True, "library": library if library in _LIBRARIES else "generic", "payload": payload}