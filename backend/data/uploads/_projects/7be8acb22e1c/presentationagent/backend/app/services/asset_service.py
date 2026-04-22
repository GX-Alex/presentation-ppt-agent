"""
资产服务 — Sprint 6。
职责: 自动沉淀（PPT/文档生成后自动创建 Asset）、缩略图生成。
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Asset, Presentation

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "default-user-00000000"


# ──────────────── 自动沉淀 ────────────────

async def auto_settle_presentation(
    session: AsyncSession,
    presentation_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> Optional[Asset]:
    """
    PPT 生成后自动沉淀为 Asset 记录。
    如果已存在相同 presentation 的 Asset，则更新而非重复创建。

    Args:
        session: 数据库会话
        presentation_id: Presentation 记录 ID
        user_id: 用户 ID

    Returns:
        创建/更新的 Asset 对象，如果 Presentation 不存在则返回 None
    """
    # 查询 Presentation
    result = await session.execute(
        select(Presentation).where(Presentation.id == presentation_id)
    )
    ppt = result.scalar_one_or_none()
    if not ppt:
        logger.warning(f"[AssetService] Presentation 不存在: {presentation_id}")
        return None

    # 检查是否已有对应 Asset（通过 metadata_ 中的 presentation_id）
    existing_result = await session.execute(
        select(Asset).where(
            Asset.user_id == user_id,
            Asset.file_type == "ppt",
            Asset.source == "generated",
        )
    )
    existing_assets = existing_result.scalars().all()

    # 检查 metadata_ 中是否有 presentation_id 匹配
    for asset in existing_assets:
        meta = asset.metadata_ or {}
        if meta.get("presentation_id") == presentation_id:
            # 已存在，更新
            asset.title = ppt.title or asset.title
            asset.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(asset)
            logger.info(f"[AssetService] 更新已有 PPT Asset: {asset.id}")
            return asset

    # 构建文件 URL（PPT 导出路径）
    file_url = f"/static/presentations/{presentation_id}/export.pptx"

    # 生成缩略图 URL（如果有首页幻灯片）
    thumbnail_url = await _generate_ppt_thumbnail(session, presentation_id)

    # 创建新 Asset
    asset = Asset(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=ppt.title or "未命名演示文稿",
        file_type="ppt",
        source="generated",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        task_id=ppt.task_id,
        metadata_={
            "presentation_id": presentation_id,
            "slide_count": ppt.slide_count,
            "theme": ppt.theme,
        },
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    logger.info(f"[AssetService] PPT 自动沉淀: {asset.id}, title={asset.title}")
    return asset


async def auto_settle_document(
    session: AsyncSession,
    title: str,
    file_url: str,
    task_id: Optional[str] = None,
    mime_type: str = "text/markdown",
    file_type: str = "document",
    user_id: str = DEFAULT_USER_ID,
    extra_meta: Optional[dict] = None,
) -> Asset:
    """
    文档/代码生成后自动沉淀为 Asset 记录。

    Args:
        session: 数据库会话
        title: 文档标题
        file_url: 文件访问 URL
        task_id: 关联任务 ID
        mime_type: MIME 类型
        file_type: 文件分类 (document|code)
        user_id: 用户 ID
        extra_meta: 额外元数据

    Returns:
        创建的 Asset 对象
    """
    asset = Asset(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=title,
        file_type=file_type,
        source="generated",
        mime_type=mime_type,
        file_url=file_url,
        task_id=task_id,
        metadata_=extra_meta or {},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)

    logger.info(f"[AssetService] 文档自动沉淀: {asset.id}, title={title}")
    return asset


# ──────────────── 缩略图生成 ────────────────

async def _generate_ppt_thumbnail(
    session: AsyncSession,
    presentation_id: str,
) -> Optional[str]:
    """
    为 PPT 生成缩略图 URL。
    当前实现：使用首页幻灯片的预览图（如果存在）。
    未来可扩展为实际截图。

    Returns:
        缩略图 URL 或 None
    """
    from app.models.tables import Slide

    # 查找第一张幻灯片
    result = await session.execute(
        select(Slide)
        .where(Slide.presentation_id == presentation_id)
        .order_by(Slide.position)
        .limit(1)
    )
    first_slide = result.scalar_one_or_none()
    if not first_slide:
        return None

    # 如果幻灯片有 thumbnail 字段或内容中有图片引用，提取之
    # 当前返回一个占位缩略图路径
    thumbnail_path = f"/static/thumbnails/ppt_{presentation_id}.png"

    # 检查文件是否实际存在
    local_path = Path(f"data/thumbnails/ppt_{presentation_id}.png")
    if local_path.exists():
        return thumbnail_path

    # 可以尝试从幻灯片内容生成简易缩略图
    # （当前版本返回 None，待后续集成截图引擎）
    logger.debug(f"[AssetService] PPT 缩略图暂不可用: {presentation_id}")
    return None


async def generate_image_thumbnail(
    source_url: str,
    asset_id: str,
) -> Optional[str]:
    """
    为图片资产生成缩略图。
    当前实现：图片类型直接使用原图作为缩略图。

    Args:
        source_url: 原图 URL
        asset_id: 资产 ID

    Returns:
        缩略图 URL
    """
    # 图片类型直接用原图作为缩略图
    # 未来可集成 Pillow 生成等比缩放的缩略图
    return source_url


async def update_asset_thumbnail(
    session: AsyncSession,
    asset_id: str,
    thumbnail_url: str,
) -> bool:
    """
    更新资产的缩略图 URL。

    Returns:
        True 更新成功，False 资产不存在
    """
    result = await session.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        return False

    asset.thumbnail_url = thumbnail_url
    asset.updated_at = datetime.utcnow()
    await session.commit()
    logger.info(f"[AssetService] 更新缩略图: {asset_id} → {thumbnail_url}")
    return True
