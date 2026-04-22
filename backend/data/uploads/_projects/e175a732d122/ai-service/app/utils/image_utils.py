"""图片压缩等处理，避免超 API 体积限制。"""
import io
import logging

from PIL import Image

from app.utils.file_utils import get_image_mime_type

logger = logging.getLogger(__name__)

# 压缩时最大边长，超过则等比缩小
MAX_DIMENSION = 2048


def maybe_compress_image(
    image_bytes: bytes,
    file_path: str | None = None,
    mime_type: str = "image/png",
    *,
    threshold: int = 0,
) -> tuple[bytes, str]:
    """
    若图片大小超过 threshold 则压缩，否则原样返回。
    返回 (bytes, mime_type)。threshold 由调用方从配置传入，0 表示不压缩。
    """
    if threshold <= 0 or len(image_bytes) <= threshold:
        out_mime = get_image_mime_type(file_path=file_path) if file_path else mime_type
        return image_bytes, out_mime

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        w, h = img.size
        if w > MAX_DIMENSION or h > MAX_DIMENSION:
            ratio = min(MAX_DIMENSION / w, MAX_DIMENSION / h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        use_jpeg = (file_path and get_image_mime_type(file_path=file_path) == "image/jpeg") or mime_type == "image/jpeg"
        out_fmt = "JPEG" if use_jpeg else "PNG"
        img.save(buf, format=out_fmt, quality=85, optimize=True)
        compressed = buf.getvalue()
        logger.info(
            "[image] 图片已压缩 | 原=%.1fKB | 后=%.1fKB",
            len(image_bytes) / 1024,
            len(compressed) / 1024,
        )
        return compressed, "image/jpeg" if out_fmt == "JPEG" else "image/png"
    except Exception as e:
        logger.warning("图片压缩失败，使用原图: %s", e)
        out_mime = get_image_mime_type(file_path=file_path) if file_path else mime_type
        return image_bytes, out_mime
