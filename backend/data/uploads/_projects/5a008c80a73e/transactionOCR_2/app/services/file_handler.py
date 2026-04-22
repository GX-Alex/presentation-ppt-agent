"""
文件处理服务 — 下载远程文件、判断类型、PDF 转图片
参考 main.py 中的 pdf_to_images 实现
"""
import io
import base64
import logging
from typing import List, Tuple
from urllib.parse import urlparse, unquote

import fitz  # PyMuPDF
import httpx
from PIL import Image

from app.config import PDF_ZOOM, PDF_QUALITY, PDF_MAX_WIDTH, REQUEST_TIMEOUT, IMAGE_FORMAT

logger = logging.getLogger("transaction_ocr")

# 支持的图片后缀
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
PDF_EXTENSIONS = {".pdf"}


def detect_file_type(url: str) -> str:
    """
    通过 URL 后缀或 data URL MIME 类型判断文件类型。

    Returns:
        "image" | "pdf" | "unknown"
    """
    # 处理 data: URL
    if url.startswith("data:"):
        mime_part = url.split(";")[0]  # e.g. "data:application/pdf"
        if "pdf" in mime_part.lower():
            return "pdf"
        if "image" in mime_part.lower():
            return "image"
        return "image"

    parsed = urlparse(url)
    # unquote 处理 URL 编码（如 %2F），只取 path 部分（query/fragment 已被 urlparse 分离）
    path = unquote(parsed.path).lower()
    # 取最后一段路径的扩展名（兼容路径中含点的情况）
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.rsplit("/", 1)[-1] else ""
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in IMAGE_EXTENSIONS:
        return "image"
    # 默认当图片处理
    return "image"


async def download_file(url: str) -> bytes:
    """
    异步下载远程文件，返回字节内容。
    """
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=False) as client:
        logger.info("下载文件: %s", url)
        resp = await client.get(url)
        resp.raise_for_status()
        logger.info("下载完成: %d bytes", len(resp.content))
        return resp.content


def pdf_to_images(
    file_bytes: bytes,
    zoom: float = PDF_ZOOM,
    quality: int = PDF_QUALITY,
    max_width: int = PDF_MAX_WIDTH,
    image_format: str = IMAGE_FORMAT,
) -> List[bytes]:
    """
    将 PDF 转换为图片字节列表。
    
    Args:
        file_bytes: PDF 文件字节
        zoom: 缩放倍数（默认 2.0）
        quality: 图片质量，仅当 image_format="JPEG" 时有效（1-100，默认 85）
        max_width: 图片最大宽度像素值（默认 2000）
        image_format: 输出格式 "PNG"（无损）或 "JPEG"（有损压缩，默认 PNG）
    """
    images = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            output = io.BytesIO()
            # 根据配置选择输出格式
            if image_format.upper() == "JPEG":
                # JPEG 有损压缩，文件小但可能损失清晰度
                img.save(output, format="JPEG", quality=quality, optimize=True)
            else:
                # PNG 无损压缩，文件大但保留完整清晰度
                img.save(output, format="PNG", optimize=True)
            img_bytes = output.getvalue()

            logger.info(
                "PDF 页面 %d: 原始 %dx%d → %dx%d, %s %d bytes",
                page_num + 1,
                pix.width,
                pix.height,
                img.width,
                img.height,
                image_format.upper(),
                len(img_bytes),
            )
            images.append(img_bytes)

        doc.close()
    except Exception as e:
        raise ValueError(f"PDF 处理失败: {e}") from e

    return images


def image_to_base64_url(img_bytes: bytes, mime: str = "image/png") -> str:
    """将图片字节转为 base64 data URL，用于 VLM 输入"""
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:{mime};base64,{b64}"
