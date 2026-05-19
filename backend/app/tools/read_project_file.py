"""
read_project_file 工具 — 读取已解压项目中的单个文件。
配合 parse_project 使用，逐个查看项目文件内容。
"""
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────── Tool 定义（OpenAI function-calling 格式）────────────────
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_project_file",
        "description": (
            "读取已解压项目中的单个文件内容。"
            "需要先通过 parse_project 工具解压项目，获取 extract_dir。"
            "支持指定行范围仅读取部分内容。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "extract_dir": {
                    "type": "string",
                    "description": "parse_project 返回的解压目录路径",
                },
                "file_path": {
                    "type": "string",
                    "description": "文件在项目中的相对路径（如 'src/main.py'）",
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（从 1 开始，可选）",
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（包含，可选）",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "最大返回字符数（默认 20000）",
                    "default": 20000,
                },
            },
            "required": ["extract_dir", "file_path"],
        },
    },
}

# 二进制文件扩展名（不尝试文本读取）
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".bmp", ".tiff", ".mp3", ".mp4", ".avi", ".mov",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".class",
    ".pyc", ".pyo", ".wasm", ".bin", ".dat",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
}

# 解压目录安全前缀
SAFE_PREFIX = os.path.realpath("data/uploads/_projects")


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    读取项目文件内容。

    Args:
        params: {
            "extract_dir": str,      # 解压目录
            "file_path": str,        # 相对路径
            "start_line": int | None,
            "end_line": int | None,
            "max_chars": int (默认 20000),
        }

    Returns:
        {
            "file_path": str,
            "content": str,
            "line_count": int,
            "truncated": bool,
            "language": str,
        }
    """
    extract_dir = params.get("extract_dir", "")
    file_path = params.get("file_path", "")
    start_line = params.get("start_line")
    end_line = params.get("end_line")
    max_chars = params.get("max_chars", 20000)

    if not extract_dir or not file_path:
        return {
            "error": (
                "缺少 extract_dir 参数。"
                "extract_dir 是项目解压目录路径，有两种获取方式：\n"
                "1. 若已上传项目文件：先调用 parse_project(asset_id=...) 获取 extract_dir，再用它调用本工具\n"
                "2. 若 context 中已有 extract_dir 字段：直接使用该值"
            )
        }

    # 安全检查: 确保路径在合法目录内
    full_path = os.path.realpath(os.path.join(extract_dir, file_path))
    real_extract = os.path.realpath(extract_dir)

    # 防止路径穿越
    if not full_path.startswith(real_extract + os.sep) and full_path != real_extract:
        return {"error": f"安全拒绝: 路径 '{file_path}' 超出项目目录范围"}

    # 额外检查: 解压目录必须在安全前缀下
    if not real_extract.startswith(SAFE_PREFIX):
        return {"error": "安全拒绝: 非法的解压目录路径"}

    if not os.path.isfile(full_path):
        return {"error": f"文件不存在: {file_path}"}

    # 检查是否为二进制文件
    ext = Path(full_path).suffix.lower()
    if ext in BINARY_EXTENSIONS:
        file_size = os.path.getsize(full_path)
        return {
            "file_path": file_path,
            "content": f"[二进制文件，大小: {file_size} 字节，扩展名: {ext}]",
            "line_count": 0,
            "truncated": False,
            "language": "binary",
            "is_binary": True,
        }

    # 读取文件内容
    try:
        with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return {"error": f"读取文件失败: {str(e)}"}

    total_lines = len(lines)

    # 行范围筛选
    if start_line is not None or end_line is not None:
        s = max(0, (start_line or 1) - 1)  # 转为 0-based
        e = min(total_lines, end_line or total_lines)
        lines = lines[s:e]

    content = "".join(lines)

    # 截断检查
    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]
        content += f"\n\n... [内容已截断，总共 {total_lines} 行]"

    # 推断语言
    language = _detect_language(ext)

    logger.info(f"[read_project_file] 读取: {file_path} ({total_lines} 行)")

    return {
        "file_path": file_path,
        "content": content,
        "line_count": total_lines,
        "truncated": truncated,
        "language": language,
        "is_binary": False,
    }


def _detect_language(ext: str) -> str:
    """根据扩展名推断编程语言。"""
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".jsx": "jsx", ".tsx": "tsx", ".html": "html", ".css": "css",
        ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".md": "markdown", ".txt": "text", ".csv": "csv",
        ".java": "java", ".go": "go", ".rs": "rust",
        ".c": "c", ".cpp": "cpp", ".h": "c", ".sh": "shell",
        ".sql": "sql", ".xml": "xml", ".toml": "toml",
        ".ini": "ini", ".cfg": "ini", ".env": "text",
        ".dockerfile": "dockerfile",
    }
    return lang_map.get(ext, "text")
