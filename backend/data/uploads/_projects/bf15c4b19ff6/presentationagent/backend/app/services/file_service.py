"""
文件上传服务 — Sprint 5。
职责: 安全校验（白名单/大小/Zip Slip）、文件持久化、Asset 记录创建。
"""
import logging
import os
import re
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Asset

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# ──────────────────── 安全常量 ────────────────────

# 允许上传的文件扩展名白名单
ALLOWED_EXTENSIONS: set[str] = {
    # 文档
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".drawio",
    # 代码
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".yaml", ".yml",
    ".java", ".go", ".rs", ".c", ".cpp", ".h", ".sh", ".sql",
    # 压缩包
    ".zip",
    # 图片
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
}

# MIME 类型 → file_type 映射
MIME_TO_FILE_TYPE: dict[str, str] = {
    "application/pdf": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "ppt",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/xml": "document",
    "text/plain": "document",
    "text/xml": "document",
    "text/markdown": "document",
    "text/csv": "document",
    "application/zip": "code",
    "image/png": "image",
    "image/jpeg": "image",
    "image/gif": "image",
    "image/webp": "image",
    "image/svg+xml": "image",
}

# 扩展名 → file_type 备用映射（当 MIME 不可靠时）
EXT_TO_FILE_TYPE: dict[str, str] = {
    ".pdf": "document", ".docx": "document", ".pptx": "ppt",
    ".xlsx": "document", ".txt": "document", ".md": "document", ".drawio": "document",
    ".csv": "document", ".zip": "code",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".py": "code", ".js": "code", ".ts": "code", ".jsx": "code",
    ".tsx": "code", ".html": "code", ".css": "code", ".json": "code",
    ".yaml": "code", ".yml": "code", ".java": "code", ".go": "code",
    ".rs": "code", ".c": "code", ".cpp": "code", ".h": "code",
    ".sh": "code", ".sql": "code",
}

# 上传大小限制（50 MB）
MAX_FILE_SIZE: int = 50 * 1024 * 1024

# 上传根目录
UPLOAD_DIR = BACKEND_ROOT / "data" / "uploads"

# 默认用户 ID（一阶段单用户）
DEFAULT_USER_ID = "default-user-00000000"


# ──────────────────── 安全校验 ────────────────────

class FileValidationError(Exception):
    """文件校验失败自定义异常。"""
    pass


def validate_extension(filename: str) -> str:
    """
    校验文件扩展名是否在白名单中。
    返回小写扩展名（含 .）。

    Raises:
        FileValidationError: 扩展名不在白名单
    """
    ext = Path(filename).suffix.lower()
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"不支持的文件类型: {ext or '无扩展名'}。"
            f"允许的类型: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def validate_file_size(size: int) -> None:
    """
    校验文件大小是否超限。

    Raises:
        FileValidationError: 超过大小限制
    """
    if size > MAX_FILE_SIZE:
        max_mb = MAX_FILE_SIZE / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        raise FileValidationError(
            f"文件过大: {actual_mb:.1f}MB，最大允许 {max_mb:.0f}MB"
        )


def sanitize_filename(filename: str) -> str:
    """
    清理文件名，移除不安全字符。
    保留中文、英文、数字、下划线、连字符、点号。
    """
    # 取文件名部分（防止路径穿越）
    name = Path(filename).name
    # 替换不安全字符
    name = re.sub(r'[^\w\u4e00-\u9fff\-.]', '_', name)
    # 去除前导点号（防止隐藏文件）
    name = name.lstrip('.')
    return name or "unnamed_file"


def validate_zip_entry(zip_path: str, extract_dir: str) -> bool:
    """
    Zip Slip 防护 — 验证 ZIP 内文件路径不会穿越到提取目录之外。

    Args:
        zip_path: ZIP 内条目的相对路径
        extract_dir: 期望的提取目标目录

    Returns:
        True 表示安全，False 表示路径穿越攻击
    """
    # 解析规范路径
    abs_extract = os.path.realpath(extract_dir)
    # 拼接并解析目标路径
    target = os.path.realpath(os.path.join(extract_dir, zip_path))
    # 确保目标在提取目录内
    return target.startswith(abs_extract + os.sep) or target == abs_extract


def detect_file_type(ext: str, mime_type: str | None) -> str:
    """根据扩展名和 MIME 类型推断 file_type 分类。"""
    if mime_type and mime_type in MIME_TO_FILE_TYPE:
        return MIME_TO_FILE_TYPE[mime_type]
    return EXT_TO_FILE_TYPE.get(ext, "document")


def resolve_file_reference(file_path: str) -> str:
    """将 /static/... 或相对路径解析为后端可访问的磁盘路径。"""
    if file_path.startswith("/static/"):
        relative_path = PurePosixPath(file_path.replace("/static/", "data/", 1))
        return str((BACKEND_ROOT / Path(relative_path)).resolve())

    raw_path = Path(file_path)
    if raw_path.is_absolute():
        return str(raw_path)
    return str((BACKEND_ROOT / raw_path).resolve())


