"""Shared helpers for presentation context layering and evidence preparation."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import chat as llm_chat
from app.models.tables import Asset, TaskMessage
from app.tools.fetch_url import execute as fetch_url_execute
from app.tools.parse_document import execute as parse_document_execute
from app.tools.web_search import execute as web_search_execute

MAX_ATTACHMENT_COUNT = 4
MAX_REFERENCE_URL_COUNT = 4
MAX_ATTACHMENT_CHARS = 6000
MAX_RESEARCH_QUERY_COUNT = 3
MAX_SEARCH_RESULTS_PER_QUERY = 4
MAX_SUPPLEMENTAL_RESEARCH_MATERIALS = 4
MATERIAL_EXCERPT_LIMIT = 1200

RESEARCH_SUMMARY_SYSTEM_PROMPT = """你是 Web Deck 生成前的研究总监。
在正式规划 deck 之前，你需要把用户 brief、上传附件、给定链接和补充检索结果整合成一份研究摘要。

输出严格 JSON，格式如下：
{
    "overview": "一句话总览判断",
    "key_findings": ["关键发现1", "关键发现2"],
    "planning_focus": ["规划应优先展开的角度1", "角度2"],
    "open_questions": ["仍待确认的问题1", "问题2"],
    "source_highlights": ["attachment-1: 为什么重要", "research-1: 为什么重要"]
}

