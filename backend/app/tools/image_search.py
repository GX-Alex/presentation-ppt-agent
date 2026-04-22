"""
image_search 工具 — 通过 Pexels API 搜索免费图片。
返回高质量图片 URL、缩略图、摄影师信息。
"""
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ──────────────── Tool 定义（OpenAI function-calling 格式）────────────────
TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "image_search",
        "description": (
            "搜索免费高质量图片（通过 Pexels API）。"
            "适合为 PPT、文档、网页查找配图。"
            "返回图片 URL、缩略图、摄影师信息和许可证信息。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（建议使用英文以获得更好结果）",
                },
                "count": {
                    "type": "integer",
                    "description": "返回图片数量（默认 5，最大 15）",
                    "default": 5,
                },
                "orientation": {
                    "type": "string",
                    "description": "图片方向: landscape（横版）| portrait（竖版）| square（方形）",
                    "enum": ["landscape", "portrait", "square"],
                },
                "size": {
                    "type": "string",
                    "description": "图片大小: large | medium | small",
                    "enum": ["large", "medium", "small"],
                },
            },
            "required": ["query"],
        },
    },
}

# Pexels API 配置
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
PEXELS_API_URL = "https://api.pexels.com/v1/search"
REQUEST_TIMEOUT = 15.0


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行图片搜索。

    Args:
        params: {
            "query": str,
            "count": int (可选, 默认 5),
            "orientation": str (可选),
            "size": str (可选),
        }

    Returns:
        {
            "query": str,
            "images": [
                {
                    "id": int,
                    "url": str,              # 原图 URL
                    "thumbnail": str,        # 缩略图 URL
                    "medium": str,           # 中等尺寸 URL
                    "width": int,
                    "height": int,
                    "photographer": str,
                    "photographer_url": str,
                    "alt": str,
                    "pexels_url": str,       # Pexels 页面链接
                }
            ],
            "total_results": int,
            "license": str,
        }
    """
    query = params.get("query", "").strip()
    count = min(params.get("count", 5), 15)
    orientation = params.get("orientation")
    size = params.get("size")

    if not query:
        return {"error": "搜索关键词不能为空"}

    if not PEXELS_API_KEY:
        return {
            "error": "未配置 PEXELS_API_KEY 环境变量。"
            "请在 .env 文件中添加: PEXELS_API_KEY=your_api_key。"
            "可在 https://www.pexels.com/api/ 免费申请。"
        }

    # 构建请求参数
    api_params: dict[str, Any] = {
        "query": query,
        "per_page": count,
        "locale": "zh-CN",
    }
    if orientation:
        api_params["orientation"] = orientation
    if size:
        api_params["size"] = size

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(
                PEXELS_API_URL,
                params=api_params,
                headers={"Authorization": PEXELS_API_KEY},
            )
            resp.raise_for_status()
            data = resp.json()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": "Pexels API Key 无效，请检查 PEXELS_API_KEY 配置"}
        return {"error": f"Pexels API 错误: HTTP {e.response.status_code}"}
    except httpx.TimeoutException:
        return {"error": f"Pexels API 请求超时（{REQUEST_TIMEOUT}秒）"}
    except Exception as e:
        logger.exception(f"[image_search] 请求失败: {e}")
        return {"error": f"图片搜索失败: {str(e)}"}

    # 解析结果
    images = []
    for photo in data.get("photos", []):
        src = photo.get("src", {})
        images.append({
            "id": photo.get("id"),
            "url": src.get("original", ""),
            "thumbnail": src.get("tiny", ""),
            "medium": src.get("medium", ""),
            "large": src.get("large", ""),
            "width": photo.get("width"),
            "height": photo.get("height"),
            "photographer": photo.get("photographer", ""),
            "photographer_url": photo.get("photographer_url", ""),
            "alt": photo.get("alt", ""),
            "pexels_url": photo.get("url", ""),
        })

    total = data.get("total_results", 0)

    logger.info(f"[image_search] 搜索 '{query}': 找到 {total} 张，返回 {len(images)} 张")

    return {
        "query": query,
        "images": images,
        "total_results": total,
        "result_count": len(images),
        "license": "Pexels License (免费使用，无需署名，但建议注明摄影师)",
    }
