"""流水/财报相关文件路径校验与 MIME 类型。"""
import os

# 支持解析的文件扩展名（流水、财报共用）
SUPPORTED_STATEMENT_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def validate_statement_file_path(file_path: str) -> bool:
    """校验路径为绝对路径且扩展名支持（PDF/图片）。"""
    if not file_path or not os.path.isabs(file_path):
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in SUPPORTED_STATEMENT_EXTENSIONS


def is_image_path(file_path: str) -> bool:
    """判断是否为图片文件（jpg/jpeg/png）。"""
    ext = os.path.splitext(file_path)[1].lower()
    return ext in IMAGE_EXTENSIONS


def get_image_mime_type(file_path: str | None = None, *, extension: str | None = None) -> str:
    """根据文件路径或扩展名返回 MIME 类型，默认 image/png。"""
    ext = extension
    if ext is None and file_path:
        ext = os.path.splitext(file_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"
