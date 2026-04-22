"""
Assets API — 用户资产管理。
Sprint 6: CRUD + 分类筛选 + 自动沉淀 + 缩略图。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.tables import Asset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

# 默认用户 ID（一阶段单用户）
DEFAULT_USER_ID = "default-user-00000000"


# ──────────────── Pydantic 模型 ────────────────

class AssetUpdate(BaseModel):
    """资产更新请求体。"""
    title: Optional[str] = Field(None, max_length=255)
    file_type: Optional[str] = None
    metadata_: Optional[dict] = None


class AssetOut(BaseModel):
    """资产响应模型。"""
    id: str
    title: str
    file_type: str
    source: str
    mime_type: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    file_size: Optional[int] = None
    task_id: Optional[str] = None
    parent_id: Optional[str] = None
    metadata_: Optional[dict] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


# ──────────────── 列表查询 ────────────────

@router.get("/")
async def list_assets(
    file_type: Optional[str] = Query(None, description="按类型筛选: document|ppt|code|image|skill"),
    source: Optional[str] = Query(None, description="按来源筛选: upload|ai_generated|remix"),
    search: Optional[str] = Query(None, description="标题模糊搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    session: AsyncSession = Depends(get_session),
):
    """
    列出用户资产（支持分类筛选、搜索、分页）。
    """
    query = select(Asset).where(Asset.user_id == DEFAULT_USER_ID)

    # 分类筛选
    if file_type:
        query = query.where(Asset.file_type == file_type)
    if source:
        query = query.where(Asset.source == source)
    # 标题搜索 (P3-1: 转义 LIKE 通配符)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Asset.title.ilike(f"%{escaped}%", escape="\\"))

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar() or 0

    # 排序 + 分页
    query = query.order_by(Asset.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(query)
    assets = result.scalars().all()

    return {
        "assets": [_asset_to_dict(a) for a in assets],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/stats")
async def asset_stats(
    session: AsyncSession = Depends(get_session),
):
    """
    资产统计（按类型分组计数）。
    """
    query = (
        select(Asset.file_type, func.count().label("count"))
        .where(Asset.user_id == DEFAULT_USER_ID)
        .group_by(Asset.file_type)
    )
    result = await session.execute(query)
    stats = {row.file_type: row.count for row in result}

    total = sum(stats.values())
    return {"total": total, "by_type": stats}


# ──────────────── 单个资产 CRUD ────────────────

@router.get("/{asset_id}")
async def get_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取单个资产详情。"""
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == DEFAULT_USER_ID)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")
    return _asset_to_dict(asset)


@router.put("/{asset_id}")
async def update_asset(
    asset_id: str,
    data: AssetUpdate,
    session: AsyncSession = Depends(get_session),
):
    """更新资产信息（标题/类型/元数据）。"""
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == DEFAULT_USER_ID)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")

    if data.title is not None:
        asset.title = data.title
    if data.file_type is not None:
        asset.file_type = data.file_type
    if data.metadata_ is not None:
        asset.metadata_ = data.metadata_
    asset.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(asset)

    logger.info(f"[Assets] 更新资产: {asset_id}")
    return _asset_to_dict(asset)


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: str,
    session: AsyncSession = Depends(get_session),
):
    """删除资产。"""
    result = await session.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == DEFAULT_USER_ID)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在")

    await session.delete(asset)
    await session.commit()
    logger.info(f"[Assets] 删除资产: {asset_id}")
    return {"ok": True, "deleted_id": asset_id}


# ──────────────── 辅助函数 ────────────────

def _asset_to_dict(asset: Asset) -> dict:
    """Asset ORM 对象转 dict。"""
    return {
        "id": asset.id,
        "title": asset.title,
        "file_type": asset.file_type,
        "source": asset.source,
        "mime_type": asset.mime_type,
        "file_url": asset.file_url,
        "thumbnail_url": asset.thumbnail_url,
        "file_size": asset.file_size,
        "task_id": asset.task_id,
        "parent_id": asset.parent_id,
        "metadata_": asset.metadata_,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }
