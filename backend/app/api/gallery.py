"""
Gallery API — 画廊系统（发布/Fork/版本冻结/版权）。
Sprint 6: 公共画廊 CRUD + Fork + 浏览计数。
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.models.tables import Asset, GalleryItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gallery", tags=["gallery"])

DEFAULT_USER_ID = "default-user-00000000"

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


# ──────────────── Pydantic 模型 ────────────────

class PublishRequest(BaseModel):
    """发布到画廊的请求体。"""
    asset_id: str
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = "other"  # ppt | research | code | skill | other
    license: Optional[str] = "cc-by-4.0"


class GalleryItemOut(BaseModel):
    """画廊项目响应模型。"""
    id: str
    asset_id: str
    author_id: str
    category: str
    title: Optional[str] = None
    description: Optional[str] = None
    preview_url: Optional[str] = None
    is_featured: bool = False
    remix_count: int = 0
    view_count: int = 0
    version: int = 1
    license: str = "cc-by-4.0"
    published_at: Optional[str] = None
    # 关联资产信息
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


def _resolve_preview_url(asset: Asset) -> Optional[str]:
    if asset.thumbnail_url:
        return asset.thumbnail_url

    file_url = asset.file_url or ""
    if asset.file_type == "image" and Path(file_url.split("?")[0]).suffix.lower() in IMAGE_EXTENSIONS:
        return file_url

    return None


# ──────────────── 列表查询 ────────────────

@router.get("/")
async def list_gallery(
    category: Optional[str] = Query(None, description="按分类筛选: ppt|research|code|skill|other"),
    featured: Optional[bool] = Query(None, description="只看推荐"),
    search: Optional[str] = Query(None, description="标题搜索"),
    sort: str = Query("newest", description="排序: newest|popular|remix"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    """
    浏览画廊（支持分类/推荐/搜索/排序/分页）。
    """
    query = select(GalleryItem)

    if category:
        query = query.where(GalleryItem.category == category)
    if featured is not None:
        query = query.where(GalleryItem.is_featured == featured)
    if search:
        query = query.where(GalleryItem.title.ilike(f"%{search}%"))

    # 总数
    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    # 排序
    if sort == "popular":
        query = query.order_by(GalleryItem.view_count.desc())
    elif sort == "remix":
        query = query.order_by(GalleryItem.remix_count.desc())
    else:
        query = query.order_by(GalleryItem.published_at.desc())

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await session.execute(query)
    items = result.scalars().all()

    # 关联查询资产信息
    items_out = []
    for item in items:
        d = _gallery_to_dict(item)
        # 查询关联资产
        asset_result = await session.execute(select(Asset).where(Asset.id == item.asset_id))
        asset = asset_result.scalar_one_or_none()
        if asset:
            d["file_type"] = asset.file_type
            d["file_url"] = asset.file_url
            d["thumbnail_url"] = asset.thumbnail_url
        items_out.append(d)

    return {
        "items": items_out,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ──────────────── 发布到画廊 ────────────────

@router.post("/publish")
async def publish_to_gallery(
    data: PublishRequest,
    session: AsyncSession = Depends(get_session),
):
    """
    将资产发布到画廊。
    自动冻结当前版本（version=1），后续更新递增版本号。
    """
    # 验证资产存在
    asset_result = await session.execute(
        select(Asset).where(Asset.id == data.asset_id, Asset.user_id == DEFAULT_USER_ID)
    )
    asset = asset_result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="资产不存在或非本人所有")

    # 检查是否已发布
    exist_result = await session.execute(
        select(GalleryItem).where(GalleryItem.asset_id == data.asset_id)
    )
    existing = exist_result.scalar_one_or_none()
    if existing:
        # 更新版本（递增 version）
        existing.version += 1
        existing.title = data.title or asset.title
        existing.description = data.description or existing.description
        existing.category = data.category or existing.category
        existing.preview_url = _resolve_preview_url(asset)
        await session.commit()
        await session.refresh(existing)
        logger.info(f"[Gallery] 更新画廊项目: {existing.id} → v{existing.version}")
        return _gallery_to_dict(existing)

    # 新建画廊项目
    # 根据资产类型推断分类
    category = data.category
    if category == "other" and asset.file_type:
        type_to_cat = {"ppt": "ppt", "document": "research", "code": "code", "skill": "skill"}
        category = type_to_cat.get(asset.file_type, "other")

    gallery_item = GalleryItem(
        id=str(uuid.uuid4()),
        asset_id=data.asset_id,
        author_id=DEFAULT_USER_ID,
        category=category,
        title=data.title or asset.title,
        description=data.description,
        preview_url=_resolve_preview_url(asset),
        is_featured=False,
        remix_count=0,
        view_count=0,
        version=1,
        license=data.license or "cc-by-4.0",
        published_at=datetime.utcnow(),
    )
    session.add(gallery_item)
    await session.commit()
    await session.refresh(gallery_item)

    logger.info(f"[Gallery] 发布到画廊: {gallery_item.id}, asset={data.asset_id}")
    return _gallery_to_dict(gallery_item)


# ──────────────── 单个画廊项目 ────────────────

@router.get("/{item_id}")
async def get_gallery_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取画廊项目详情（自动增加浏览计数）。"""
    result = await session.execute(select(GalleryItem).where(GalleryItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="画廊项目不存在")

    # 增加浏览计数
    item.view_count = (item.view_count or 0) + 1
    await session.commit()
    await session.refresh(item)

    d = _gallery_to_dict(item)
    # 关联资产
    asset_result = await session.execute(select(Asset).where(Asset.id == item.asset_id))
    asset = asset_result.scalar_one_or_none()
    if asset:
        d["file_type"] = asset.file_type
        d["file_url"] = asset.file_url
        d["thumbnail_url"] = asset.thumbnail_url

    return d


# ──────────────── Fork（复制到我的资产） ────────────────

@router.post("/{item_id}/fork")
async def fork_gallery_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """
    Fork 画廊项目 — 将资产复制到当前用户的资产空间。
    创建 source=remix 的新 Asset，parent_id 指向原始资产。
    """
    # 获取画廊项目
    result = await session.execute(select(GalleryItem).where(GalleryItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="画廊项目不存在")

    # 获取原始资产
    asset_result = await session.execute(select(Asset).where(Asset.id == item.asset_id))
    original_asset = asset_result.scalar_one_or_none()
    if not original_asset:
        raise HTTPException(status_code=404, detail="原始资产不存在")

    # 创建 Fork 资产
    forked_asset = Asset(
        id=str(uuid.uuid4()),
        user_id=DEFAULT_USER_ID,
        title=f"{original_asset.title} (Fork)",
        file_type=original_asset.file_type,
        source="remix",
        mime_type=original_asset.mime_type,
        file_url=original_asset.file_url,
        thumbnail_url=original_asset.thumbnail_url,
        file_size=original_asset.file_size,
        parent_id=original_asset.id,
        metadata_={
            "forked_from": item_id,
            "original_asset_id": original_asset.id,
            "fork_version": item.version,
        },
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(forked_asset)

    # 增加 remix 计数
    item.remix_count = (item.remix_count or 0) + 1
    await session.commit()
    await session.refresh(forked_asset)

    logger.info(f"[Gallery] Fork: {item_id} → 新资产 {forked_asset.id}")

    return {
        "ok": True,
        "forked_asset_id": forked_asset.id,
        "source_gallery_id": item_id,
        "source_asset_id": original_asset.id,
    }


# ──────────────── 删除画廊项目 ────────────────

@router.delete("/{item_id}")
async def delete_gallery_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
):
    """删除画廊项目（仅作者可删）。"""
    result = await session.execute(
        select(GalleryItem).where(GalleryItem.id == item_id, GalleryItem.author_id == DEFAULT_USER_ID)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="画廊项目不存在或非本人发布")

    await session.delete(item)
    await session.commit()
    logger.info(f"[Gallery] 删除画廊项目: {item_id}")
    return {"ok": True, "deleted_id": item_id}


# ──────────────── 辅助函数 ────────────────

def _gallery_to_dict(item: GalleryItem) -> dict:
    """GalleryItem ORM 对象转 dict。"""
    return {
        "id": item.id,
        "asset_id": item.asset_id,
        "author_id": item.author_id,
        "category": item.category,
        "title": item.title,
        "description": item.description,
        "preview_url": item.preview_url,
        "is_featured": item.is_featured,
        "remix_count": item.remix_count,
        "view_count": item.view_count,
        "version": item.version,
        "license": item.license,
        "published_at": item.published_at.isoformat() if item.published_at else None,
    }
