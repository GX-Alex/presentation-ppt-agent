"""
公共工具模块：文件/路径校验、图片处理、JSON 抽取等。

高内聚：按职责分文件；低耦合：不依赖 api/parsers，仅依赖标准库与 core.config（可选）。
"""
from app.utils.file_utils import (
    get_image_mime_type,
    is_image_path,
    validate_statement_file_path,
)
from app.utils.image_utils import maybe_compress_image
from app.utils.json_utils import extract_json_raw

__all__ = [
    "validate_statement_file_path",
    "is_image_path",
    "get_image_mime_type",
    "maybe_compress_image",
    "extract_json_raw",
]
