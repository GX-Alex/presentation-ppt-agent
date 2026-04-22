"""
Deck Planner — 规划器 (对齐 high.md §5.3.2)。
负责将用户 brief 转化为机器可读的 DeckManifest。
调用 LLM 生成结构化页面规格。
"""
import json
import logging
import re
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import chat as llm_chat
from app.services.presentation_briefing_service import (
    format_context_layers_for_prompt,
    format_evidence_materials_for_prompt,
    format_preparation_diagnostics_for_prompt,
    format_research_summary_for_prompt,
)
from app.services.webdeck_runtime.contracts import (
    AssetRequirement,
    ContentRequirements,
    DeckManifest,
    GlobalTheme,
    NarrativeContract,
    PageKind,
    PageSpecEntry,
)

logger = logging.getLogger(__name__)


DEFAULT_DESIGN_STYLE: str = (
    "视觉与美学风格（默认麦肯锡商业报告风格）：\n"
    "- 美学风格：科技极简主义，高信息密度，简洁、锐利、权威\n"
    "- 标题字体：衬线字体（Times New Roman 或 Garamond），传递专业质感\n"
    "- 数据/标签字体：无衬线字体（Arial 或 Roboto），确保可读性\n"
    "- 配色：白色背景 (#FFFFFF)；文字黑色 (#000000)；图表主色深宝蓝 (#0A2463)；"
    "灰阶辅助色 (#4A4A4A, #9E9E9E, #E0E0E0)\n"
    "- 图形：表格使用细发丝边框，图表使用精确矢量线条，禁止3D效果和阴影\n"
    "- 布局：每页必须有完整句子作为行动标题（So What结论）\n"
    "- 数据可视化：优先使用复杂图表（软件架构图、业务流程图、堆叠柱状图、"
    "瀑布图、马里梅科图）、详细数据表格、战略框架或2x2矩阵\n"
    "- 栏式布局：2-3栏多信息密度，模仿真实商业分析报告\n"
    "- 数据完整性：未知数字使用占位符 [Data: XX%]，不编造数据来源"
)


PLANNER_SYSTEM_PROMPT = """你是 Web Deck Planner，负责将用户需求转化为结构化的 DeckManifest JSON。

## 输出要求
输出一个标准 JSON 对象，严格按照以下 schema:

```json
{
  "title": "演示标题",
  "subtitle": "副标题描述",
  "global_theme": {
    "brand_mode": "executive_clean",
    "palette": "slate_cyan",
    "motion": "subtle",
    "density": "high",
    "accent_color": "#3b82f6",
    "bg_color": "#0f172a",
    "text_color": "#f1f5f9"
  },
  "toc": ["章节标题1", "章节标题2"],
  "pages": [
    {
      "page_id": "p01",
      "title": "页面标题",
      "role": "cover",
      "page_kind": "cover",
      "goal": "该页核心目标",
      "narrative_contract": {
        "core_message": "核心信息",
        "audience": "管理层",
                "tone": "professional"
      },
      "content_requirements": {
        "min_points": 0,
        "require_detailed_explanation": false,
        "min_card_blocks": 0,
        "min_visual_blocks": 1,
        "must_include_blocks": ["title_block"]
      },
      "asset_requirements": [
        {
          "type": "chart",
          "kind": "bar_chart",
          "description": "展示降本增效对比图",
          "purpose": "用量化结果支撑核心结论",
          "data_dimensions": ["阶段", "成本", "效率"],
          "required_elements": ["明确标题", "结论标注", "图例/坐标"],
          "caption": "图表结论说明"
        }
      ],
      "evidence_refs": [],
      "review_rules": ["不得出现与本页目标无关的信息"],
      "dependencies": ["p03"]
    }
  ]
}
```

## page_kind 可选值
cover, summary, toc, content, architecture, chart_analysis, roadmap, comparison, closing, appendix

## asset type 可选值
diagram, chart, text_block, image, icon

## 规划原则
1. 标准结构: 封面 -> 目录(可选) -> 执行摘要 -> 正文 -> 结尾
2. 总页数 8-15 页
3. 每页必须适配 16:9 单页展示，不依赖纵向滚动；单页控制在 2-6 个主视觉区块，内容充实的说明类页面可适当增加
4. 每页都要输出 content_requirements，明确最低信息量，而不是只给上限
5. 架构图页、图表页、路线图页、对比页必须添加细化后的 asset_requirements，写清 purpose、data_dimensions、required_elements、caption
6. dependencies 仅在页面确实依赖前页上下文、数据口径或结论时填写；独立页保持空数组以支持并行生成
7. review_rules 要写成可执行的硬规则，例如“必须有结论标注”“必须解释关键概念”

只输出 JSON，不要其他内容。"""


