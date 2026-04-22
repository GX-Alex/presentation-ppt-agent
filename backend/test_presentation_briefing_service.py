import asyncio
import json
from types import SimpleNamespace

from app.services import presentation_briefing_service as briefing_module


def test_collect_source_materials_uses_synthetic_asset_id_when_missing(monkeypatch) -> None:
    captured: list[dict] = []

    async def fake_parse_document(params: dict) -> dict:
        captured.append(params)
        return {
            "format": "markdown",
            "content": "附件中的核心结论：先做客服场景，再扩展到其他业务流程。",
            "truncated": False,
            "metadata": {"line_count": 2},
        }

    monkeypatch.setattr(briefing_module, "parse_document_execute", fake_parse_document)

    materials = asyncio.run(
        briefing_module.collect_source_materials(
            {
                "attachments": [
                    {
                        "filename": "strategy-notes.md",
                        "file_url": "/static/uploads/default/strategy-notes.md",
                        "file_type": "document",
                    }
                ]
            }
        )
    )

    assert len(materials) == 1
    assert captured[0]["asset_id"]
    assert materials[0]["asset_id"] == captured[0]["asset_id"]
    assert materials[0]["content"].startswith("附件中的核心结论")


def test_prepare_planning_briefing_runs_supplemental_research_before_planning(monkeypatch) -> None:
    async def fake_collect_context_layers(session, task_id, max_messages=16) -> dict:
        return {
            "summary": "用户目标/约束: 要突出 ROI 与实施路径",
            "user_goals": ["要突出 ROI 与实施路径"],
            "assistant_findings": [],
            "open_questions": [],
            "framing_rule": "对话上下文仅用于理解目标、约束和既有沟通结论，不可直接当作事实证据。",
        }

    async def fake_parse_document(params: dict) -> dict:
        return {
            "format": "pdf",
            "content": "附件证据显示首期应聚焦 AI 客服，并分阶段推进能力落地。",
            "truncated": False,
            "metadata": {"page_count": 6},
        }

    async def fake_fetch_url(params: dict) -> dict:
        url = params["url"]
        if "input.example.com" in url:
            return {
                "url": url,
                "title": "用户给定行业文章",
                "content": "给定链接强调转型项目需要先统一口径，再分阶段交付。",
                "char_count": 30,
                "truncated": False,
            }
        return {
            "url": url,
            "title": "补充行业报告",
            "content": "外部研究指出，ROI 证明、风险治理和路线图拆解应作为同一主线组织。",
            "char_count": 36,
            "truncated": False,
        }

    async def fake_web_search(params: dict) -> dict:
        return {
            "query": params["query"],
            "source": "duckduckgo",
            "results": [
                {
                    "title": "行业研究补充",
                    "url": "https://search.example.com/report",
                    "snippet": "行业研究摘要",
                }
            ],
        }

    async def fake_llm_chat(system: str, messages: list[dict], model: str | None, task_id: str):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "overview": "综合附件、给定链接和补充研究后，可以先围绕 ROI 结论，再展开实施路径与治理要求。",
                    "key_findings": ["应分阶段推进", "必须同步治理口径"],
                    "planning_focus": ["先结论页", "再实施路径", "最后风险与闭环动作"],
                    "open_questions": ["缺少精确财务基线"],
                    "source_highlights": ["attachment-1: 首期聚焦范围", "research-1: 行业共性拆解"],
                },
                ensure_ascii=False,
            )
        )

    statuses: list[str] = []

    async def fake_status(text: str) -> None:
        statuses.append(text)

    monkeypatch.setattr(briefing_module, "collect_task_context_layers", fake_collect_context_layers)
    monkeypatch.setattr(briefing_module, "parse_document_execute", fake_parse_document)
    monkeypatch.setattr(briefing_module, "fetch_url_execute", fake_fetch_url)
    monkeypatch.setattr(briefing_module, "web_search_execute", fake_web_search)
    monkeypatch.setattr(briefing_module, "llm_chat", fake_llm_chat)

    prepared = asyncio.run(
        briefing_module.prepare_planning_briefing(
            session=object(),
            task_id="task-1",
            brief={
                "topic": "AI 客服改造方案",
                "audience": "管理层",
                "goal": "帮助管理层快速决策",
                "must_include": ["ROI", "实施路径"],
                "attachments": [
                    {
                        "asset_id": "asset-1",
                        "filename": "内部方案.pdf",
                        "file_url": "/static/uploads/default/internal-plan.pdf",
                        "file_type": "document",
                    }
                ],
                "reference_urls": ["https://input.example.com/article"],
            },
            send_status=fake_status,
            model="test-model",
        )
    )

    assert statuses[0] == "正在解析附件与链接，建立证据底座..."
    assert "正在补充外部研究，交叉验证关键观点..." in statuses
    assert statuses[-1] == "正在汇总研究结论，准备生成大纲..."
    assert any(item["source_type"] == "research" for item in prepared["source_materials"])
    assert prepared["preparation_diagnostics"]["attachment_loaded"] == 1
    assert prepared["preparation_diagnostics"]["reference_url_loaded"] == 1
    assert prepared["preparation_diagnostics"]["supplemental_research_count"] == 1
    assert prepared["research_summary"]["overview"].startswith("综合附件、给定链接和补充研究后")
    assert "research-1" in prepared["evidence_catalog"]


