"""
web_search 工具 — 网络搜索能力。
优先使用 Tavily API，失败时 fallback 到 DuckDuckGo HTML 搜索。
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
        "name": "web_search",
        "description": "搜索互联网获取最新信息。支持任意查询，返回搜索结果摘要。当你不确定某个事实或需要最新数据时使用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询关键词（建议使用英文以获得更好结果）",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大返回结果数量，默认 5",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
HTTPX_TIMEOUT = 15.0  # 秒


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """
    执行网络搜索。

    Args:
        params: {"query": str, "max_results"?: int}

    Returns:
        {"results": [{"title": str, "url": str, "snippet": str}], "source": str}
    """
    query = params.get("query", "")
    max_results = params.get("max_results", 5)

    if not query.strip():
        return {"error": "搜索查询不能为空"}

    # 优先尝试 Tavily
    if TAVILY_API_KEY:
        try:
            results = await _search_tavily(query, max_results)
            return {"results": results, "source": "tavily", "query": query}
        except Exception as e:
            logger.warning(f"[web_search] Tavily 搜索失败，fallback 到 DuckDuckGo: {e}")

    # Fallback: DuckDuckGo
    try:
        results = await _search_duckduckgo(query, max_results)
        return {"results": results, "source": "duckduckgo", "query": query}
    except Exception as e:
        logger.exception(f"[web_search] DuckDuckGo 搜索也失败: {e}")
        return {"error": f"搜索失败: {str(e)}", "query": query}


async def _search_tavily(query: str, max_results: int) -> list[dict[str, str]]:
    """通过 Tavily API 执行搜索。"""
    async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    # 如果 Tavily 提供了直接答案，放在第一条
    if data.get("answer"):
        results.append({
            "title": "Tavily AI 摘要",
            "url": "",
            "snippet": data["answer"],
        })

    for item in data.get("results", [])[:max_results]:
        results.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })

    return results


async def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
    """通过 DuckDuckGo HTML 页面抓取搜索结果（免费，无需 API Key）。"""
    async with httpx.AsyncClient(
        timeout=HTTPX_TIMEOUT,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        },
        follow_redirects=True,
    ) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
        )
        resp.raise_for_status()
        html = resp.text

    # 简单解析 DuckDuckGo HTML 结果
    results = _parse_ddg_html(html, max_results)
    return results


def _parse_ddg_html(html: str, max_results: int) -> list[dict[str, str]]:
    """从 DuckDuckGo HTML 搜索页面提取结果。"""
    import re

    results = []

    # 提取搜索结果块
    # DuckDuckGo HTML 版本的结果在 <div class="result"> 中
    result_blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*</div>',
        html,
        re.DOTALL,
    )

    if not result_blocks:
        # 备用: 提取所有链接和文本片段
        links = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )
        snippets = re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )

        for i, (url, title) in enumerate(links[:max_results]):
            snippet = snippets[i] if i < len(snippets) else ""
            results.append({
                "title": re.sub(r"<[^>]+>", "", title).strip(),
                "url": url,
                "snippet": re.sub(r"<[^>]+>", "", snippet).strip(),
            })
    else:
        for block in result_blocks[:max_results]:
            title_match = re.search(r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
            url_match = re.search(r'href="([^"]*)"', block)
            snippet_match = re.search(
                r'class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL
            )

            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
            url = url_match.group(1) if url_match else ""
            snippet = (
                re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip() if snippet_match else ""
            )

            if title or snippet:
                results.append({"title": title, "url": url, "snippet": snippet})

    # 如果 HTML 解析完全失败，返回提示
    if not results:
        results.append({
            "title": "搜索结果解析失败",
            "url": "",
            "snippet": f"DuckDuckGo 返回了内容但无法解析结构化结果。原始查询: {html[:200]}...",
        })

    return results
