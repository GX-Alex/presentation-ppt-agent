"""
parse_project 工具 — 解析上传的项目压缩包（ZIP）。
安全解压后分析项目结构，返回文件树和项目元信息。
"""
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ──────────────── Tool 定义（OpenAI function-calling 格式）────────────────
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "parse_project",
        "description": (
            "解析上传的项目压缩包（ZIP），安全解压并分析项目结构。"
            "返回文件树、项目类型检测（如 Python/Node.js/Java）和关键配置文件摘要。"
            "解压后的文件可通过 read_project_file 工具逐个读取。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "asset_id": {
                    "type": "string",
                    "description": "上传 ZIP 文件的 Asset ID",
                },
                "file_path": {
                    "type": "string",
                    "description": "ZIP 文件在服务器上的路径",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "文件树最大显示深度（默认 5）",
                    "default": 5,
                },
            },
            "required": ["asset_id", "file_path"],
        },
    },
}

# 项目类型检测规则
PROJECT_INDICATORS: dict[str, list[str]] = {
    "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile"],
    "nodejs": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "dotnet": ["*.csproj", "*.sln"],
    "docker": ["Dockerfile", "docker-compose.yml", "docker-compose.yaml"],
}

# 忽略的目录名（不展示在文件树中）
IGNORED_DIRS = {
    "__pycache__", "node_modules", ".git", ".svn", ".hg",
    ".idea", ".vscode", ".vs", "dist", "build", ".tox",
    "venv", ".venv", "env", ".env", ".eggs", "*.egg-info",
}

# 关键配置文件（自动摘要）
KEY_CONFIG_FILES = {
    "requirements.txt", "package.json", "pyproject.toml",
    "setup.py", "Makefile", "Dockerfile", "docker-compose.yml",
    "README.md", "README.rst", "README.txt",
    ".env.example", "config.yaml", "config.json",
}

# 解压目录
EXTRACT_BASE = Path("data/uploads/_projects")


def _resolve_path(file_path: str) -> str:
    """将 /static/... 格式转为磁盘路径。"""
    if file_path.startswith("/static/"):
        return file_path.replace("/static/", "data/", 1)
    return file_path


def _build_file_tree(root_dir: str, max_depth: int = 5) -> dict[str, Any]:
    """
    构建项目文件树（带深度限制）。

    Returns:
        {
            "name": str,
            "type": "dir",
            "children": [...],
            "file_count": int,
            "dir_count": int,
        }
    """
    root = Path(root_dir)

    def _scan(current: Path, depth: int) -> dict[str, Any]:
        name = current.name
        if current.is_file():
            return {
                "name": name,
                "type": "file",
                "size": current.stat().st_size,
                "ext": current.suffix.lower(),
            }

        # 目录
        children = []
        if depth < max_depth:
            try:
                entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                for entry in entries:
                    # 跳过忽略的目录
                    if entry.is_dir() and entry.name in IGNORED_DIRS:
                        continue
                    children.append(_scan(entry, depth + 1))
            except PermissionError:
                pass

        file_count = sum(1 for c in children if c.get("type") == "file")
        dir_count = sum(1 for c in children if c.get("type") == "dir")

        return {
            "name": name,
            "type": "dir",
            "children": children,
            "file_count": file_count,
            "dir_count": dir_count,
        }

    return _scan(root, 0)


def _detect_project_type(root_dir: str) -> list[str]:
    """检测项目类型（可能同时属于多种类型，如 Python + Docker）。"""
    detected = []
    root = Path(root_dir)

    for ptype, indicators in PROJECT_INDICATORS.items():
        for indicator in indicators:
            if '*' in indicator:
                # 通配符匹配
                if list(root.rglob(indicator)):
                    detected.append(ptype)
                    break
            else:
                # 精确文件名匹配（在根目录或一级子目录）
                if (root / indicator).exists():
                    detected.append(ptype)
                    break
                # 检查一级子目录（解压后可能多一层）
                for sub in root.iterdir():
                    if sub.is_dir() and (sub / indicator).exists():
                        detected.append(ptype)
                        break

    return detected or ["unknown"]


