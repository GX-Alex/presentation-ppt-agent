"""
retry_failed_deck_pages 工具 — 重试 Web Deck 项目中所有失败页面。
"""
from __future__ import annotations

import logging
from typing import Any

from app.models.database import async_session
from app.services.webdeck_runtime.state_store import deck_state_store
from app.services.webdeck_runtime.director import DeckDirector

logger = logging.getLogger(__name__)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "retry_failed_deck_pages",
        "description": (
            "重试 Web Deck 项目中所有状态为失败的页面。"
            "当用户要求重试、重新生成失败页面或修复 Web Deck 时使用。"
            "会返回每个页面的重试结果摘要。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Web Deck 项目 ID（格式：UUID，例如 53ce5422-2506-4dd7-af1a-f30e78da2e2f）",
                },
            },
            "required": ["project_id"],
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """列出失败页面并逐一调用 DeckDirector.retry_page()。"""
    project_id = str(params.get("project_id", "")).strip()
    if not project_id:
        return {"error": "缺少 project_id 参数"}

    async with async_session() as session:
        pages = await deck_state_store.get_pages(session, project_id)

    failed_pages = [p for p in pages if p.status == "failed"]
    if not failed_pages:
        return {"result": "✅ 没有失败的页面，所有页面均已完成。"}

    # Sort by page index so dependency pages are retried first
    failed_pages.sort(key=lambda p: getattr(p, "page_index", 0))

    page_titles = [getattr(p, "title", None) or p.page_id for p in failed_pages]
    logger.info(
        "[retry_failed_deck_pages] project=%s retrying %d pages: %s",
        project_id,
        len(failed_pages),
        page_titles,
    )

    async def _noop_send(msg: dict) -> None:
        pass

    director = DeckDirector(send_fn=_noop_send)

    retry_results: list[str] = []
    for page in failed_pages:
        page_label = getattr(page, "title", None) or page.page_id
        try:
            await director.retry_page(project_id=project_id, page_id=page.page_id)
            retry_results.append(f"✅ {page_label}")
        except Exception as exc:
            logger.warning("[retry_failed_deck_pages] page=%s error=%s", page.page_id, exc)
            retry_results.append(f"❌ {page_label}: {exc}")

    summary = "\n".join(retry_results)
    return {"result": f"已重试 {len(failed_pages)} 个失败页面：\n{summary}"}