def test_prepare_planning_briefing_injects_pre_research_materials(monkeypatch) -> None:
    """pre_research entries in the brief are injected as source materials with source_type='pre_research'."""

    async def fake_collect_context_layers(session, task_id, max_messages=16) -> dict:
        return {
            "summary": "",
            "user_goals": [],
            "assistant_findings": [],
            "key_insights": [],
            "data_findings": [],
            "open_questions": [],
            "framing_rule": "",
        }

    async def fake_llm_chat(system: str, messages: list[dict], model: str | None, task_id: str):
        return SimpleNamespace(
            content=json.dumps(
                {
                    "overview": "已整合预注入研究结果",
                    "key_findings": ["发现1", "发现2"],
                    "planning_focus": ["重点1"],
                    "open_questions": [],
                    "source_highlights": ["pre-research-1: 市场分析报告"],
                },
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(briefing_module, "collect_task_context_layers", fake_collect_context_layers)
    monkeypatch.setattr(briefing_module, "llm_chat", fake_llm_chat)

    pre_research = [
        {
            "title": "市场分析报告",
            "content": "2024年AI市场规模突破5000亿，年增长率超过30%。",
            "source_url": "https://analyst.example.com/ai-market-2024",
            "query": "AI市场规模 2024",
        },
        {
            "title": "竞品对比分析",
            "content": "主要竞品在功能覆盖度上存在明显短板，本产品具备差异化优势。",
        },
    ]

    prepared = asyncio.run(
        briefing_module.prepare_planning_briefing(
            session=object(),
            task_id="task-pre-research",
            brief={
                # No topic → no supplemental research triggered, simpler mocking
                "pre_research": pre_research,
            },
            model="test-model",
        )
    )

    source_materials = prepared["source_materials"]
    evidence_catalog = prepared["evidence_catalog"]

    # Both entries must appear in source_materials
    pr_materials = [m for m in source_materials if m.get("source_type") == "pre_research"]
    assert len(pr_materials) == 2, f"Expected 2 pre_research materials, got {len(pr_materials)}"

    # Check first entry fields
    first = next(m for m in pr_materials if m.get("filename") == "市场分析报告")
    assert first["content"] == "2024年AI市场规模突破5000亿，年增长率超过30%。"
    assert first["url"] == "https://analyst.example.com/ai-market-2024"
    assert first.get("metadata", {}).get("query") == "AI市场规模 2024"

    # Check second entry fields
    second = next(m for m in pr_materials if m.get("filename") == "竞品对比分析")
    assert second["content"] == "主要竞品在功能覆盖度上存在明显短板，本产品具备差异化优势。"

    # Both must have material_id assigned and appear in evidence_catalog
    for material in pr_materials:
        mid = material.get("material_id")
        assert mid, "pre_research material must have a material_id"
        assert mid in evidence_catalog, f"{mid} must be present in evidence_catalog"
        assert evidence_catalog[mid]["source_type"] == "pre_research"


def test_prepare_planning_briefing_skips_invalid_pre_research_entries(monkeypatch) -> None:
    """pre_research entries with no content or invalid type are silently skipped."""

    async def fake_collect_context_layers(session, task_id, max_messages=16) -> dict:
        return {
            "summary": "",
            "user_goals": [],
            "assistant_findings": [],
            "key_insights": [],
            "data_findings": [],
            "open_questions": [],
            "framing_rule": "",
        }

    async def fake_llm_chat(system: str, messages: list[dict], model: str | None, task_id: str):
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(briefing_module, "collect_task_context_layers", fake_collect_context_layers)
    monkeypatch.setattr(briefing_module, "llm_chat", fake_llm_chat)

    prepared = asyncio.run(
        briefing_module.prepare_planning_briefing(
            session=object(),
            task_id="task-skip-invalid",
            brief={
                "pre_research": [
                    {"title": "没有内容的条目"},            # missing content → skip
                    {"content": "   "},                    # blank content → skip
                    "not a dict",                          # wrong type → skip
                    None,                                  # None → skip
                    {"content": "有效内容，应当保留。"},    # valid → keep
                ],
            },
            model="test-model",
        )
    )

    pr_materials = [m for m in prepared["source_materials"] if m.get("source_type") == "pre_research"]
    assert len(pr_materials) == 1, f"Expected exactly 1 valid pre_research material, got {len(pr_materials)}"
    assert pr_materials[0]["content"] == "有效内容，应当保留。"


def test_prepare_planning_briefing_without_pre_research_is_unchanged(monkeypatch) -> None:
    """When pre_research is absent from the brief, no pre_research materials appear in the result."""

    async def fake_collect_context_layers(session, task_id, max_messages=16) -> dict:
        return {
            "summary": "",
            "user_goals": [],
            "assistant_findings": [],
            "key_insights": [],
            "data_findings": [],
            "open_questions": [],
            "framing_rule": "",
        }

    async def fake_llm_chat(system: str, messages: list[dict], model: str | None, task_id: str):
        return SimpleNamespace(content="{}")

    monkeypatch.setattr(briefing_module, "collect_task_context_layers", fake_collect_context_layers)
    monkeypatch.setattr(briefing_module, "llm_chat", fake_llm_chat)

    # Brief has no pre_research key at all
    prepared = asyncio.run(
        briefing_module.prepare_planning_briefing(
            session=object(),
            task_id="task-no-pre-research",
            brief={"title": "无预研究的简报"},
            model="test-model",
        )
    )

    pr_materials = [m for m in prepared["source_materials"] if m.get("source_type") == "pre_research"]
    assert len(pr_materials) == 0, "No pre_research materials expected when field is absent"