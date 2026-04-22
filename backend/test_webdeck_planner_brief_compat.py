from app.services.webdeck_runtime.contracts import DeckManifest, PageSpecEntry
from app.services.webdeck_runtime.planner import DeckPlanner


def test_planner_accepts_camel_case_webdeck_brief() -> None:
    planner = DeckPlanner()

    prompt = planner._build_planning_prompt(
        {
            "topic": "AI 客服改造方案",
            "audience": "管理层",
            "pageCount": 7,
            "extras": "强调 ROI 与实施节奏",
            "theme_id": "tech_dark",
            "tone": "专业、清晰",
            "must_include": ["执行摘要", "路线图"],
            "reference_urls": ["https://example.com/report"],
            "goal": "帮助管理层快速做决策",
        }
    )

    assert "**主题**: AI 客服改造方案" in prompt
    assert "**目标受众**: 管理层" in prompt
    assert "**期望页数**: 7 页" in prompt
    assert "**风格**: tech_dark / 专业、清晰" in prompt
    assert "**必须覆盖的内容**: 执行摘要；路线图" in prompt
    assert "**参考材料**: https://example.com/report" in prompt
    assert "**补充说明**: 强调 ROI 与实施节奏\n沟通目标: 帮助管理层快速做决策" in prompt


def test_planner_preserves_snake_case_webdeck_brief() -> None:
    planner = DeckPlanner()

    prompt = planner._build_planning_prompt(
        {
            "topic": "银行数字化转型",
            "audience": "董事会",
            "page_count": 9,
            "style": "executive_clean / restrained",
            "must_cover": "风险、路线图、预算",
            "materials": "附件 A\n附件 B",
            "extra": "突出阶段性目标",
        }
    )

    assert "**主题**: 银行数字化转型" in prompt
    assert "**目标受众**: 董事会" in prompt
    assert "**期望页数**: 9 页" in prompt
    assert "**风格**: executive_clean / restrained" in prompt
    assert "**必须覆盖的内容**: 风险、路线图、预算" in prompt
    assert "**参考材料**: 附件 A\n附件 B" in prompt
    assert "**补充说明**: 突出阶段性目标" in prompt


def test_planner_includes_context_layers_and_evidence_directory() -> None:
    planner = DeckPlanner()

    prompt = planner._build_planning_prompt(
        {
            "topic": "AI 客服改造方案",
            "audience": "管理层",
            "page_count": 8,
            "context_layers": {
                "summary": "用户目标/约束: 要突出 ROI 与实施顺序 | 已有沟通分析: 之前已经确认先做客服场景",
                "user_goals": ["要突出 ROI 与实施顺序"],
                "assistant_findings": ["之前已经确认先做客服场景"],
                "framing_rule": "对话上下文仅用于理解目标、约束和既有沟通结论，不可直接当作事实证据。",
            },
            "source_materials": [
                {
                    "material_id": "attachment-1",
                    "source_type": "attachment",
                    "filename": "方案说明.pdf",
                    "content": "项目已确认聚焦智能客服场景，首期目标为降低人工成本并缩短响应时延。",
                },
                {
                    "material_id": "web-2",
                    "source_type": "url",
                    "filename": "行业白皮书",
                    "content": "参考案例强调实施路线需分三阶段推进。",
                },
            ],
        }
    )

    assert "**对话上下文（仅作 framing，不可直接当证据）**:" in prompt
    assert "要突出 ROI 与实施顺序" in prompt
    assert "**证据目录（仅以下 material_id 可用于 evidence_refs）**:" in prompt
    assert "attachment-1 | 方案说明.pdf | attachment" in prompt
    assert "web-2 | 行业白皮书 | url" in prompt
    assert "**证据约束**: 具体事实、案例、数字和引用只能来自上面的证据目录；如果证据不足，允许暴露信息缺口，但不要编造。" in prompt