# ──────────────────── 文件存储 ────────────────────

async def save_upload(
    file: UploadFile,
    user_id: str = DEFAULT_USER_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    保存上传文件到磁盘。

    流程:
      1. 校验扩展名白名单
      2. 读取内容并校验大小
      3. 生成安全文件名并写入磁盘
      4. 返回元数据 dict

    Returns:
        {
            "filename": str,        # 原始文件名
            "safe_name": str,       # 清理后的文件名
            "stored_name": str,     # 磁盘上的文件名（含 UUID 前缀）
            "ext": str,             # 扩展名
            "mime_type": str,       # MIME 类型
            "file_type": str,       # 分类: document|ppt|code|image
            "file_size": int,       # 文件大小（字节）
            "file_path": str,       # 磁盘绝对路径
            "file_url": str,        # 静态访问相对URL
            "user_id": str,
            "task_id": str | None,
        }

    Raises:
        FileValidationError: 校验失败
    """
    original_name = file.filename or "unnamed"

    # 1. 扩展名校验
    ext = validate_extension(original_name)

    # 2. 读取文件内容
    content = await file.read()
    file_size = len(content)

    # 3. 大小校验
    validate_file_size(file_size)

    # 4. 生成安全的存储文件名
    safe_name = sanitize_filename(original_name)
    unique_id = uuid.uuid4().hex[:12]
    stored_name = f"{unique_id}_{safe_name}"

    # 5. 创建用户目录并写入文件
    user_dir = UPLOAD_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    file_path = user_dir / stored_name
    file_path.write_bytes(content)

    # 6. 构建静态 URL
    # main.py 中 /static → data/，所以 URL 为 /static/uploads/{user_id}/{stored_name}
    file_url = f"/static/uploads/{user_id}/{stored_name}"

    # 7. 推断文件类型
    mime_type = file.content_type or "application/octet-stream"
    file_type = detect_file_type(ext, mime_type)

    logger.info(
        f"[FileService] 文件上传成功: {original_name} → {stored_name} "
        f"({file_size} bytes, {file_type})"
    )

    return {
        "filename": original_name,
        "safe_name": safe_name,
        "stored_name": stored_name,
        "ext": ext,
        "mime_type": mime_type,
        "file_type": file_type,
        "file_size": file_size,
        "file_path": str(file_path),
        "file_url": file_url,
        "user_id": user_id,
        "task_id": task_id,
    }


async def create_asset_record(
    session: AsyncSession,
    file_meta: dict[str, Any],
) -> Asset:
    """
    根据上传文件元数据创建 Asset 数据库记录。

    Args:
        session: 数据库会话
        file_meta: save_upload 返回的元数据 dict

    Returns:
        创建的 Asset 对象
    """
    asset = Asset(
        id=str(uuid.uuid4()),
        user_id=file_meta["user_id"],
        title=file_meta["filename"],
        file_type=file_meta["file_type"],
        source="upload",
        mime_type=file_meta["mime_type"],
        file_url=file_meta["file_url"],
        file_size=file_meta["file_size"],
        task_id=file_meta.get("task_id"),
        metadata_={
            "original_name": file_meta["filename"],
            "stored_name": file_meta["stored_name"],
            "ext": file_meta["ext"],
        },
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    logger.info(f"[FileService] 创建 Asset 记录: id={asset.id}, title={asset.title}")
    return asset


async def extract_zip_safe(
    zip_path: str | Path,
    extract_dir: str | Path,
) -> list[str]:
    """
    安全解压 ZIP 文件（Zip Slip 防护）。

    Args:
        zip_path: ZIP 文件路径
        extract_dir: 解压目标目录

    Returns:
        解压出的文件相对路径列表

    Raises:
        FileValidationError: 检测到路径穿越攻击
    """
    zip_path = str(zip_path)
    extract_dir = str(extract_dir)
    os.makedirs(extract_dir, exist_ok=True)

    extracted_files: list[str] = []

    with zipfile.ZipFile(zip_path, 'r') as zf:
        for entry in zf.namelist():
            # 跳过目录条目
            if entry.endswith('/'):
                continue

            # Zip Slip 检查
            if not validate_zip_entry(entry, extract_dir):
                raise FileValidationError(
                    f"检测到 Zip Slip 攻击: 路径 '{entry}' 试图穿越到目标目录之外"
                )

            # 检查路径中是否含有 .. 组件
            parts = PurePosixPath(entry).parts
            if '..' in parts:
                raise FileValidationError(
                    f"检测到路径穿越: '{entry}' 包含 '..' 组件"
                )

            # 安全解压
            zf.extract(entry, extract_dir)
            extracted_files.append(entry)

    logger.info(f"[FileService] ZIP 安全解压完成: {len(extracted_files)} 个文件")
    return extracted_files
