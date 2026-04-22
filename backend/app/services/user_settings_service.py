"""用户设置服务。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import User

DEFAULT_USER_ID = "default-user-00000000"

DEFAULT_USER_SETTINGS: dict[str, Any] = {
    "memory": {
        "enabled": True,
        "auto_capture": {
            "preference": True,
            "instruction": True,
            "fact": False,
            "feedback": False,
        },
    },
    "ui": {
        "show_thinking": True,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(base)
    if not override:
        return merged

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def normalize_user_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    """补齐默认设置，返回可直接使用的 settings。"""
    return _deep_merge(DEFAULT_USER_SETTINGS, settings)


async def ensure_user(
    session: AsyncSession,
    user_id: str = DEFAULT_USER_ID,
    *,
    name: str = "默认用户",
    email: str | None = None,
) -> User:
    """确保用户存在。"""
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        id=user_id,
        name=name,
        email=email,
        settings=deepcopy(DEFAULT_USER_SETTINGS),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_settings(
    session: AsyncSession,
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """获取用户设置，如用户不存在则自动创建默认用户。"""
    user = await ensure_user(session, user_id=user_id)
    normalized = normalize_user_settings(user.settings)
    if user.settings != normalized:
        user.settings = normalized
        await session.commit()
    return normalized


async def update_user_settings(
    session: AsyncSession,
    patch: dict[str, Any],
    user_id: str = DEFAULT_USER_ID,
) -> dict[str, Any]:
    """更新用户设置（深度合并）。"""
    user = await ensure_user(session, user_id=user_id)
    merged = _deep_merge(normalize_user_settings(user.settings), patch)
    user.settings = merged
    await session.commit()
    return merged


def is_memory_enabled(settings: dict[str, Any] | None) -> bool:
    normalized = normalize_user_settings(settings)
    return bool(normalized.get("memory", {}).get("enabled", True))


def is_auto_memory_capture_enabled(
    settings: dict[str, Any] | None,
    category: str,
) -> bool:
    normalized = normalize_user_settings(settings)
    if not normalized.get("memory", {}).get("enabled", True):
        return False
    auto_capture = normalized.get("memory", {}).get("auto_capture", {})
    return bool(auto_capture.get(category, False))