def test_planner_includes_research_summary_and_material_diagnostics() -> None:
    planner = DeckPlanner()

    prompt = planner._build_planning_prompt(
        {
            "topic": "AI 客服改造方案",
            "audience": "管理层",
            "page_count": 8,
            "research_summary": {
                "overview": "综合附件、给定链接和补充研究后，应先输出 ROI 判断，再展开实施路径。",
                "key_findings": ["首期聚焦客服场景", "治理口径必须前置统一"],
                "planning_focus": ["结论先行", "实施路径", "风险闭环"],
                "open_questions": ["缺少财务基线"],
                "source_highlights": ["attachment-1: 内部方案", "research-1: 行业研究"],
            },
            "preparation_diagnostics": {
                "attachment_total": 2,
                "attachment_loaded": 1,
                "reference_url_total": 1,
                "reference_url_loaded": 1,
                "supplemental_research_count": 2,
                "warnings": ["附件 董事会备忘录: 文件暂不可读"],
            },
        }
    )

    assert "**Pre-plan 研究综述（用于形成全景视图，不可直接当作 evidence_refs）**:" in prompt
    assert "- 全景判断: 综合附件、给定链接和补充研究后，应先输出 ROI 判断，再展开实施路径。" in prompt
    assert "- 规划重点: 结论先行；实施路径；风险闭环" in prompt
    assert "**材料准备状态**:" in prompt
    assert "附件已解析 1/2" in prompt
    assert "附件 董事会备忘录: 文件暂不可读" in prompt


def test_planner_finalize_manifest_adds_density_asset_and_dependency_contracts() -> None:
    planner = DeckPlanner()

    manifest = DeckManifest(
        title="AI 客服改造方案",
        pages=[
            PageSpecEntry(page_id="p01", title="封面", page_kind="cover"),
            PageSpecEntry(page_id="p02", title="执行摘要", page_kind="summary"),
            PageSpecEntry(page_id="p03", title="目标架构", page_kind="architecture"),
            PageSpecEntry(page_id="p04", title="价值测算", page_kind="chart_analysis"),
            PageSpecEntry(page_id="p05", title="实施路径", page_kind="roadmap"),
            PageSpecEntry(page_id="p06", title="下一步行动", page_kind="closing"),
            PageSpecEntry(page_id="p07", title="补充材料", page_kind="appendix"),
        ],
    )

    finalized = planner._finalize_manifest(
        manifest,
        {
            "topic": "AI 客服改造方案",
            "audience": "管理层",
        },
    )

    summary_page = finalized.pages[1]
    architecture_page = finalized.pages[2]
    chart_page = finalized.pages[3]
    roadmap_page = finalized.pages[4]
    closing_page = finalized.pages[5]
    appendix_page = finalized.pages[6]

    assert finalized.global_theme.density == "high"
    assert summary_page.content_requirements.min_points >= 4
    assert "metric_cards" in summary_page.content_requirements.must_include_blocks
    assert architecture_page.content_requirements.require_detailed_explanation is True
    assert architecture_page.asset_requirements[0].type == "diagram"
    assert architecture_page.asset_requirements[0].purpose
    assert architecture_page.asset_requirements[0].data_dimensions
    assert chart_page.asset_requirements[0].type == "chart"
    assert "标题" in chart_page.asset_requirements[0].required_elements
    assert chart_page.dependencies == []
    assert roadmap_page.dependencies == []
    assert closing_page.dependencies == ["p04", "p05"]
    assert appendix_page.dependencies == []
    assert finalized.toc == ["执行摘要", "目标架构", "价值测算", "实施路径", "下一步行动"]


def test_planner_rebuilds_toc_from_final_page_titles() -> None:
    planner = DeckPlanner()

    manifest = DeckManifest(
        title="AI 客服改造方案",
        toc=["错误目录项", "另一项"],
        pages=[
            PageSpecEntry(page_id="p01", title="封面", page_kind="cover"),
            PageSpecEntry(page_id="p02", title="执行摘要", page_kind="summary"),
            PageSpecEntry(page_id="p03", title="ROI 分析", page_kind="chart_analysis"),
            PageSpecEntry(page_id="p04", title="下一步行动", page_kind="closing"),
        ],
    )

    finalized = planner._finalize_manifest(
        manifest,
        {
            "topic": "AI 客服改造方案",
            "audience": "管理层",
        },
    )

    assert finalized.toc == ["执行摘要", "ROI 分析", "下一步行动"]