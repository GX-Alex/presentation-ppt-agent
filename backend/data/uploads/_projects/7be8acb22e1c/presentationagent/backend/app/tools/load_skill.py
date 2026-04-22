"""
load_skill 工具 — 供 LLM function-calling 加载系统或用户 Skill。
当 LLM 判断用户需求匹配某个 Skill 时，调用此工具加载对应角色定义。
Sprint 4: Skill 两层加载机制的 Tool 入口。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────── Tool 定义（JSON Schema） ────────────────

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "加载指定的专业 Skill（角色）。"
            "当用户需求匹配某个 Skill 时调用此工具，加载该 Skill 的详细指令。"
            "支持加载系统预置 Skill 和用户自定义 Skill。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "要加载的 Skill 名称。"
                        "系统 Skill: pptx, docx, research_analyst, code_reviewer, "
                        "data_analyst, writing_coach, meeting_facilitator。"
                        "也可以是用户自定义 Skill 的名称。"
                    ),
                },
            },
            "required": ["skill_name"],
        },
    },
}


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    加载指定 Skill 的完整内容。

    Args:
        params: {"skill_name": "pptx"} — 要加载的 Skill 名称

    Returns:
        {"skill_name": str, "body": str, "source": str} 或 {"error": str}
    """
    skill_name = params.get("skill_name", "").strip()
    if not skill_name:
        return {"error": "skill_name 参数不能为空"}

    # 1. 优先从系统 Skill 加载
    from app.services.skill_service import (
        get_system_skill_body,
        SYSTEM_SKILLS,
    )

    if skill_name in SYSTEM_SKILLS:
        body = get_system_skill_body(skill_name)
        if body:
            logger.info(f"[LoadSkill] 加载系统 Skill: {skill_name}")
            return {
                "skill_name": skill_name,
                "display_name": SYSTEM_SKILLS[skill_name]["display_name"],
                "body": body,
                "source": "system",
                "message": f"已加载系统 Skill: {SYSTEM_SKILLS[skill_name]['display_name']}",
            }
        else:
            return {"error": f"系统 Skill '{skill_name}' 文件未加载，请检查文件是否存在"}

    # 2. 从用户自定义 Skill 加载（需要数据库查询）
    try:
        from app.models.database import async_session
        from app.services.skill_service import (
            list_user_skills,
            increment_skill_usage,
        )

        async with async_session() as session:
            # 默认用户 ID
            user_id = "default-user-00000000"
            user_skills = await list_user_skills(session, user_id, include_disabled=False)

            for skill in user_skills:
                if skill["name"] == skill_name:
                    # 加载用户 Skill 正文（需要重新查询带 body）
                    from app.services.skill_service import get_user_skill
                    full_skill = await get_user_skill(session, skill["id"])
                    if full_skill:
                        await increment_skill_usage(session, skill["id"])
                        logger.info(f"[LoadSkill] 加载用户 Skill: {skill_name}")
                        return {
                            "skill_name": skill_name,
                            "display_name": full_skill.get("display_name", skill_name),
                            "body": full_skill.get("body", ""),
                            "source": "user",
                            "message": f"已加载用户自定义 Skill: {full_skill.get('display_name', skill_name)}",
                        }
    except Exception as e:
        logger.error(f"[LoadSkill] 查询用户 Skill 失败: {e}")

    # 3. 未找到
    available_skills = list(SYSTEM_SKILLS.keys())
    return {
        "error": f"未找到名为 '{skill_name}' 的 Skill",
        "available_system_skills": available_skills,
        "hint": "请检查 Skill 名称是否正确，或使用可用的系统 Skill。",
    }
