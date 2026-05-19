"""LLM 配置 API — 管理模型供应商、BASE_URL、模型名称和 API Key。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.database import async_session
from app.services.user_settings_service import (
    DEFAULT_USER_ID,
    get_user_settings,
    update_user_settings,
)

router = APIRouter(prefix="/llm-config", tags=["llm-config"])


def _mask_api_key(api_key: str) -> str:
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


class LLMConfigRequest(BaseModel):
    provider: str = ""
    base_url: str = ""
    model: str = ""
    api_key: str | None = None  # None = keep existing, "" = clear, str = update
    is_reasoning_model: bool = False


@router.get("")
async def get_llm_config():
    async with async_session() as session:
        settings = await get_user_settings(session, DEFAULT_USER_ID)
    llm = settings.get("llm", {})
    api_key = llm.get("api_key", "")
    return {
        "provider": llm.get("provider", ""),
        "base_url": llm.get("base_url", ""),
        "model": llm.get("model", ""),
        "api_key_masked": _mask_api_key(api_key) if api_key else "",
        "has_api_key": bool(api_key),
        "is_reasoning_model": llm.get("is_reasoning_model", False),
    }


@router.post("")
async def save_llm_config(body: LLMConfigRequest):
    async with async_session() as session:
        current = await get_user_settings(session, DEFAULT_USER_ID)
        current_llm = current.get("llm", {})

        patch: dict = {
            "provider": body.provider,
            "base_url": body.base_url,
            "model": body.model,
            "api_key": body.api_key if body.api_key is not None else current_llm.get("api_key", ""),
            "is_reasoning_model": body.is_reasoning_model,
        }

        settings = await update_user_settings(session, {"llm": patch}, DEFAULT_USER_ID)

    llm = settings.get("llm", {})
    api_key = llm.get("api_key", "")
    return {
        "ok": True,
        "provider": llm.get("provider", ""),
        "base_url": llm.get("base_url", ""),
        "model": llm.get("model", ""),
        "api_key_masked": _mask_api_key(api_key) if api_key else "",
        "has_api_key": bool(api_key),
        "is_reasoning_model": llm.get("is_reasoning_model", False),
    }
