"""
regenerate_deck_page 工具 — 对已完成页面重跑完整生成流水线。

与 edit_deck_page（精准编辑现有 HTML）不同，此工具会调用 DeckDirector.retry_page()，
重新经历「证据注入 → LLM 生成 → 多轮审稿」全流程，适用于用户反馈内容不够丰富的场景。
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Awaitable, Callable

from app.core.llm_client import llm_timeout_override
from app.services.webdeck_runtime.director import DeckDirector

logger = logging.getLogger(__name__)
REGENERATE_DECK_PAGE_LLM_TIMEOUT_S = 240

_send_fn_var: contextvars.ContextVar[
    Callable[[dict], Awaitable[None]] | None
] = contextvars.ContextVar("regen_page_send_fn", default=None)


def set_runtime_context(send_fn: Callable[[dict], Awaitable[None]] | None) -> None:
    _send_fn_var.set(send_fn)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "regenerate_deck_page",
        "description": (
            "对 Web Deck 中某一已完成页面重新运行完整生成流水线（含证据重新注入、多轮审稿）。"
            "当用户反馈某页内容不够丰富、信息量不足、希望获得更好内容时使用。"
            "与 edit_deck_page（仅精准编辑现有 HTML 的文字/布局/样式）不同，"
            "此工具会从头生成该页，适合需要大幅改进内容质量的场景。"
            "不受页面当前状态限制，已完成的页面也可重新生成。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Web Deck 项目 ID（格式：UUID）",
                },
                "page_id": {
                    "type": "string",
                    "description": "需要重新生成的页面 ID（如 p14）",
                },
                "reason": {
                    "type": "string",
                    "description": "重新生成的原因（可选，用于日志记录）",
                },
            },
            "required": ["project_id", "page_id"],
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """调用 DeckDirector.retry_page() 重跑完整页面生成流水线。"""
    project_id = str(params.get("project_id", "")).strip()
    page_id = str(params.get("page_id", "")).strip()
    reason = str(params.get("reason", "")).strip()

    if not project_id:
        return {"error": "缺少 project_id 参数"}
    if not page_id:
        return {"error": "缺少 page_id 参数"}

    logger.info(
        "[regenerate_deck_page] project=%s page=%s reason=%s",
        project_id, page_id, reason or "未指定",
    )

    send_fn = _send_fn_var.get(None)

    async def _noop_send(msg: dict) -> None:
        pass

    director = DeckDirector(send_fn=send_fn or _noop_send)
    try:
        with llm_timeout_override(REGENERATE_DECK_PAGE_LLM_TIMEOUT_S):
            await director.retry_page(project_id=project_id, page_id=page_id)
        return {
            "result": f"✅ 页面 {page_id} 已重新生成完成",
            "project_id": project_id,
            "page_id": page_id,
        }
    except Exception as exc:
        logger.warning(
            "[regenerate_deck_page] project=%s page=%s error=%s",
            project_id, page_id, exc,
        )
        return {"error": f"重新生成失败: {exc}"}