要求：
1. 只能基于当前输入材料，不要编造事实。
2. 信息不足时，明确指出缺口。
3. planning_focus 必须能直接指导后续 deck 结构设计。
4. source_highlights 仅用于帮助 planner 理解材料重要性，不可替代 evidence_refs。
不要输出 Markdown 或代码块。"""

ARTIFACT_PATTERN = re.compile(
    r"<general-artifact\s+type=\"[^\"]+\">[\s\S]*?</general-artifact>",
    re.IGNORECASE,
)
ATTACHMENT_PATTERN = re.compile(
    r"\[附件:\s*(?P<filename>.+?)\s*\((?:Asset ID:\s*[^,]+,\s*URL:\s*[^)]+|[^)]+)\)\]"
)


def _collapse_text(content: str, limit: int = 220) -> str:
    text = ARTIFACT_PATTERN.sub(" ", str(content or ""))
    text = ATTACHMENT_PATTERN.sub(lambda match: f"附件:{match.group('filename')}", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _dedupe_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _normalize_url(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = "https://" + text
    return text


def _build_synthetic_asset_id(file_path: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, file_path))


def _safe_json_object(raw_content: str) -> dict[str, Any] | None:
    text = str(raw_content or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _material_excerpt(material: dict[str, Any], limit: int = MATERIAL_EXCERPT_LIMIT) -> str:
    return _collapse_text(str(material.get("content") or ""), limit=limit)


def _build_research_queries(brief: dict[str, Any]) -> list[str]:
    topic = str(brief.get("topic") or "").strip()
    if not topic:
        return []

    must_include = [
        str(item).strip()
        for item in (brief.get("must_include") or [])
        if str(item).strip()
    ][:2]
    goal = str(brief.get("goal") or "").strip()
    current_year = datetime.now(timezone.utc).year

    queries = [
        f"{topic} {current_year} 现状 数据 趋势",
        f"{topic} 案例 风险 路线图",
    ]

    if must_include:
        queries.append(f"{topic} {' '.join(must_include)}")
    elif goal:
        queries.append(f"{topic} {goal[:24]} 实践")

    return _dedupe_keep_order([query.strip() for query in queries if query.strip()])[:MAX_RESEARCH_QUERY_COUNT]


def _should_run_supplemental_research(brief: dict[str, Any]) -> bool:
    # 如果已有 pre_research 内容（来自 subagent），跳过重复的补充研究
    pre_research = brief.get("pre_research") if isinstance(brief.get("pre_research"), list) else []
    has_substantial_pre_research = any(
        isinstance(entry, dict) and len(str(entry.get("content") or "").strip()) > 200
        for entry in pre_research
    )
    if has_substantial_pre_research:
        return False
    if str(brief.get("topic") or "").strip():
        return True
    return False


def _material_prompt_payload(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for material in materials[: MAX_ATTACHMENT_COUNT + MAX_REFERENCE_URL_COUNT + MAX_SUPPLEMENTAL_RESEARCH_MATERIALS]:
        payload.append(
            {
                "material_id": str(material.get("material_id") or "").strip(),
                "label": str(material.get("filename") or material.get("material_id") or "").strip(),
                "source_type": str(material.get("source_type") or "attachment"),
                "url": str(material.get("url") or "").strip(),
                "error": str(material.get("error") or "").strip(),
                "content": _collapse_text(str(material.get("content") or ""), limit=1200),
                "metadata": material.get("metadata") or {},
            }
        )
    return payload


def _merge_materials(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for material in [*primary, *secondary]:
        material_id = str(material.get("material_id") or "").strip()
        normalized_url = _normalize_url(str(material.get("url") or ""))
        key = (material_id, normalized_url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        merged.append(material)
    return merged


def _fallback_research_summary(
    brief: dict[str, Any],
    materials: list[dict[str, Any]],
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    attachment_loaded = int(diagnostics.get("attachment_loaded") or 0)
    attachment_total = int(diagnostics.get("attachment_total") or 0)
    reference_loaded = int(diagnostics.get("reference_url_loaded") or 0)
    reference_total = int(diagnostics.get("reference_url_total") or 0)
    supplemental = int(diagnostics.get("supplemental_research_count") or 0)

    key_findings = [
        f"{str(material.get('filename') or material.get('material_id') or '材料')}: {_material_excerpt(material, limit=140)}"
        for material in materials
        if not material.get("error") and _material_excerpt(material, limit=140)
    ][:3]

    planning_focus = [
        str(item).strip()
        for item in (brief.get("must_include") or [])
        if str(item).strip()
    ][:4]
    if not planning_focus:
        planning_focus = [
            "先给出结论与业务判断",
            "再展开证据、影响与实施路径",
            "最后闭环行动建议与风险缓释",
        ]

    open_questions = [
        str(item).strip()
        for item in diagnostics.get("warnings") or []
        if str(item).strip()
    ][:3]
    if not open_questions:
        open_questions = [
            str(item).strip()
            for item in (brief.get("reference_urls") or [])
            if str(item).strip()
        ][:1]

    return {
        "overview": (
            f"已解析 {attachment_loaded}/{attachment_total} 个附件、"
            f"{reference_loaded}/{reference_total} 个给定链接，并补充 {supplemental} 个外部研究来源。"
        ),
        "key_findings": key_findings,
        "planning_focus": planning_focus,
        "open_questions": open_questions,
        "source_highlights": [
            f"{str(material.get('material_id') or '').strip()}: {str(material.get('filename') or material.get('material_id') or '材料')}"
            for material in materials[:4]
            if str(material.get("material_id") or "").strip()
        ],
    }


async def collect_task_attachments(
    session: AsyncSession,
    task_id: str,
    user_id: str,
) -> list[dict[str, Any]]:
    """Auto-collect all uploaded attachments from the task's history.

    Merges attachments from:
    1. Asset table (files uploaded during this task)
    2. Attachment references embedded in user messages
    """
    attachments: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # Source 1: Assets linked to this task
    result = await session.execute(
        select(Asset)
        .where(Asset.task_id == task_id)
        .where(Asset.source == "upload")
        .where(Asset.file_type.in_(["document", "code"]))
        .order_by(Asset.created_at.asc())
    )
    for asset in result.scalars().all():
        if not asset.file_url:
            continue
        key = asset.id
        if key in seen_keys:
            continue
        seen_keys.add(key)
        attachments.append({
            "asset_id": asset.id,
            "filename": asset.title,
            "file_url": asset.file_url,
            "file_type": asset.mime_type or asset.file_type,
        })

    # Source 2: Attachment references in user messages
    msg_result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.role == "user")
        .where(TaskMessage.is_compressed == False)  # noqa: E712
        .order_by(TaskMessage.created_at.asc())
    )
    for msg in msg_result.scalars().all():
        if not msg.content:
            continue
        for match in ATTACHMENT_PATTERN.finditer(msg.content):
            filename = match.group("filename")
            # Try to extract URL from the full match
            full_match = match.group(0)
            url_match = re.search(r"URL:\s*([^)\s]+)", full_match)
            asset_id_match = re.search(r"Asset ID:\s*([^,)\s]+)", full_match)
            file_url = url_match.group(1) if url_match else ""
            asset_id = asset_id_match.group(1) if asset_id_match else ""
            if not file_url:
                continue
            key = asset_id or file_url
            if key in seen_keys:
                continue
            seen_keys.add(key)
            attachments.append({
                "asset_id": asset_id,
                "filename": filename,
                "file_url": file_url,
                "file_type": "document",
            })

    return attachments[:MAX_ATTACHMENT_COUNT + 4]  # Allow up to 8 auto-collected attachments


async def collect_source_materials(brief: dict[str, Any]) -> list[dict[str, Any]]:
    materials: list[dict[str, Any]] = []

    attachments = brief.get("attachments") if isinstance(brief.get("attachments"), list) else []
    for attachment in attachments[:MAX_ATTACHMENT_COUNT]:
        file_path = str(
            attachment.get("file_url")
            or attachment.get("file_path")
            or ""
        ).strip()
        if not file_path:
            continue
        asset_id = str(attachment.get("asset_id") or "").strip() or _build_synthetic_asset_id(file_path)

        parsed = await parse_document_execute(
            {
                "asset_id": asset_id,
                "file_path": file_path,
                "max_chars": MAX_ATTACHMENT_CHARS,
                "index_chunks": False,
            }
        )
        if parsed.get("error"):
            materials.append(
                {
                    "material_id": f"attachment-{len(materials) + 1}",
                    "source_type": "attachment",
                    "asset_id": asset_id,
                    "filename": attachment.get("filename") or asset_id,
                    "error": parsed["error"],
                }
            )
            continue

        materials.append(
            {
                "material_id": f"attachment-{len(materials) + 1}",
                "source_type": "attachment",
                "asset_id": asset_id,
                "filename": attachment.get("filename") or asset_id,
                "file_type": attachment.get("file_type") or attachment.get("mime_type") or "unknown",
                "format": parsed.get("format") or "text",
                "content": str(parsed.get("content") or "").strip(),
                "truncated": bool(parsed.get("truncated")),
                "metadata": parsed.get("metadata") or {},
            }
        )

    reference_urls = brief.get("reference_urls") if isinstance(brief.get("reference_urls"), list) else []
    for raw_url in reference_urls[:MAX_REFERENCE_URL_COUNT]:
        url = str(raw_url or "").strip()
        if not url:
            continue

        fetched = await fetch_url_execute(
            {
                "url": url,
                "extract_mode": "article",
                "max_chars": MAX_ATTACHMENT_CHARS,
            }
        )
        if fetched.get("error"):
            materials.append(
                {
                    "material_id": f"web-{len(materials) + 1}",
                    "source_type": "url",
                    "url": url,
                    "filename": fetched.get("title") or url,
                    "error": fetched["error"],
                }
            )
            continue

        materials.append(
            {
                "material_id": f"web-{len(materials) + 1}",
                "source_type": "url",
                "url": fetched.get("url") or url,
                "filename": fetched.get("title") or url,
                "file_type": "webpage",
                "format": "article",
                "content": str(fetched.get("content") or "").strip(),
                "truncated": bool(fetched.get("truncated")),
                "metadata": {"char_count": fetched.get("char_count") or 0},
            }
        )

    return materials


async def collect_supplemental_research_materials(
    brief: dict[str, Any],
    existing_materials: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not _should_run_supplemental_research(brief):
        return []

    materials: list[dict[str, Any]] = []
    seen_urls = {
        _normalize_url(str(item.get("url") or ""))
        for item in existing_materials
        if _normalize_url(str(item.get("url") or ""))
    }
    seen_urls.update(
        {
            _normalize_url(str(item).strip())
            for item in (brief.get("reference_urls") or [])
            if str(item).strip()
        }
    )

    queries = _build_research_queries(brief)

    # 并发执行所有搜索查询
    search_tasks = [
        web_search_execute({"query": query, "max_results": MAX_SEARCH_RESULTS_PER_QUERY})
        for query in queries
    ]
    search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

    # 收集所有需要 fetch 的 URL
    fetch_items: list[tuple[str, str, str, str, int]] = []  # (url, title, snippet, query, rank)
    for query, searched in zip(queries, search_results_list):
        if isinstance(searched, Exception):
            continue
        results = searched.get("results") if isinstance(searched.get("results"), list) else []
        for rank, result in enumerate(results, start=1):
            url = _normalize_url(result.get("url") or "")
            title = str(result.get("title") or url or "补充研究来源").strip()
            snippet = str(result.get("snippet") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            fetch_items.append((url, title, snippet, query, rank))
            if len(fetch_items) >= MAX_SUPPLEMENTAL_RESEARCH_MATERIALS:
                break
        if len(fetch_items) >= MAX_SUPPLEMENTAL_RESEARCH_MATERIALS:
            break

    # 并发 fetch 所有 URL
    async def _fetch_one(url: str, title: str, snippet: str, query: str, rank: int) -> dict[str, Any]:
        fetched = await fetch_url_execute(
            {"url": url, "extract_mode": "article", "max_chars": MAX_ATTACHMENT_CHARS}
        )
        material_id = f"research-{rank}"
        if fetched.get("error") and not snippet:
            return {
                "material_id": material_id,
                "source_type": "research",
                "url": url,
                "filename": title,
                "error": fetched["error"],
                "metadata": {"search_query": query, "search_rank": rank, "search_source": "unknown"},
            }
        return {
            "material_id": material_id,
            "source_type": "research",
            "url": fetched.get("url") or url,
            "filename": fetched.get("title") or title,
            "file_type": "webpage",
            "format": "article" if not fetched.get("error") else "search_snippet",
            "content": str(fetched.get("content") or snippet).strip(),
            "truncated": bool(fetched.get("truncated")),
            "metadata": {
                "search_query": query,
                "search_rank": rank,
                "search_source": "unknown",
                "fetch_error": str(fetched.get("error") or "").strip(),
                "char_count": fetched.get("char_count") or 0,
            },
        }

    if fetch_items:
        fetch_tasks = [_fetch_one(*item) for item in fetch_items[:MAX_SUPPLEMENTAL_RESEARCH_MATERIALS]]
        fetched_materials = await asyncio.gather(*fetch_tasks, return_exceptions=True)
        for mat in fetched_materials:
            if isinstance(mat, Exception):
                continue
            # 重新编号 material_id
            mat["material_id"] = f"research-{len(materials) + 1}"
            materials.append(mat)

    return materials


def build_preparation_diagnostics(
    brief: dict[str, Any],
    materials: list[dict[str, Any]],
    supplemental_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    attachments = brief.get("attachments") if isinstance(brief.get("attachments"), list) else []
    reference_urls = brief.get("reference_urls") if isinstance(brief.get("reference_urls"), list) else []
    attachment_materials = [item for item in materials if str(item.get("source_type") or "") == "attachment"]
    url_materials = [item for item in materials if str(item.get("source_type") or "") == "url"]
    warnings: list[str] = []

    attachment_errors = [
        f"附件 {str(item.get('filename') or item.get('asset_id') or '未知文件')}: {str(item.get('error') or '').strip()}"
        for item in attachment_materials
        if str(item.get("error") or "").strip()
    ]
    url_errors = [
        f"链接 {str(item.get('filename') or item.get('url') or '未知链接')}: {str(item.get('error') or '').strip()}"
        for item in url_materials
        if str(item.get("error") or "").strip()
    ]
    warnings.extend(attachment_errors)
    warnings.extend(url_errors)

    return {
        "attachment_total": len(attachments[:MAX_ATTACHMENT_COUNT]),
        "attachment_loaded": sum(1 for item in attachment_materials if not item.get("error")),
        "reference_url_total": len(reference_urls[:MAX_REFERENCE_URL_COUNT]),
        "reference_url_loaded": sum(1 for item in url_materials if not item.get("error")),
        "supplemental_research_count": sum(
            1 for item in (supplemental_materials or []) if not str(item.get("error") or "").strip()
        ),
        "warnings": warnings,
    }


async def build_research_summary(
    brief: dict[str, Any],
    context_layers: dict[str, Any],
    materials: list[dict[str, Any]],
    *,
    diagnostics: dict[str, Any],
    task_id: str,
    model: str | None = None,
) -> dict[str, Any]:
    prompt = json.dumps(
        {
            "brief": {
                "topic": brief.get("topic"),
                "title": brief.get("title"),
                "audience": brief.get("audience"),
                "goal": brief.get("goal"),
                "must_include": brief.get("must_include") or [],
                "notes": brief.get("notes"),
            },
            "context_layers": context_layers,
            "diagnostics": diagnostics,
            "materials": _material_prompt_payload(materials),
        },
        ensure_ascii=False,
    )
    try:
        response = await llm_chat(
            system=RESEARCH_SUMMARY_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            model=model,
            task_id=task_id,
        )
        parsed = _safe_json_object(response.content or "")
        if parsed:
            return {
                "overview": str(parsed.get("overview") or "").strip(),
                "key_findings": [
                    str(item).strip()
                    for item in parsed.get("key_findings") or []
                    if str(item).strip()
                ][:4],
                "planning_focus": [
                    str(item).strip()
                    for item in parsed.get("planning_focus") or []
                    if str(item).strip()
                ][:4],
                "open_questions": [
                    str(item).strip()
                    for item in parsed.get("open_questions") or []
                    if str(item).strip()
                ][:4],
                "source_highlights": [
                    str(item).strip()
                    for item in parsed.get("source_highlights") or []
                    if str(item).strip()
                ][:4],
            }
    except Exception:
        pass

    return _fallback_research_summary(brief, materials, diagnostics)


async def prepare_planning_briefing(
    session: AsyncSession,
    task_id: str,
    brief: dict[str, Any],
    *,
    send_status: Callable[[str], Awaitable[None]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    if send_status is not None:
        await send_status("正在解析附件与链接，建立证据底座...")

    context_layers = await collect_task_context_layers(session, task_id)
    source_materials = await collect_source_materials(brief)

    # Inject pre_research materials from subagent results (code_analyst / researcher)
    pre_research_entries = brief.get("pre_research") if isinstance(brief.get("pre_research"), list) else []
    for idx, entry in enumerate(pre_research_entries, start=1):
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or "").strip()
        if not content:
            continue
        material: dict[str, Any] = {
            "material_id": f"pre-research-{idx}",
            "source_type": "pre_research",
            "filename": str(entry.get("title") or f"pre-research-{idx}").strip(),
            "content": content,
        }
        source_url = str(entry.get("source_url") or "").strip()
        if source_url:
            material["url"] = source_url
        query = str(entry.get("query") or "").strip()
        if query:
            material["metadata"] = {"query": query}
        source_materials.append(material)

    supplemental_materials: list[dict[str, Any]] = []
    if _should_run_supplemental_research(brief):
        if send_status is not None:
            await send_status("正在补充外部研究，交叉验证关键观点...")
        supplemental_materials = await collect_supplemental_research_materials(brief, source_materials)

    all_materials = _merge_materials(source_materials, supplemental_materials)
    diagnostics = build_preparation_diagnostics(brief, all_materials, supplemental_materials)

    if send_status is not None and diagnostics.get("warnings"):
        await send_status("材料准备提示：" + "；".join(str(item) for item in diagnostics["warnings"][:2]))

    if send_status is not None:
        await send_status("正在汇总研究结论，准备生成大纲...")

    research_summary = await build_research_summary(
        brief,
        context_layers,
        all_materials,
        diagnostics=diagnostics,
        task_id=task_id,
        model=model,
    )

    return {
        "context_layers": context_layers,
        "source_materials": all_materials,
        "evidence_catalog": build_evidence_catalog(all_materials),
        "research_summary": research_summary,
        "preparation_diagnostics": diagnostics,
    }


async def collect_task_context_layers(
    session: AsyncSession,
    task_id: str,
    *,
    max_messages: int = 32,
) -> dict[str, Any]:
    result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.is_compressed == False)  # noqa: E712
        .order_by(TaskMessage.created_at.desc())
        .limit(max_messages)
    )
    history = list(reversed(result.scalars().all()))

    user_goals: list[str] = []
    assistant_findings: list[str] = []
    open_questions: list[str] = []
    key_insights: list[str] = []
    data_findings: list[str] = []

    _INSIGHT_MARKERS = ("分析", "发现", "结论", "总结", "建议", "趋势", "数据显示",
                        "研究表明", "报告指出", "根据", "调研", "核心", "关键")
    _SKIP_MSG_TYPES = {"quality_entry", "thinking", "summary"}

    for message in history:
        if message.msg_type in _SKIP_MSG_TYPES:
            continue

        # Extract tool result content (parsed documents, search results)
        if message.role == "tool" and message.msg_type == "tool_result":
            tool_content = _collapse_text(message.content or "", limit=600)
            if tool_content and len(tool_content) > 30:
                tool_name = ""
                if message.tool_input and isinstance(message.tool_input, dict):
                    tool_name = str(message.tool_input.get("_tool_name") or "")
                if tool_name in ("parse_document", "web_search", "fetch_url"):
                    data_findings.append(tool_content)
            continue

        if message.role not in {"user", "assistant"}:
            continue

        if message.role == "user":
            compact = _collapse_text(message.content or "", limit=300)
            if not compact:
                continue
            user_goals.append(compact)
            if any(token in compact for token in ["?", "？", "待确认", "确认", "是否", "能否"]):
                open_questions.append(compact)
        else:
            # Use longer limit for assistant messages to capture analysis depth
            compact = _collapse_text(message.content or "", limit=500)
            if not compact:
                continue
            assistant_findings.append(compact)
            # Detect deep analysis / insight content
            if any(marker in compact for marker in _INSIGHT_MARKERS):
                key_insights.append(compact)

    user_goals = _dedupe_keep_order(user_goals)[-6:]
    assistant_findings = _dedupe_keep_order(assistant_findings)[-6:]
    open_questions = _dedupe_keep_order(open_questions)[-4:]
    key_insights = _dedupe_keep_order(key_insights)[-5:]
    data_findings = _dedupe_keep_order(data_findings)[-4:]

    summary_parts: list[str] = []
    if user_goals:
        summary_parts.append("用户目标/约束: " + "；".join(user_goals[:3]))
    if assistant_findings:
        summary_parts.append("已有沟通分析: " + "；".join(assistant_findings[:3]))
    if key_insights:
        summary_parts.append("关键洞察: " + "；".join(key_insights[:2]))
    if data_findings:
        summary_parts.append("数据发现: " + "；".join(data_findings[:2]))
    if open_questions:
        summary_parts.append("待确认项: " + "；".join(open_questions[:2]))

    return {
        "summary": " | ".join(summary_parts),
        "user_goals": user_goals,
        "assistant_findings": assistant_findings,
        "key_insights": key_insights,
        "data_findings": data_findings,
        "open_questions": open_questions,
        "framing_rule": (
            "对话上下文中的沟通分析结论和数据发现可作为deck内容的参考依据，但需标注来源为'对话分析'。"
            "纯用户指令和目标描述仅用于理解方向约束。"
        ),
    }


def build_evidence_catalog(materials: list[dict[str, Any]]) -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    for material in materials:
        material_id = str(material.get("material_id") or "").strip()
        if not material_id:
            continue
        full_content = str(material.get("content") or "").strip()
        catalog[material_id] = {
            "material_id": material_id,
            "label": str(material.get("filename") or material_id),
            "source_type": str(material.get("source_type") or "attachment"),
            "url": str(material.get("url") or "").strip(),
            "excerpt": _material_excerpt(material),
            "content": full_content[:4000] if full_content else "",
            "error": str(material.get("error") or "").strip(),
        }
    return catalog


def format_context_layers_for_prompt(context_layers: dict[str, Any] | None) -> str:
    context_layers = context_layers or {}
    lines: list[str] = []

    summary = str(context_layers.get("summary") or "").strip()
    if summary:
        lines.append(f"- 摘要: {summary}")

    user_goals = [str(item).strip() for item in context_layers.get("user_goals") or [] if str(item).strip()]
    if user_goals:
        lines.append("- 用户目标/约束: " + "；".join(user_goals[:4]))

    assistant_findings = [str(item).strip() for item in context_layers.get("assistant_findings") or [] if str(item).strip()]
    if assistant_findings:
        lines.append("- 已有沟通分析: " + "；".join(assistant_findings[:4]))

    key_insights = [str(item).strip() for item in context_layers.get("key_insights") or [] if str(item).strip()]
    if key_insights:
        lines.append("- 关键洞察（可用于deck内容）: " + "；".join(key_insights[:4]))

    data_findings = [str(item).strip() for item in context_layers.get("data_findings") or [] if str(item).strip()]
    if data_findings:
        lines.append("- 数据发现（来自附件/搜索解析）: " + "；".join(data_findings[:3]))

    open_questions = [str(item).strip() for item in context_layers.get("open_questions") or [] if str(item).strip()]
    if open_questions:
        lines.append("- 待确认项: " + "；".join(open_questions[:3]))

    framing_rule = str(context_layers.get("framing_rule") or "").strip()
    if framing_rule:
        lines.append(f"- 规则: {framing_rule}")

    return "\n".join(lines) if lines else "无"


def format_evidence_materials_for_prompt(materials: list[dict[str, Any]]) -> str:
    if not materials:
        return "无"

    lines: list[str] = []
    for material in materials[:MAX_ATTACHMENT_COUNT + MAX_REFERENCE_URL_COUNT + MAX_SUPPLEMENTAL_RESEARCH_MATERIALS]:
        material_id = str(material.get("material_id") or "").strip()
        if not material_id:
            continue
        label = str(material.get("filename") or material_id)
        source_type = str(material.get("source_type") or "attachment")
        error = str(material.get("error") or "").strip()
        if error:
            lines.append(f"- {material_id} | {label} | {source_type} | 解析失败: {error}")
            continue
        excerpt = _material_excerpt(material)
        lines.append(f"- {material_id} | {label} | {source_type} | 摘录: {excerpt or '无可用摘录'}")
    return "\n".join(lines) if lines else "无"


def format_evidence_refs_for_prompt(evidence_details: list[dict[str, Any]] | None) -> str:
    evidence_details = evidence_details or []
    if not evidence_details:
        return "当前无硬证据；不得捏造具体事实、业务案例或财务数字，如必须展示只能明确标注\u201c待确认\u201d或\u201c示意\u201d。"

    lines: list[str] = []
    for detail in evidence_details[:6]:
        material_id = str(detail.get("material_id") or "").strip()
        label = str(detail.get("label") or material_id)
        error = str(detail.get("error") or "").strip()
        if error:
            lines.append(f"{material_id} / {label}: 当前仅知解析失败（{error}），不可据此补写事实")
            continue
        # Use full content when available, fall back to excerpt
        content = str(detail.get("content") or "").strip()
        excerpt = str(detail.get("excerpt") or "").strip()
        display = content[:2000] if content else excerpt
        lines.append(f"{material_id} / {label}: {display or '无摘录'}")
    return "\n".join(lines)


def format_research_summary_for_prompt(research_summary: dict[str, Any] | None) -> str:
    research_summary = research_summary or {}
    lines: list[str] = []

    overview = str(research_summary.get("overview") or "").strip()
    if overview:
        lines.append(f"- 全景判断: {overview}")

    key_findings = [
        str(item).strip()
        for item in research_summary.get("key_findings") or []
        if str(item).strip()
    ]
    if key_findings:
        lines.append("- 关键发现: " + "；".join(key_findings[:4]))

    planning_focus = [
        str(item).strip()
        for item in research_summary.get("planning_focus") or []
        if str(item).strip()
    ]
    if planning_focus:
        lines.append("- 规划重点: " + "；".join(planning_focus[:4]))

    open_questions = [
        str(item).strip()
        for item in research_summary.get("open_questions") or []
        if str(item).strip()
    ]
    if open_questions:
        lines.append("- 待确认问题: " + "；".join(open_questions[:4]))

    source_highlights = [
        str(item).strip()
        for item in research_summary.get("source_highlights") or []
        if str(item).strip()
    ]
    if source_highlights:
        lines.append("- 关键来源提示: " + "；".join(source_highlights[:4]))

    return "\n".join(lines) if lines else "无"


def format_preparation_diagnostics_for_prompt(diagnostics: dict[str, Any] | None) -> str:
    diagnostics = diagnostics or {}
    if not diagnostics:
        return "无"

    lines = [
        (
            f"- 材料状态: 附件已解析 {int(diagnostics.get('attachment_loaded') or 0)}/"
            f"{int(diagnostics.get('attachment_total') or 0)}，给定链接已抓取 "
            f"{int(diagnostics.get('reference_url_loaded') or 0)}/"
            f"{int(diagnostics.get('reference_url_total') or 0)}，补充研究来源 "
            f"{int(diagnostics.get('supplemental_research_count') or 0)} 条"
        )
    ]

    warnings = [
        str(item).strip()
        for item in diagnostics.get("warnings") or []
        if str(item).strip()
    ]
    if warnings:
        lines.append("- 风险提示: " + "；".join(warnings[:3]))

    return "\n".join(lines) if lines else "无"