def _read_key_configs(root_dir: str, max_preview: int = 2000) -> dict[str, str]:
    """读取关键配置文件的前 N 字符作为摘要。"""
    configs = {}
    root = Path(root_dir)

    for config_name in KEY_CONFIG_FILES:
        # 在根目录和一级子目录中查找
        candidates = [root / config_name]
        for sub in root.iterdir():
            if sub.is_dir():
                candidates.append(sub / config_name)

        for path in candidates:
            if path.is_file():
                try:
                    content = path.read_text(encoding='utf-8', errors='replace')
                    rel_path = str(path.relative_to(root))
                    if len(content) > max_preview:
                        content = content[:max_preview] + f"\n... [截断，共 {len(content)} 字符]"
                    configs[rel_path] = content
                except Exception as e:
                    logger.warning(f"[parse_project] 读取配置文件失败: {path} — {e}")

    return configs


def _tree_to_text(tree: dict, indent: int = 0) -> str:
    """将文件树转为可读的文本格式。"""
    prefix = "  " * indent
    if tree["type"] == "file":
        size_str = _format_size(tree.get("size", 0))
        return f"{prefix}📄 {tree['name']} ({size_str})"

    lines = [f"{prefix}📁 {tree['name']}/"]
    for child in tree.get("children", []):
        lines.append(_tree_to_text(child, indent + 1))
    return "\n".join(lines)


def _format_size(size: int) -> str:
    """格式化文件大小。"""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    else:
        return f"{size / (1024 * 1024):.1f}MB"


def _count_files(root_dir: str) -> dict[str, int]:
    """统计各扩展名的文件数量。"""
    ext_counts: dict[str, int] = {}
    root = Path(root_dir)
    for path in root.rglob("*"):
        if path.is_file() and path.name not in IGNORED_DIRS:
            # 检查是否在忽略目录中
            parts = path.relative_to(root).parts
            if any(p in IGNORED_DIRS for p in parts):
                continue
            ext = path.suffix.lower() or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
    return dict(sorted(ext_counts.items(), key=lambda x: -x[1]))


# ──────────────── Tool 执行入口 ────────────────

async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行项目解析。

    Args:
        params: {
            "asset_id": str,
            "file_path": str,
            "max_depth": int (可选, 默认 5),
        }

    Returns:
        {
            "asset_id": str,
            "project_id": str,       # 解压目录标识
            "project_types": [str],   # 检测到的项目类型
            "file_tree": str,         # 文本格式文件树
            "file_stats": dict,       # 按扩展名统计
            "key_configs": dict,      # 关键配置文件摘要
            "extract_dir": str,       # 解压目录路径（供 read_project_file 使用）
        }
    """
    asset_id = params.get("asset_id", "")
    file_path = params.get("file_path", "")
    max_depth = params.get("max_depth", 5)

    if not asset_id or not file_path:
        return {"error": "缺少 asset_id 或 file_path 参数"}

    actual_path = _resolve_path(file_path)

    if not os.path.isfile(actual_path):
        return {"error": f"文件不存在: {file_path}"}

    if not actual_path.lower().endswith('.zip'):
        return {"error": "parse_project 仅支持 ZIP 格式"}

    # 创建唯一解压目录
    project_id = uuid.uuid4().hex[:12]
    extract_dir = str(EXTRACT_BASE / project_id)

    try:
        # 安全解压（含 Zip Slip 防护）
        from app.services.file_service import extract_zip_safe
        extracted_files = await extract_zip_safe(actual_path, extract_dir)
    except Exception as e:
        logger.exception(f"[parse_project] 解压失败: {actual_path}")
        return {"error": f"ZIP 解压失败: {str(e)}"}

    # 分析项目
    try:
        file_tree_dict = _build_file_tree(extract_dir, max_depth)
        file_tree_text = _tree_to_text(file_tree_dict)
        project_types = _detect_project_type(extract_dir)
        file_stats = _count_files(extract_dir)
        key_configs = _read_key_configs(extract_dir)
    except Exception as e:
        logger.exception(f"[parse_project] 分析失败: {extract_dir}")
        return {"error": f"项目分析失败: {str(e)}"}

    logger.info(
        f"[parse_project] 解析完成: project_id={project_id}, "
        f"files={len(extracted_files)}, types={project_types}"
    )

    return {
        "asset_id": asset_id,
        "project_id": project_id,
        "project_types": project_types,
        "file_count": len(extracted_files),
        "file_tree": file_tree_text,
        "file_stats": file_stats,
        "key_configs": key_configs,
        "extract_dir": extract_dir,
    }
