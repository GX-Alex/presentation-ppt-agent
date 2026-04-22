"""
Skills API — 用户 Skill CRUD + 校验 + 系统 Skill 列表。
Sprint 4: 完整的 Skill 管理 REST 接口。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.database import async_session
from app.services.skill_service import (
    get_system_skill_list,
    list_user_skills,
    get_user_skill,
    create_user_skill,
    update_user_skill,
    delete_user_skill,
    validate_user_skill,
    toggle_user_skill,
)

router = APIRouter(prefix="/skills", tags=["skills"])

# 默认用户 ID（一阶段无鉴权）
DEFAULT_USER_ID = "default-user-00000000"


# ──────────────── 请求模型 ────────────────

class SkillCreate(BaseModel):
    """创建 Skill 的请求体。"""
    name: str = Field(..., min_length=2, max_length=63, description="Skill 名称")
    display_name: str = Field("", max_length=127, description="展示名称")
    description: str = Field("", description="Skill 描述")
    tags: str = Field("", description="标签，逗号分隔")
    body: str = Field(..., min_length=50, description="Skill 正文（Markdown）")
    required_tools: str = Field("", description="依赖工具，逗号分隔")
    scope: str = Field("manual", description="作用域: manual | auto")


class SkillUpdate(BaseModel):
    """更新 Skill 的请求体。"""
    display_name: str | None = None
    description: str | None = None
    tags: str | None = None
    body: str | None = None
    required_tools: str | None = None
    scope: str | None = None


# ──────────────── 系统 Skill ────────────────

@router.get("/system")
async def list_system_skills():
    """获取系统预置 Skill 列表。"""
    skills = get_system_skill_list()
    return {"skills": skills, "total": len(skills)}


# ──────────────── 用户 Skill CRUD ────────────────

@router.get("/")
async def list_skills(include_disabled: bool = True):
    """列出当前用户的所有自定义 Skill。"""
    async with async_session() as session:
        skills = await list_user_skills(session, DEFAULT_USER_ID, include_disabled)
        return {"skills": skills, "total": len(skills)}


@router.post("/")
async def create_skill(data: SkillCreate):
    """创建新的用户自定义 Skill。"""
    async with async_session() as session:
        skill = await create_user_skill(session, DEFAULT_USER_ID, data.model_dump())
        return {"skill": skill}


@router.get("/{skill_id}")
async def get_skill(skill_id: str):
    """获取单个 Skill 详情。"""
    async with async_session() as session:
        skill = await get_user_skill(session, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"skill": skill}


@router.put("/{skill_id}")
async def update_skill(skill_id: str, data: SkillUpdate):
    """更新用户 Skill。"""
    async with async_session() as session:
        # 过滤掉 None 值
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="没有可更新的字段")
        skill = await update_user_skill(session, skill_id, update_data)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"skill": skill}


@router.delete("/{skill_id}")
async def remove_skill(skill_id: str):
    """删除用户 Skill。"""
    async with async_session() as session:
        success = await delete_user_skill(session, skill_id)
        if not success:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"deleted": True}


@router.post("/{skill_id}/validate")
async def validate_skill(skill_id: str):
    """校验用户 Skill — 检查格式、冲突、依赖工具。"""
    async with async_session() as session:
        result = await validate_user_skill(session, skill_id)
        if not result:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"skill": result}


@router.post("/{skill_id}/toggle")
async def toggle_skill(skill_id: str):
    """切换 Skill 启用/禁用状态。"""
    async with async_session() as session:
        skill = await toggle_user_skill(session, skill_id)
        if not skill:
            raise HTTPException(status_code=404, detail="Skill 不存在")
        return {"skill": skill}
