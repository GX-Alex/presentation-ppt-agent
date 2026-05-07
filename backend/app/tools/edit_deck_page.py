"""
edit_deck_page 工具 — 使用自然语言修改 Web Deck 中的单页。

与已淘汰的 edit_slide 不同，本工具专为 Web Deck 设计，操作 DeckPage 数据。
current_html 由中间件（PPTEventMiddleware.on_tool_start）从数据库自动注入，
LLM 无需在调用时传入 current_html。
"""
import json
import logging
import re
from typing import Any

from app.core.llm_client import chat as llm_chat

logger = logging.getLogger(__name__)
EDIT_DECK_PAGE_TIMEOUT_S = 240

# ──────────── Tool 定义 ────────────
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_deck_page",
        "description": (
            "修改 Web Deck 演示中的指定页面。"
            "根据自然语言指令对该页面 HTML 进行精准编辑，支持文字修改、布局调整、样式更改等。"
            "仅适用于通过 Web Deck 流程生成的演示文稿（不适用于旧版 PPT）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Web Deck 项目 ID（执行上下文中应有此信息）",
                },
                "page_id": {
                    "type": "string",
                    "description": "要修改的页面 page_id（执行上下文中应有此信息）",
                },
                "instruction": {
                    "type": "string",
                    "description": '用户的修改指令，如"把标题改为xxx"、"增加要点"、"调整配色"等',
                },
            },
            "required": ["project_id", "page_id", "instruction"],
        },
    },
}

EDIT_SYSTEM_PROMPT = """你是一位专业的 Web Deck 页面编辑设计师。
你的任务是根据用户的修改指令，优化给定的 HTML 幻灯片页面。

## 编辑原则
1. **保持设计品质** — 修改后的视觉质量应不低于修改前
2. **精确修改** — 只改用户要求的部分，不破坏现有设计
3. **完整输出** — 输出完整的 <section> 标签，包含所有内容
4. **样式一致** — 使用内联 style 确保修改效果可控
5. **16:9 画布约束** — 确保所有内容适配 16:9 单页展示，不允许出现纵向溢出

## 输出格式（严格 JSON）
{
    "html": "<section>...修改后的完整 HTML...</section>",
    "changes_summary": "本次修改的简要描述"
}

只输出 JSON，不要附加任何解释文字。"""


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行 Web Deck 页面编辑。

    current_html 由 PPTEventMiddleware.on_tool_start 从数据库注入，
    LLM 调用时无需提供此参数。

    Args:
        params: {project_id, page_id, instruction, current_html (injected by middleware)}

    Returns:
        {project_id, page_id, html, changes_summary} 或 {error: "..."}
    """
    project_id = params.get("project_id", "")
    page_id = params.get("page_id", "")
    instruction = params.get("instruction", "")
    current_html = params.get("current_html", "")

    if not current_html:
        logger.error(f"[EditDeckPage] 未注入 current_html: project={project_id}, page={page_id}")
        return {"error": "无法获取当前页面 HTML 内容，请确认项目 ID 和页面 ID 正确"}

    logger.info(
        f"[EditDeckPage] 开始编辑: project={project_id}, page={page_id}, "
        f"instruction={instruction[:60]}..."
    )

    try:
        user_message = (
            f"当前页面 HTML:\n```html\n{current_html}\n```\n\n"
            f"修改指令: {instruction}"
        )

        response = await llm_chat(
            system=EDIT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
            tools=None,
            task_id=f"edit_deck_{project_id}_{page_id}",
            request_timeout_s=EDIT_DECK_PAGE_TIMEOUT_S,
        )

        raw = response.content.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            section_match = re.search(r"(<section[\s\S]*?</section>)", raw)
            if section_match:
                result = {
                    "html": section_match.group(1),
                    "changes_summary": "已根据指令修改页面",
                }
            else:
                logger.error(f"[EditDeckPage] 无法解析 LLM 响应: {raw[:200]}")
                return {"error": f"无法解析修改结果: {raw[:200]}"}

        new_html = result.get("html", "")
        if not new_html:
            return {"error": "修改结果为空"}

        logger.info(
            f"[EditDeckPage] ✅ 编辑完成: page={page_id}, "
            f"html_len={len(new_html)}, summary={result.get('changes_summary', '')}"
        )

        return {
            "project_id": project_id,
            "page_id": page_id,
            "html": new_html,
            "changes_summary": result.get("changes_summary", "已修改页面"),
        }

    except Exception as e:
        logger.exception(f"[EditDeckPage] 编辑失败: {e}")
        return {"error": f"编辑页面时出错: {str(e)}"}
