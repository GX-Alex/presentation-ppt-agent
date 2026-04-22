"""
Files API — 文件上传与管理。
Sprint 5: 安全上传（白名单/大小校验/Zip Slip 防护）+ Asset 记录创建。
"""
import logging
from typing import Optional

from fastapi import APIRouter, File, Query, UploadFile, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.services.file_service import (
    FileValidationError,
    save_upload,
    create_asset_record,
    DEFAULT_USER_ID,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = File(..., description="上传的文件列表"),
    task_id: Optional[str] = Query(None, description="关联的任务 ID"),
    session: AsyncSession = Depends(get_session),
):
    """
    上传文件（支持多文件同时上传）。

    安全措施:
    - 文件类型白名单校验
    - 大小限制（50MB）
    - 文件名清理（防路径穿越）
    - Zip Slip 防护（ZIP 文件）

    Returns:
        {"uploaded": [...], "errors": [...]}
    """
    uploaded: list[dict] = []
    errors: list[dict] = []

    for file in files:
        try:
            # 1. 保存文件到磁盘（含安全校验）
            file_meta = await save_upload(
                file=file,
                user_id=DEFAULT_USER_ID,
                task_id=task_id,
            )

            # 2. 创建 Asset 数据库记录
            asset = await create_asset_record(session, file_meta)

            uploaded.append({
                "asset_id": asset.id,
                "filename": file_meta["filename"],
                "file_type": file_meta["file_type"],
                "mime_type": file_meta["mime_type"],
                "file_size": file_meta["file_size"],
                "file_url": file_meta["file_url"],
            })

            logger.info(f"[Files API] 上传成功: {file_meta['filename']}")

        except FileValidationError as e:
            # 安全校验失败 — 记录错误但不中断其他文件上传
            errors.append({
                "filename": file.filename or "unknown",
                "error": str(e),
            })
            logger.warning(f"[Files API] 校验失败: {file.filename} — {e}")

        except Exception as e:
            # 其他未预期错误
            errors.append({
                "filename": file.filename or "unknown",
                "error": f"上传失败: {str(e)}",
            })
            logger.exception(f"[Files API] 上传异常: {file.filename}")

    return {
        "uploaded": uploaded,
        "errors": errors,
        "total": len(files),
        "success_count": len(uploaded),
        "error_count": len(errors),
    }
