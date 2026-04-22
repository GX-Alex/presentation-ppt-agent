"""Memory API — 长期记忆管理与设置。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.models.database import async_session
from app.services.memory_service import (
    capture_memory,
    clear_user_memories,
    delete_memory,
    get_memory_count,
    list_user_memories,
    update_memory,
)
from app.services.user_settings_service import (
    DEFAULT_USER_ID,
    ensure_user,
    get_user_settings,
    update_user_settings,
)

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    category: str = Field(..., pattern="^(preference|fact|instruction|feedback)$")
    content: str = Field(..., min_length=1, max_length=2000)


class MemoryUpdate(BaseModel):
    category: str | None = Field(None, pattern="^(preference|fact|instruction|feedback)$")
    content: str | None = Field(None, min_length=1, max_length=2000)


class AutoCaptureSettingsPayload(BaseModel):
    preference: bool | None = None
    instruction: bool | None = None
    fact: bool | None = None
    feedback: bool | None = None


class MemorySettingsPayload(BaseModel):
    enabled: bool | None = None
    auto_capture: AutoCaptureSettingsPayload | None = None


@router.get("/")
async def get_memories(category: str | None = None):
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        memories = await list_user_memories(session, DEFAULT_USER_ID, category)
        return {"memories": memories, "total": len(memories)}


@router.post("/")
async def create_memory(payload: MemoryCreate):
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        memory = await capture_memory(
            session=session,
            user_id=DEFAULT_USER_ID,
            category=payload.category,
            content=payload.content,
            source="user_explicit",
            confidence=1.0,
        )
        return {"memory": memory}


@router.put("/{memory_id}")
async def edit_memory(memory_id: str, payload: MemoryUpdate):
    if payload.category is None and payload.content is None:
        raise HTTPException(status_code=400, detail="没有可更新的字段")

    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        memory = await update_memory(
            session=session,
            memory_id=memory_id,
            category=payload.category,
            content=payload.content,
        )
        if not memory:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"memory": memory}


@router.delete("/{memory_id}")
async def remove_memory(memory_id: str):
    async with async_session() as session:
        success = await delete_memory(session, memory_id)
        if not success:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"deleted": True}


@router.post("/clear")
async def clear_memory():
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        cleared = await clear_user_memories(session, DEFAULT_USER_ID)
        return {"success": True, "cleared": cleared}


@router.get("/export")
async def export_memories():
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        memories = await list_user_memories(session, DEFAULT_USER_ID)
        return {"memories": memories, "total": len(memories)}


@router.get("/settings")
async def get_memory_settings():
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)
        settings = await get_user_settings(session, DEFAULT_USER_ID)
        memory_count = await get_memory_count(session, DEFAULT_USER_ID)
        return {
            "settings": settings.get("memory", {}),
            "memory_count": memory_count,
        }


@router.post("/settings")
async def update_memory_settings_api(payload: MemorySettingsPayload):
    async with async_session() as session:
        await ensure_user(session, user_id=DEFAULT_USER_ID)

        patch: dict[str, object] = {"memory": {}}
        if payload.enabled is not None:
            patch["memory"]["enabled"] = payload.enabled
        if payload.auto_capture is not None:
            patch["memory"]["auto_capture"] = {
                key: value
                for key, value in payload.auto_capture.model_dump().items()
                if value is not None
            }

        settings = await update_user_settings(session, patch, DEFAULT_USER_ID)
        memory_count = await get_memory_count(session, DEFAULT_USER_ID)
        return {
            "settings": settings.get("memory", {}),
            "memory_count": memory_count,
        }