class DeckPlanner:
    """Deck 规划器 — 从 brief 生成 DeckManifest"""

    async def plan(
        self,
        session: AsyncSession,
        project_id: str,
        brief: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
    ) -> DeckManifest:
        """
        根据用户 brief 规划整份 deck 的结构。

        Args:
            session: 数据库会话
            project_id: 项目 ID
            brief: 包含 topic, audience, page_count, style 等的 brief
            send_fn: 状态推送回调
            model: LLM 模型

        Returns:
            DeckManifest 对象
        """
        user_prompt = self._build_planning_prompt(brief)

        logger.info(f"[Planner] 开始规划: project={project_id}")

        response = await llm_chat(
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            model=model,
            task_id=project_id,
        )

        manifest = self._parse_manifest(response.content, brief)

        logger.info(
            f"[Planner] 规划完成: project={project_id} "
            f"title={manifest.title} pages={len(manifest.pages)}"
        )

        return manifest

    def _build_planning_prompt(self, brief: dict) -> str:
        """构造规划提示词"""
        parts = ["请为以下需求规划一份 Web 演示稿:\n"]

        topic = brief.get("topic", "")
        if topic:
            parts.append(f"**主题**: {topic}")

        audience = brief.get("audience", "")
        if audience:
            parts.append(f"**目标受众**: {audience}")

        page_count = brief.get("page_count") or brief.get("pageCount") or brief.get("slide_count") or ""
        if page_count:
            parts.append(f"**期望页数**: {page_count} 页")

        style = brief.get("style") or " / ".join(
            value for value in [brief.get("theme_id"), brief.get("tone")] if value
        )
        if style:
            parts.append(f"**风格**: {style}")

        density = brief.get("density") or brief.get("detail_level") or "高信息密度，适配 16:9 单页展示"
        parts.append(f"**版式约束**: {density}")

        must_cover = brief.get("must_cover") or brief.get("must_include") or ""
        if isinstance(must_cover, list):
            must_cover = "；".join(str(item).strip() for item in must_cover if str(item).strip())
        if must_cover:
            parts.append(f"**必须覆盖的内容**: {must_cover}")

        context_prompt = format_context_layers_for_prompt(brief.get("context_layers") or {})
        if context_prompt != "无":
            parts.append("**对话上下文（仅作 framing，不可直接当证据）**:\n" + context_prompt)

        research_prompt = format_research_summary_for_prompt(brief.get("research_summary") or {})
        if research_prompt != "无":
            parts.append(
                "**Pre-plan 研究综述（用于形成全景视图，不可直接当作 evidence_refs）**:\n"
                + research_prompt
            )

        diagnostics_prompt = format_preparation_diagnostics_for_prompt(
            brief.get("preparation_diagnostics") or {}
        )
        if diagnostics_prompt != "无":
            parts.append("**材料准备状态**:\n" + diagnostics_prompt)

        source_materials = brief.get("source_materials") if isinstance(brief.get("source_materials"), list) else []
        if source_materials:
            parts.append(
                "**证据目录（仅以下 material_id 可用于 evidence_refs）**:\n"
                + format_evidence_materials_for_prompt(source_materials)
            )
            parts.append(
                "**证据约束**: 具体事实、案例、数字和引用只能来自上面的证据目录；如果证据不足，允许暴露信息缺口，但不要编造。"
            )
        else:
            materials = brief.get("materials") or brief.get("reference_urls") or ""
            if isinstance(materials, list):
                materials = "\n".join(str(item).strip() for item in materials if str(item).strip())
            if materials:
                parts.append(f"**参考材料**: {materials}")

        extra = brief.get("extra") or brief.get("extras") or ""
        goal = str(brief.get("goal") or "").strip()
        if goal:
            extra = f"{extra}\n沟通目标: {goal}".strip() if extra else f"沟通目标: {goal}"
        if extra:
            parts.append(f"**补充说明**: {extra}")

        # Design style: use user notes verbatim if provided, else fall back to default
        design_style = str(brief.get("notes") or "").strip()
        if not design_style:
            design_style = DEFAULT_DESIGN_STYLE
        parts.append(f"**设计风格要求**:\n{design_style}")

        return "\n".join(parts)

    def _parse_manifest(self, raw_content: str, brief: dict) -> DeckManifest:
        """解析 LLM 输出为 DeckManifest，包含容错处理"""
        json_str = self._extract_json(raw_content)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"[Planner] JSON 解析失败，使用回退 manifest: {e}")
            return self._fallback_manifest(brief)

        try:
            manifest = DeckManifest.from_dict(data)
        except Exception as e:
            logger.warning(f"[Planner] Manifest 构造失败，使用回退 manifest: {e}")
            return self._fallback_manifest(brief)

        return self._finalize_manifest(manifest, brief)

    def _extract_json(self, content: str) -> str:
        """从 LLM 输出中提取 JSON（可能被 markdown 代码块包裹）"""
        match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', content)
        if match:
            return match.group(1).strip()

        match = re.search(r'\{[\s\S]*\}', content)
        if match:
            return match.group(0).strip()

        return content.strip()

    def _finalize_manifest(self, manifest: DeckManifest, brief: dict) -> DeckManifest:
        """为解析后的 manifest 填充缺失契约，使其可直接进入调度与质检。"""
        topic = brief.get("topic", "演示文稿")
        audience = brief.get("audience", "管理层")

        if not manifest.title:
            manifest.title = topic
        if not manifest.subtitle:
            manifest.subtitle = f"面向{audience}的方案演示"

        theme = manifest.global_theme or GlobalTheme()
        if theme.density in {"", "medium"}:
            theme.density = "high"
        design_style = str(brief.get("notes") or "").strip()
        if not design_style:
            design_style = DEFAULT_DESIGN_STYLE
            # 同步默认麦肯锡配色 token，消除与 design_rules 文本描述的冲突：
            # DEFAULT_DESIGN_STYLE 明确指定白色背景/黑色文字/深宝蓝主色，
            # 若不同步 token，page_generator 会因【强制】bg_color 约束优先使用
            # LLM 生成的深色 token，导致页面风格与默认规范不符。
            theme.bg_color = "#FFFFFF"
            theme.text_color = "#000000"
            theme.accent_color = "#0A2463"
        theme.design_rules = design_style
        manifest.global_theme = theme

        for idx, page in enumerate(manifest.pages):
            if not page.page_id:
                page.page_id = f"p{idx + 1:02d}"
            if not page.title:
                page.title = f"第 {idx + 1} 页"
            if not page.role:
                page.role = page.page_kind or "content"
            if not page.goal:
                page.goal = page.narrative_contract.core_message or page.title
            if not page.narrative_contract.audience:
                page.narrative_contract.audience = audience
            if not page.narrative_contract.core_message:
                page.narrative_contract.core_message = page.goal

        for idx, page in enumerate(manifest.pages):
            page.content_requirements = self._merge_content_requirements(
                page.page_kind,
                page.content_requirements,
            )
            page.asset_requirements = self._normalize_asset_requirements(
                page.page_kind,
                page.asset_requirements,
                page.title,
                page.goal,
            )
            if not page.review_rules:
                page.review_rules = self._default_review_rules(page.page_kind)
            if not page.dependencies:
                page.dependencies = self._default_dependencies(manifest.pages, idx)
            else:
                valid_ids = {item.page_id for item in manifest.pages}
                deduped: list[str] = []
                for dep in page.dependencies:
                    if dep in valid_ids and dep != page.page_id and dep not in deduped:
                        deduped.append(dep)
                page.dependencies = deduped

        manifest.toc = self._build_canonical_toc(manifest.pages)

        return manifest

    def _build_canonical_toc(self, pages: list[PageSpecEntry]) -> list[str]:
        return [
            page.title
            for page in pages
            if page.page_kind not in {PageKind.COVER.value, PageKind.TOC.value, PageKind.APPENDIX.value}
        ]

    def _merge_content_requirements(
        self,
        page_kind: str,
        current: ContentRequirements,
    ) -> ContentRequirements:
        """将 page_kind 默认信息密度契约合并进页面规格。"""
        defaults = self._default_content_requirements(page_kind)
        base = ContentRequirements()

        return ContentRequirements(
            min_points=(
                defaults.min_points
                if current.min_points == base.min_points and defaults.min_points != base.min_points
                else current.min_points
            ),
            require_detailed_explanation=(
                defaults.require_detailed_explanation
                if current.require_detailed_explanation == base.require_detailed_explanation
                and defaults.require_detailed_explanation != base.require_detailed_explanation
                else current.require_detailed_explanation
            ),
            min_card_blocks=(
                defaults.min_card_blocks
                if current.min_card_blocks == base.min_card_blocks and defaults.min_card_blocks != base.min_card_blocks
                else current.min_card_blocks
            ),
            min_visual_blocks=(
                defaults.min_visual_blocks
                if current.min_visual_blocks == base.min_visual_blocks and defaults.min_visual_blocks != base.min_visual_blocks
                else current.min_visual_blocks
            ),
            must_include_blocks=current.must_include_blocks or defaults.must_include_blocks,
        )

    def _default_content_requirements(self, page_kind: str) -> ContentRequirements:
        if page_kind == PageKind.COVER.value:
            return ContentRequirements(
                min_points=0,
                min_card_blocks=0,
                min_visual_blocks=1,
                must_include_blocks=["title_block"],
            )
        if page_kind == PageKind.SUMMARY.value:
            return ContentRequirements(
                min_points=4,
                min_card_blocks=3,
                min_visual_blocks=1,
                must_include_blocks=["core_message", "metric_cards", "action_strip"],
            )
        if page_kind == PageKind.ARCHITECTURE.value:
            return ContentRequirements(
                min_points=4,
                require_detailed_explanation=True,
                min_card_blocks=2,
                min_visual_blocks=1,
                must_include_blocks=["architecture_diagram", "module_cards"],
            )
        if page_kind == PageKind.CHART_ANALYSIS.value:
            return ContentRequirements(
                min_points=3,
                require_detailed_explanation=True,
                min_card_blocks=1,
                min_visual_blocks=1,
                must_include_blocks=["chart", "insight_cards"],
            )
        if page_kind == PageKind.ROADMAP.value:
            return ContentRequirements(
                min_points=4,
                require_detailed_explanation=True,
                min_card_blocks=3,
                min_visual_blocks=1,
                must_include_blocks=["timeline", "phase_cards"],
            )
        if page_kind == PageKind.COMPARISON.value:
            return ContentRequirements(
                min_points=4,
                min_card_blocks=2,
                min_visual_blocks=1,
                must_include_blocks=["comparison_chart", "comparison_cards"],
            )
        if page_kind == PageKind.CLOSING.value:
            return ContentRequirements(
                min_points=3,
                min_card_blocks=2,
                must_include_blocks=["key_takeaways", "next_steps"],
            )
        if page_kind == PageKind.APPENDIX.value:
            return ContentRequirements(
                min_points=2,
                require_detailed_explanation=True,
                min_card_blocks=1,
                must_include_blocks=["reference_block"],
            )
        return ContentRequirements(
            min_points=3,
            min_card_blocks=2,
            must_include_blocks=["core_message", "point_cards"],
        )

    def _normalize_asset_requirements(
        self,
        page_kind: str,
        asset_requirements: list[AssetRequirement],
        title: str,
        goal: str,
    ) -> list[AssetRequirement]:
        defaults = self._default_asset_requirements(page_kind, title, goal)
        if not asset_requirements:
            return defaults

        template_by_type = {item.type: item for item in defaults}
        normalized = [
            self._merge_asset_requirement(req, template_by_type.get(req.type))
            for req in asset_requirements
        ]

        existing_types = {item.type for item in normalized}
        for default_req in defaults:
            if default_req.type not in existing_types and page_kind in {
                PageKind.ARCHITECTURE.value,
                PageKind.CHART_ANALYSIS.value,
                PageKind.ROADMAP.value,
                PageKind.COMPARISON.value,
            }:
                normalized.append(default_req)

        return normalized

    def _merge_asset_requirement(
        self,
        current: AssetRequirement,
        template: AssetRequirement | None,
    ) -> AssetRequirement:
        if not template:
            return current

        return AssetRequirement(
            type=current.type,
            kind=current.kind or template.kind,
            description=current.description or template.description,
            purpose=current.purpose or template.purpose,
            data_dimensions=current.data_dimensions or template.data_dimensions,
            required_elements=current.required_elements or template.required_elements,
            caption=current.caption or template.caption,
        )

    def _default_asset_requirements(
        self,
        page_kind: str,
        title: str,
        goal: str,
    ) -> list[AssetRequirement]:
        if page_kind == PageKind.SUMMARY.value:
            return [
                AssetRequirement(
                    type="text_block",
                    kind="metric_cards",
                    description="3-4 个关键指标或价值卡片",
                    purpose="帮助管理层在 15 秒内抓住核心收益",
                    required_elements=["指标值", "指标标签", "一句价值判断"],
                    caption=f"{title} 的关键摘要",
                )
            ]

        if page_kind == PageKind.ARCHITECTURE.value:
            return [
                AssetRequirement(
                    type="diagram",
                    kind="system_architecture",
                    description="展示系统边界、核心模块与关键数据流的架构图",
                    purpose=goal or "说明方案结构与控制点",
                    data_dimensions=["系统边界", "核心模块", "关键数据流"],
                    required_elements=["模块分层", "接口/数据流向", "关键控制点标注"],
                    caption="目标架构与关键控制点",
                )
            ]

        if page_kind == PageKind.CHART_ANALYSIS.value:
            return [
                AssetRequirement(
                    type="chart",
                    kind="comparison_bar",
                    description="展示核心指标对比或趋势变化的图表",
                    purpose=goal or "用量化结果支撑页面结论",
                    data_dimensions=["对比对象", "核心指标", "时间/阶段"],
                    required_elements=["标题", "图例/坐标", "结论标注"],
                    caption="核心指标对比与结论说明",
                )
            ]

        if page_kind == PageKind.ROADMAP.value:
            return [
                AssetRequirement(
                    type="diagram",
                    kind="timeline",
                    description="展示阶段目标、时间线与关键交付物的路线图",
                    purpose=goal or "明确推进节奏与阶段成果",
                    data_dimensions=["阶段", "时间", "关键交付物"],
                    required_elements=["阶段节点", "时间轴", "里程碑/负责人"],
                    caption="分阶段推进路线图",
                )
            ]

        if page_kind == PageKind.COMPARISON.value:
            return [
                AssetRequirement(
                    type="chart",
                    kind="comparison_matrix",
                    description="展示方案/状态之间核心差异的对比图或矩阵",
                    purpose=goal or "帮助受众快速比较不同方案的优劣",
                    data_dimensions=["比较维度", "方案 A", "方案 B"],
                    required_elements=["比较维度", "差异高亮", "推荐结论"],
                    caption="关键差异对比",
                )
            ]

        if page_kind == PageKind.CLOSING.value:
            return [
                AssetRequirement(
                    type="text_block",
                    kind="action_cards",
                    description="总结结论与下一步动作的卡片块",
                    purpose="让收尾页形成明确行动闭环",
                    required_elements=["关键结论", "下一步动作", "责任/时间建议"],
                    caption="结论与下一步",
                )
            ]

        return []

    def _default_review_rules(self, page_kind: str) -> list[str]:
        common = [
            "必须适配 16:9 单页展示，禁止依赖纵向滚动才能读完主体内容",
            "核心结论必须在首屏可见区域内出现",
            "所有视觉块必须直接服务于页面目标，禁止装饰性堆砌",
        ]

        if page_kind == PageKind.ARCHITECTURE.value:
            return common + [
                "必须解释关键概念或模块职责，不能只给图不解释",
                "架构图必须标出边界、模块和关键流向",
            ]
        if page_kind == PageKind.CHART_ANALYSIS.value:
            return common + [
                "图表必须给出明确的比较维度与结论标注",
                "图表说明必须回扣页面核心结论",
            ]
        if page_kind == PageKind.ROADMAP.value:
            return common + [
                "路线图必须体现阶段目标、里程碑和节奏",
                "不得只列时间轴，必须解释阶段价值",
            ]
        if page_kind == PageKind.SUMMARY.value:
            return common + [
                "必须在 15 秒内让管理层理解主张与收益",
                "至少包含 3 个关键价值点或指标卡片",
            ]
        if page_kind == PageKind.CLOSING.value:
            return common + [
                "必须给出下一步动作，而不仅是重复总结",
            ]
        return common

    def _default_dependencies(self, pages: list[PageSpecEntry], index: int) -> list[str]:
        page = pages[index]
        previous_pages = pages[:index]
        if not previous_pages:
            return []

        previous_core_pages = [
            item.page_id
            for item in previous_pages
            if item.page_kind not in {PageKind.COVER.value, PageKind.TOC.value}
        ]

        # 默认依赖保持极小集合，避免缺省策略把 manifest 退化成近似串行执行。
        if page.page_kind == PageKind.CLOSING.value:
            return previous_core_pages[-2:] if len(previous_core_pages) >= 2 else previous_core_pages
        return []

    def _fallback_manifest(self, brief: dict) -> DeckManifest:
        """回退 manifest — 当 LLM 输出无法解析时使用最小可用结构"""
        topic = brief.get("topic", "演示文稿")
        audience = brief.get("audience", "管理层")

        pages = [
            PageSpecEntry(
                page_id="p01",
                title=topic,
                role="cover",
                page_kind="cover",
                goal="展示演示主题和品牌",
                narrative_contract=NarrativeContract(
                    core_message=topic,
                    audience=audience,
                    tone="professional",
                ),
            ),
            PageSpecEntry(
                page_id="p02",
                title="执行摘要",
                role="summary",
                page_kind="summary",
                goal="让受众在 30 秒内理解核心价值",
                narrative_contract=NarrativeContract(
                    core_message="核心价值概述",
                    audience=audience,
                    tone="firm",
                ),
            ),
            PageSpecEntry(
                page_id="p03",
                title="背景分析",
                role="content",
                page_kind="content",
                goal="阐述当前现状和问题",
                narrative_contract=NarrativeContract(
                    core_message="现状与挑战",
                    audience=audience,
                ),
            ),
            PageSpecEntry(
                page_id="p04",
                title="解决方案",
                role="content",
                page_kind="architecture",
                goal="展示目标架构和方案",
                narrative_contract=NarrativeContract(
                    core_message="方案架构与关键控制点",
                    audience=audience,
                ),
            ),
            PageSpecEntry(
                page_id="p05",
                title="价值分析",
                role="content",
                page_kind="chart_analysis",
                goal="用数据证明方案价值",
                narrative_contract=NarrativeContract(
                    core_message="量化价值论证",
                    audience=audience,
                ),
            ),
            PageSpecEntry(
                page_id="p06",
                title="实施路线图",
                role="content",
                page_kind="roadmap",
                goal="展示清晰的实施步骤和时间线",
                narrative_contract=NarrativeContract(
                    core_message="分阶段推进",
                    audience=audience,
                ),
            ),
            PageSpecEntry(
                page_id="p07",
                title="总结与建议",
                role="closing",
                page_kind="closing",
                goal="总结核心观点和行动建议",
                narrative_contract=NarrativeContract(
                    core_message="关键结论与下一步",
                    audience=audience,
                ),
            ),
        ]

        manifest = DeckManifest(
            title=topic,
            subtitle=f"面向{audience}的方案演示",
            global_theme=GlobalTheme(density="high"),
            toc=[page.title for page in pages],
            pages=pages,
        )
        return self._finalize_manifest(manifest, brief)
