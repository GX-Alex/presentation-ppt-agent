"""
Page Orchestrator — 页面级编排器 (对齐 high.md §5.3.3)。
每页一个 orchestrator 实例，负责:
- 读取 PageSpec
- 判断需要的 lane 类型
- 生成各 lane 的输入
- 收集 lane 产物
- 组合成最终页面 HTML + PageBundle
- 发起页级 review

参考 claw-code 的 per-task orchestration 模式。
"""
import asyncio
import json
import logging
import re
import uuid
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import chat as llm_chat
from app.core.cancellation import CancellationToken, CooperativeCancelledError
from app.models.tables import DeckPage
from app.services.presentation_briefing_service import (
    format_context_layers_for_prompt,
    format_evidence_refs_for_prompt,
)
from app.services.webdeck_runtime.contracts import (
    PageStatus, LaneKind, LaneStatus, PageKind, AssetNode, PageBundle, ReviewReport,
)
from app.services.webdeck_runtime.editor_bundle import hydrate_page_bundle
from app.services.webdeck_runtime.state_store import deck_state_store
from app.services.webdeck_runtime.lane_runner import LaneRunner
from app.services.webdeck_runtime.reviewer import DeckReviewer

logger = logging.getLogger(__name__)

# 高价值页面类型 — 这些页面使用多 lane 编排 (对齐 high.md §10 第三优先级)
HIGH_VALUE_PAGE_KINDS = {
    PageKind.SUMMARY.value,
    PageKind.ARCHITECTURE.value,
    PageKind.CHART_ANALYSIS.value,
    PageKind.ROADMAP.value,
}

MAX_PAGE_REVIEW_RETRIES = 2
MIN_ACCEPTABLE_SCORE = 0.85

# ── Lane 超时配置（秒） ──
# Minimax LLM 单次调用最长约 120s (litellm timeout)，lane timeout 必须 > 120s 才能等到回包
LANE_TIMEOUT_DEFAULTS: dict[str, float] = {
    "narrative": 400.0,    # 普通页面叙事 lane（5-7k tokens @ 35 tok/s ≈ 200s，留 200s 缓冲）
    "chart": 600.0,        # 图表生成：SVG 复杂图表 + 多轮工具调用
    "diagram": 600.0,      # 图示生成：SVG 图示 + validation retry
    "asset": 300.0,        # 静态资产
    "layout": 300.0,       # 布局组合（单次 LLM，加 retry 缓冲）
}
DEFAULT_LANE_TIMEOUT = 400.0

# 高价值页面类型的 narrative lane 需要更长超时
# architecture/summary 类页面输出 token 多（10k+），35 tok/s 下需要 5+ 分钟
NARRATIVE_TIMEOUT_BY_PAGE_KIND: dict[str, float] = {
    "architecture": 800.0,
    "summary": 600.0,
    "chart_analysis": 600.0,
    "roadmap": 600.0,
}

# ── 页面生成提示词 ──
PAGE_GENERATION_PROMPT = """你是 Web Deck Page Generator，负责生成单页 Web 演示内容。

## 输出要求
输出一个完整的 HTML section，在 1280×720 的固定画布中渲染。使用现代 CSS（Flexbox/Grid）布局。

## 约束
1. 必须用 `<section data-page-id="{page_id}" class="deck-page">` 包裹，section 尺寸为 width:100%; height:100%
2. 【强制】背景色必须是 {bg_color}，文字色必须是 {text_color}，高亮色 {accent_color}；严禁使用已知与上述背景色不符的任何其他配色方案
2b. 【强制】标题字体（h1/h2/h3/h4）必须使用 {font_heading}；正文/说明字体必须使用 {font_body}；不得使用其他字体族
3. 核心信息: {core_message}
4. 页面目标: {goal}
5. 风格专业、视觉层次清晰
6. 使用 中文 内容
7. 页面必须适配 16:9 单页展示（画布 1280×720px），禁止依赖纵向滚动阅读主体内容；内容较多时，优先缩小字号或增大信息密度，而非删减文字
8. **内容密度 ≥70%**：页面可视区域必须有效利用，严禁大面积留白，信息量要充实
9. **设计风格约束**（以下规则在所有页面中强制执行）:
{design_style}

## 正确输出示例（McKinsey 风格 content 页 — 体现全部规则）

```html
<section data-page-id="p03" class="deck-page" style="width:100%;height:100%;background:#FFFFFF;padding:48px 56px;box-sizing:border-box;overflow:hidden;">
  <!-- RULE-5: So What 行动标题 — 完整句子结论 -->
  <h1 style="font-family:'Times New Roman',Garamond,Georgia,serif;font-size:26px;color:#000000;font-weight:700;margin:0 0 6px 0;">
    数字化转型使运营成本降低37%，投资回收期缩短至14个月
  </h1>
  <p style="font-family:Arial,Roboto,sans-serif;font-size:13px;color:#9E9E9E;margin:0 0 16px 0;">
    基于三个维度的综合量化分析 · 数据截至 2024Q3
  </p>
  <div style="width:60px;height:3px;background:#0A2463;margin-bottom:20px;"></div>
  <!-- RULE-7: 3栏 grid 高密度布局 -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;">
    <!-- RULE-4: 1px发丝边框 + 无阴影 -->
    <div style="border:1px solid #E0E0E0;border-radius:4px;padding:16px 18px;">
      <h3 style="font-family:'Times New Roman',serif;font-size:15px;color:#0A2463;margin:0 0 8px 0;">成本结构优化</h3>
      <p style="font-family:Arial,sans-serif;font-size:12px;color:#4A4A4A;line-height:1.6;margin:0;">
        人力成本降低 [Data: XX%]，IT运维支出减少 [Data: XX%]
      </p>
      <table style="width:100%;border-collapse:collapse;margin-top:10px;font-family:Arial,sans-serif;font-size:11px;">
        <tr><th style="border-bottom:1px solid #E0E0E0;padding:4px 0;text-align:left;color:#9E9E9E;">指标</th>
            <th style="border-bottom:1px solid #E0E0E0;padding:4px 0;text-align:right;color:#9E9E9E;">变化</th></tr>
        <tr><td style="padding:4px 0;color:#000000;">人力成本</td>
            <td style="padding:4px 0;text-align:right;color:#0A2463;font-weight:600;">-[Data: XX%]</td></tr>
      </table>
    </div>
    <!-- 第2/3栏结构相同，省略 -->
  </div>
</section>
```
↑ 关键模式：So What完整句子标题 · 3栏grid · 衬线标题+无衬线正文 · 白底+深宝蓝 · 1px细边框无阴影 · [Data:XX%]占位符

## P1: 全局组件库（可直接使用，无需自定义 CSS）

Shell 已注入如下 .s- 前缀工具类，**优先使用这些类替代重复的内联样式**：

| 类名 | 用途 |
|------|------|
| `.s-card` | 半透明卡片（带边框、圆角） |
| `.s-card-hover` | 卡片 hover 动效 |
| `.s-grid-2/3/4` | 2/3/4 列等宽网格 |
| `.s-flex` | 水平 flex 行 |
| `.s-flex-col` | 垂直 flex 列 |
| `.s-alert` | 左边框强调块（默认蓝色） |
| `.s-alert-warn/error/success` | 警告/错误/成功色变体 |
| `.s-badge` | 小型标签徽章 |
| `.s-code` | 代码行内片段 |
| `.s-stat` + `.s-stat-value` + `.s-stat-label` | 大数字统计卡片 |
| `.s-table` | 表格样式 |
| `.s-divider` | 分隔线 |

CSS 变量：`--accent`（主色调）、`--bg`（背景色）、`--text`（文字色）均已在 :root 中定义，可直接用于内联样式。

## P1: Iconify 图标库

Shell 已通过 CDN 加载 Iconify，**可直接使用图标 Web Component**，无需额外引入：

```html
<iconify-icon icon="mdi:check-circle" style="font-size:20px;color:#22c55e;"></iconify-icon>
<iconify-icon icon="mdi:arrow-right" width="16" height="16"></iconify-icon>
```

推荐图标前缀：`mdi:` (Material Design) / `ph:` (Phosphor) / `tabler:` (Tabler)
常用图标：`mdi:check-circle`、`mdi:alert`、`mdi:lightbulb`、`mdi:trending-up`、`mdi:users`、`mdi:code-braces`、`mdi:database`、`mdi:rocket-launch`

## 页面类型: {page_kind}
## 页面标题: {title}

{extra_instructions}

## 禁止事项（违反将导致页面被拒绝重生成）
【禁止】不要输出完整 HTML 文档（禁止 <!DOCTYPE>、<html>、<head>、<body> 标签）——只输出单个 <section> 片段
【禁止】不要使用 <slide> 或任何自创非标准 HTML 标签——只用标准 <section> 标签
【禁止】不要回显输入的 brief / 规格 JSON——必须生成渲染用 HTML 内容

只输出 HTML 代码，不要添加 ``` 标记或其他说明。"""


class PageOrchestrator:
    """
    页面编排器 — 单页生成的核心控制器。
    根据页面类型决定使用 单 agent 模式 还是 多 lane 模式。
    """

    def __init__(self):
        self.lane_runner = LaneRunner()
        self.reviewer = DeckReviewer()

    @staticmethod
    def _format_list(values: list[str] | None, fallback: str = "无") -> str:
        cleaned = [str(value).strip() for value in (values or []) if str(value).strip()]
        return "；".join(cleaned) if cleaned else fallback

    async def generate_page(
        self,
        session: AsyncSession,
        page: DeckPage,
        project_id: str,
        global_theme: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> PageBundle:
        """
        生成单页内容。

        高价值页面走多 lane 编排，普通页面走单 agent 直接生成。
        支持通过 cancellation_token 协作取消。
        """
        page_spec = page.page_spec or {}
        page_kind = page.page_kind or "content"

        # 检查取消状态
        if cancellation_token and cancellation_token.is_cancelled:
            raise CooperativeCancelledError(f"页面生成已取消: {cancellation_token.cancel_reason}")

        logger.info(
            f"[PageOrch] 开始生成页面: page_id={page.page_id} "
            f"kind={page_kind} title={page.title}"
        )

        project = await deck_state_store.get_project(session, project_id)
        page_spec = self._enrich_page_spec(page.page_spec or {}, (project.brief if project else {}) or {})
        page.page_spec = page_spec

        await deck_state_store.update_page_status(session, page.id, PageStatus.IN_PROGRESS.value)

        try:
            revision_guidance = ""
            best_bundle = None
            best_score = -1.0
            for attempt in range(MAX_PAGE_REVIEW_RETRIES + 1):
                if attempt > 0:
                    await deck_state_store.update_page_status(
                        session, page.id, PageStatus.RETRYING.value
                    )

                bundle = await self._generate_page_bundle(
                    session=session,
                    page=page,
                    project_id=project_id,
                    global_theme=global_theme,
                    send_fn=send_fn,
                    model=model,
                    revision_guidance=revision_guidance,
                    cancellation_token=cancellation_token,
                )

                page.html = bundle.html
                await deck_state_store.save_page_html(
                    session,
                    page.id,
                    bundle.html,
                    bundle.to_dict(),
                    status=PageStatus.REVIEWING.value,
                )

                report = await self.reviewer.review_page(
                    session=session,
                    page=page,
                    project_id=project_id,
                    global_theme=global_theme,
                    model=model,
                )
                bundle.review = report

                await self._emit_review_event(
                    send_fn=send_fn,
                    project_id=project_id,
                    level="page",
                    target_id=page.page_id,
                    report=report,
                    retrying=(not report.passed and attempt < MAX_PAGE_REVIEW_RETRIES),
                )

                if report.passed:
                    # 即使通过审稿，若评分低于阈值仍触发重试以充分利用审稿意见
                    if report.score < MIN_ACCEPTABLE_SCORE and attempt < MAX_PAGE_REVIEW_RETRIES:
                        logger.info(
                            f"[PageOrch] 审稿通过但评分偏低 ({report.score:.2f} < {MIN_ACCEPTABLE_SCORE})，"
                            f"触发额外重试: page_id={page.page_id}, attempt={attempt}"
                        )
                        revision_guidance = self._build_revision_guidance(report)
                        if report.score > best_score:
                            best_score = report.score
                            best_bundle = bundle
                        continue

                    await deck_state_store.save_page_html(
                        session,
                        page.id,
                        bundle.html,
                        bundle.to_dict(),
                        status=PageStatus.COMPLETED.value,
                    )
                    await send_fn({
                        "type": "webdeck_page_ready",
                        "project_id": project_id,
                        "page_id": page.page_id,
                        "page_index": page.page_index,
                        "title": page.title,
                        "html": bundle.html,
                        "page_bundle": bundle.to_dict(),
                        "status": "completed",
                    })

                    logger.info(f"[PageOrch] 页面完成: page_id={page.page_id}")
                    return bundle

                revision_guidance = self._build_revision_guidance(report)
                # 记录最高分版本，供全部重试后的兜底使用
                if report.score > best_score:
                    best_score = report.score
                    best_bundle = bundle

            # 全部重试后仍未通过 — 先尝试 LLM 定向编辑修复溢出，再 CSS 兜底
            final_bundle = best_bundle if best_bundle is not None else bundle
            has_overflow = any(
                "16:9" in str(iss.get("message", "")) or "越界" in str(iss.get("message", ""))
                for iss in (report.issues if report else [])
            )
            if has_overflow:
                try:
                    logger.info(f"[PageOrch] 尝试 LLM 定向编辑修复溢出: page_id={page.page_id}")
                    edited_bundle = await self._auto_edit_html(page, final_bundle, report, global_theme, model)
                    # 快速渲染检查 (仅浏览器，不再调 LLM)
                    overflow_issues = await self.reviewer.check_page_overflow(edited_bundle.html)
                    still_overflow = any(
                        "16:9" in str(iss.get("message", "")) or "越界" in str(iss.get("message", ""))
                        or iss.get("level") == "error"
                        for iss in overflow_issues
                    )
                    if still_overflow:
                        final_bundle = self._apply_overflow_css_fix(edited_bundle)
                        logger.info(f"[PageOrch] LLM 编辑后仍有溢出，补充 CSS 修复: page_id={page.page_id}")
                    else:
                        final_bundle = edited_bundle
                        logger.info(f"[PageOrch] LLM 定向编辑成功修复溢出: page_id={page.page_id}")
                except Exception as e:
                    logger.warning(
                        f"[PageOrch] LLM 定向编辑失败({e})，回退 CSS 修复: page_id={page.page_id}"
                    )
                    final_bundle = self._apply_overflow_css_fix(final_bundle)

            final_bundle = hydrate_page_bundle(final_bundle)

            logger.warning(
                f"[PageOrch] 审稿 {MAX_PAGE_REVIEW_RETRIES + 1} 次未通过，接受最终稿: "
                f"page_id={page.page_id}, best_score={best_score:.2f}"
            )
            await deck_state_store.save_page_html(
                session, page.id, final_bundle.html, final_bundle.to_dict(),
                status=PageStatus.COMPLETED.value,
            )
            await send_fn({
                "type": "webdeck_page_ready",
                "project_id": project_id,
                "page_id": page.page_id,
                "page_index": page.page_index,
                "title": page.title,
                "html": final_bundle.html,
                "page_bundle": final_bundle.to_dict(),
                "status": "completed",
            })
            return final_bundle

        except CooperativeCancelledError as ce:
            logger.warning(f"[PageOrch] 页面已取消: page_id={page.page_id}: {ce.reason}")
            await deck_state_store.update_page_status(
                session, page.id, PageStatus.FAILED.value
            )
            await send_fn({
                "type": "webdeck_page_ready",
                "project_id": project_id,
                "page_id": page.page_id,
                "page_index": page.page_index,
                "title": page.title,
                "html": "",
                "status": "cancelled",
                "error": ce.reason,
            })
            raise

        except Exception as e:
            logger.exception(f"[PageOrch] 页面生成失败: page_id={page.page_id}: {e}")
            await deck_state_store.update_page_status(
                session, page.id, PageStatus.FAILED.value
            )
            await send_fn({
                "type": "webdeck_page_ready",
                "project_id": project_id,
                "page_id": page.page_id,
                "page_index": page.page_index,
                "title": page.title,
                "html": "",
                "status": "failed",
                "error": str(e),
            })
            raise

    async def _generate_page_bundle(
        self,
        session: AsyncSession,
        page: DeckPage,
        project_id: str,
        global_theme: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        revision_guidance: str = "",
        cancellation_token: CancellationToken | None = None,
    ) -> PageBundle:
        def _hydrate(bundle: PageBundle) -> PageBundle:
            return hydrate_page_bundle(bundle)

        if (page.page_kind or "content") in HIGH_VALUE_PAGE_KINDS:
            return _hydrate(await self._generate_with_lanes(
                session,
                page,
                project_id,
                global_theme,
                send_fn,
                model,
                revision_guidance,
                cancellation_token=cancellation_token,
            ))

        return _hydrate(await self._generate_simple(
            session,
            page,
            project_id,
            global_theme,
            send_fn,
            model,
            revision_guidance,
            cancellation_token=cancellation_token,
        ))

    async def _generate_simple(
        self,
        session: AsyncSession,
        page: DeckPage,
        project_id: str,
        global_theme: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        revision_guidance: str = "",
        cancellation_token: CancellationToken | None = None,
    ) -> PageBundle:
        """单 agent 直接生成（用于普通内容页）"""
        # 检查取消状态
        if cancellation_token and cancellation_token.is_cancelled:
            raise CooperativeCancelledError(f"页面生成已取消: {cancellation_token.cancel_reason}")

        page_spec = page.page_spec or {}
        nc = page_spec.get("narrative_contract", {})

        prompt = PAGE_GENERATION_PROMPT.format(
            page_id=page.page_id,
            accent_color=global_theme.get("accent_color", "#0A2463"),
            bg_color=global_theme.get("bg_color", "#FFFFFF"),
            text_color=global_theme.get("text_color", "#000000"),
            font_heading=global_theme.get("font_heading", "'Times New Roman', 'Garamond', Georgia, serif"),
            font_body=global_theme.get("font_body", "Arial, Roboto, 'Helvetica Neue', sans-serif"),
            core_message=nc.get("core_message", ""),
            goal=page_spec.get("goal", ""),
            page_kind=page.page_kind or "content",
            title=page.title or "",
            design_style=global_theme.get("design_rules", ""),
            extra_instructions=self._build_page_extra_instructions(page_spec, revision_guidance),
        )

        response = await llm_chat(
            system=prompt,
            messages=[{"role": "user", "content": f"请生成「{page.title}」页面的 HTML 内容。"}],
            model=model,
            task_id=project_id,
        )

        html = self._extract_html(response.content)
        html = self._normalize_page_html(html, page.page_id, global_theme)
        if html is None:
            nc = page_spec.get("narrative_contract", {})
            html = self._basic_page_html(page, global_theme, nc)
        html = self._apply_theme_shell(html, global_theme)

        return PageBundle(
            page_id=page.page_id,
            status="completed",
            html=html,
            css_tokens=global_theme,
        )

    async def _generate_with_lanes(
        self,
        session: AsyncSession,
        page: DeckPage,
        project_id: str,
        global_theme: dict,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        revision_guidance: str = "",
        cancellation_token: CancellationToken | None = None,
    ) -> PageBundle:
        """
        多 lane 编排生成（用于高价值页面）。
        对齐 high.md §7.1: 各 lane 并行执行 → layout_lane → review_lane。
        Phase 1: narrative lane 先执行（其他 lane 可能依赖其输出）。
        Phase 2: chart / diagram / asset lane 通过 asyncio.gather 并行执行。

        协作取消: 通过 cancellation_token 传播取消信号，每个 lane 有独立超时。
        """
        page_spec = page.page_spec or {}
        asset_reqs = page_spec.get("asset_requirements", [])

        # 1. 确定需要的 lane
        lane_plan = self._plan_lanes(page.page_id, page.page_kind, asset_reqs, revision_guidance)

        # 2. 创建 lane 记录
        lane_records: list[tuple[str, dict[str, Any], Any]] = []
        for planned_lane in lane_plan:
            lane_kind = str(planned_lane.get("lane_kind") or LaneKind.NARRATIVE.value)
            lane_input = dict(planned_lane.get("input") or {})
            lane = await deck_state_store.create_lane(
                session=session,
                page_db_id=page.id,
                project_id=project_id,
                lane_id=f"{page.page_id}_{lane_kind}_{uuid.uuid4().hex[:8]}",
                kind=lane_kind,
                input_data={
                    "page_spec": page_spec,
                    "global_theme": global_theme,
                    **lane_input,
                },
            )
            lane_records.append((lane_kind, lane_input, lane))

        # 3. 执行各 lane（Phase 1: narrative 先行，Phase 2: 其余并行）
        lane_outputs: list[dict[str, Any]] = []
        narrative_lanes = []
        other_lanes = []
        for entry in lane_records:
            if entry[0] == LaneKind.NARRATIVE.value:
                narrative_lanes.append(entry)
            else:
                other_lanes.append(entry)

        # Phase 1: Run narrative lane(s) first — other lanes may reference its output
        for lane_kind, lane_input, lane_record in narrative_lanes:
            # 检查取消状态
            if cancellation_token and cancellation_token.is_cancelled:
                raise CooperativeCancelledError(f"页面取消: {cancellation_token.cancel_reason}")

            _page_kind = page.page_kind or "content"
            lane_timeout = NARRATIVE_TIMEOUT_BY_PAGE_KIND.get(
                _page_kind, LANE_TIMEOUT_DEFAULTS.get(lane_kind, DEFAULT_LANE_TIMEOUT)
            )
            try:
                output = await asyncio.wait_for(
                    self.lane_runner.run_lane(
                        session=session,
                        lane=lane_record,
                        model=model,
                    ),
                    timeout=lane_timeout,
                )
                lane_outputs.append({
                    "lane_kind": lane_kind,
                    "lane_input": lane_input,
                    "output": output,
                })

                await send_fn({
                    "type": "webdeck_lane_status",
                    "project_id": project_id,
                    "page_id": page.page_id,
                    "lane_id": lane_record.lane_id,
                    "kind": lane_kind,
                    "status": "completed",
                })

            except asyncio.TimeoutError:
                logger.warning(
                    f"[PageOrch] Lane 超时: page={page.page_id} lane={lane_kind} "
                    f"timeout={lane_timeout}s"
                )
                await send_fn({
                    "type": "webdeck_lane_status",
                    "project_id": project_id,
                    "page_id": page.page_id,
                    "lane_id": lane_record.lane_id,
                    "kind": lane_kind,
                    "status": "failed",
                    "error": f"lane 超时 ({lane_timeout}s)",
                })
            except Exception as e:
                logger.warning(
                    f"[PageOrch] Lane 失败: page={page.page_id} lane={lane_kind}: {e}"
                )
                await send_fn({
                    "type": "webdeck_lane_status",
                    "project_id": project_id,
                    "page_id": page.page_id,
                    "lane_id": lane_record.lane_id,
                    "kind": lane_kind,
                    "status": "failed",
                    "error": str(e),
                })

        # Phase 2: Run remaining lanes (chart / diagram / asset) in parallel with per-lane timeout
        if other_lanes:
            # 检查取消状态
            if cancellation_token and cancellation_token.is_cancelled:
                raise CooperativeCancelledError(f"页面取消: {cancellation_token.cancel_reason}")

            async def _run_one_lane(lane_kind, lane_input, lane_record):
                from app.models.database import async_session as make_session
                lane_timeout = LANE_TIMEOUT_DEFAULTS.get(lane_kind, DEFAULT_LANE_TIMEOUT)
                async with make_session() as lane_session:
                    # 使用 wait_for 实现 per-lane 超时
                    output = await asyncio.wait_for(
                        self.lane_runner.run_lane(
                            session=lane_session,
                            lane=lane_record,
                            model=model,
                        ),
                        timeout=lane_timeout,
                    )
                    return lane_kind, lane_input, lane_record, output

            parallel_results = await asyncio.gather(
                *[_run_one_lane(lk, li, lr) for lk, li, lr in other_lanes],
                return_exceptions=True,
            )
            for idx, result in enumerate(parallel_results):
                lane_kind, lane_input, lane_record = other_lanes[idx]
                if isinstance(result, Exception):
                    # asyncio.TimeoutError.__str__() returns "" — log the type name as fallback
                    error_msg = str(result) or f"{type(result).__name__} (timeout={LANE_TIMEOUT_DEFAULTS.get(lane_kind, DEFAULT_LANE_TIMEOUT):.0f}s)"
                    logger.warning(
                        f"[PageOrch] Lane 失败: page={page.page_id} lane={lane_kind}: {error_msg}"
                    )
                    await send_fn({
                        "type": "webdeck_lane_status",
                        "project_id": project_id,
                        "page_id": page.page_id,
                        "lane_id": lane_record.lane_id,
                        "kind": lane_kind,
                        "status": "failed",
                        "error": error_msg,
                    })
                else:
                    _, _, _, output = result
                    lane_outputs.append({
                        "lane_kind": lane_kind,
                        "lane_input": lane_input,
                        "output": output,
                    })
                    await send_fn({
                        "type": "webdeck_lane_status",
                        "project_id": project_id,
                        "page_id": page.page_id,
                        "lane_id": lane_record.lane_id,
                        "kind": lane_kind,
                        "status": "completed",
                    })
                    # lane 失败不阻断整页，继续其他 lane

        # 4. Layout lane — 将各 lane 产物组合成最终页面
        html = await self._compose_page_html(
            page, global_theme, page_spec, lane_outputs, model, revision_guidance
        )
        html = self._apply_theme_shell(html, global_theme)

        # 5. 构建 PageBundle
        artifacts = []
        for lane_output in lane_outputs:
            kind = str(lane_output.get("lane_kind") or "asset")
            output = lane_output.get("output") or {}
            if output.get("asset"):
                artifacts.append(AssetNode(
                    kind=kind,
                    content=output.get("asset", ""),
                    metadata={
                        "lane_kind": kind,
                        **(output.get("metadata") or {}),
                    },
                ))

        return PageBundle(
            page_id=page.page_id,
            status="completed",
            html=html,
            css_tokens=global_theme,
            artifacts=artifacts,
        )

    def _plan_lanes(
        self,
        page_id: str,
        page_kind: str,
        asset_reqs: list[dict],
        revision_guidance: str,
    ) -> list[dict[str, Any]]:
        """根据页面类型和资产需求确定需要的 lane"""
        lanes: list[dict[str, Any]] = []

        # 所有高价值页面都需要 narrative lane
        lanes.append({
            "lane_kind": LaneKind.NARRATIVE.value,
            "input": {
                "focus": "narrative",
                "revision_guidance": revision_guidance,
            },
        })

        # 根据资产需求添加对应 lane
        for index, req in enumerate(asset_reqs):
            asset_type = req.get("type", "")
            if asset_type == "diagram":
                lanes.append({
                    "lane_kind": LaneKind.DIAGRAM.value,
                    "input": {
                        "focus": "diagram",
                        "asset_index": index,
                        "diagram_kind": req.get("kind", "architecture"),
                        "description": req.get("description", ""),
                        "purpose": req.get("purpose", ""),
                        "data_dimensions": req.get("data_dimensions", []),
                        "required_elements": req.get("required_elements", []),
                        "caption": req.get("caption", ""),
                        "revision_guidance": revision_guidance,
                    },
                })
            elif asset_type == "chart":
                lanes.append({
                    "lane_kind": LaneKind.CHART.value,
                    "input": {
                        "focus": "chart",
                        "asset_index": index,
                        "container_id": f"{page_id}_chart_{index + 1}",
                        "chart_kind": req.get("kind", "bar_chart"),
                        "description": req.get("description", ""),
                        "purpose": req.get("purpose", ""),
                        "data_dimensions": req.get("data_dimensions", []),
                        "required_elements": req.get("required_elements", []),
                        "caption": req.get("caption", ""),
                        "revision_guidance": revision_guidance,
                    },
                })
            elif asset_type == "image":
                lanes.append({
                    "lane_kind": LaneKind.ASSET.value,
                    "input": {
                        "focus": "asset",
                        "asset_index": index,
                        "description": req.get("description", ""),
                        "revision_guidance": revision_guidance,
                    },
                })

        return lanes

    async def _compose_page_html(
        self,
        page: DeckPage,
        global_theme: dict,
        page_spec: dict,
        lane_outputs: list[dict[str, Any]],
        model: str | None = None,
        revision_guidance: str = "",
    ) -> str:
        """将各 lane 的产出组合成最终页面 HTML"""
        if (page.page_kind or "content") == PageKind.CHART_ANALYSIS.value:
            return self._compose_chart_analysis_page(page, global_theme, lane_outputs)

        nc = page_spec.get("narrative_contract", {})
        cr = page_spec.get("content_requirements", {})
        review_rules = page_spec.get("review_rules", [])

        # 收集所有 lane 的内容片段
        parts = []
        for lane_output in lane_outputs:
            kind = str(lane_output.get("lane_kind") or "asset")
            lane_input = lane_output.get("lane_input") or {}
            output = lane_output.get("output") or {}
            content = output.get("content", "")
            if content:
                label = str(
                    lane_input.get("chart_kind")
                    or lane_input.get("diagram_kind")
                    or lane_input.get("description")
                    or kind
                )
                parts.append(f"<!-- {kind} lane output: {label} -->\n{content}")

        if not parts:
            # 如果所有 lane 都失败了，用基础模板
            return self._basic_page_html(page, global_theme, nc)

        # 调用 LLM 组合
        compose_prompt = f"""你是 Layout Composer，负责将多个内容片段组合成一个完整的 Web 演示 section。

## 约束
1. 用 `<section data-page-id="{page.page_id}" class="deck-page">` 包裹
2. 【强制】页面背景色必须是 {global_theme.get('bg_color', '#FFFFFF')}，严禁使用任何其他深色/浅色背景
3. 【强制】主文字色必须是 {global_theme.get('text_color', '#000000')}
4. 高亮/强调色: {global_theme.get('accent_color', '#0A2463')}
4b. 【强制】标题字体（h1/h2/h3）使用 {global_theme.get('font_heading', "'Times New Roman', Georgia, serif")}；正文字体使用 {global_theme.get('font_body', "Arial, Roboto, sans-serif")}
5. 页面标题: {page.title}
6. 使用 Flexbox/Grid 排版，保证视觉层次
7. 所有样式内联
8. 页面必须适配 16:9 单页展示，禁止依赖纵向滚动
9. 至少保留 {cr.get('min_points', 3)} 个核心观点/信息点
10. 至少包含 {cr.get('min_card_blocks', 0)} 个卡片块、{cr.get('min_visual_blocks', 0)} 个视觉块
11. 必须包含的区块: {self._format_list(cr.get('must_include_blocks'))}
12. 是否需要详细概念解释: {'需要' if cr.get('require_detailed_explanation') else '不需要'}
13. 审稿硬规则: {self._format_list(review_rules)}
14. 页面目标: {page_spec.get('goal', '')}
15. 核心信息: {nc.get('core_message', '')}
16. 上一轮修改指导: {revision_guidance or '无'}
17. 输入中出现的每一个 `deck-visual-wrapper` / `<script>` / `<svg>` 片段都必须保留一次，不得删除或替换为空占位
18. 如果输入中有多个 chart/diagram 片段，必须全部落在最终页面中，并保持各自的容器 ID 与脚本逻辑不被改写
19. 如果页面涉及 ROI、回收期、净收益、成本节省等财务数字，允许修正原始文案中的数字，但最终页面中的全部财务口径必须可自洽，并显式写出关键假设
20. 设计风格约束（以下规则强制执行）: {global_theme.get('design_rules', '')}

## 内容片段
{chr(10).join(parts)}

将以上片段组合成一个视觉效果优秀的单页 HTML section。

## 禁止事项（违反将导致页面被拒绝重生成）
【禁止】不要输出完整 HTML 文档（禁止 <!DOCTYPE>、<html>、<head>、<body> 标签）——只输出单个 <section> 片段
【禁止】不要使用 <slide> 或任何自创非标准 HTML 标签——只用标准 <section> 标签
【禁止】不要回显输入的 brief / 规格 JSON

只输出 HTML。"""

        response = await llm_chat(
            system=compose_prompt,
            messages=[{"role": "user", "content": "请组合以上内容片段。"}],
            model=model,
        )

        if not response or not getattr(response, "content", None):
            logger.warning(f"[PageOrch] Layout Compose LLM 返回空响应: page={page.page_id}")
            return self._basic_page_html(page, global_theme, nc)

        raw_html = self._extract_html(response.content)
        normalized = self._normalize_page_html(raw_html, page.page_id, global_theme)
        if normalized is None:
            return self._basic_page_html(page, global_theme, nc)
        return normalized

    def _compose_chart_analysis_page(
        self,
        page: DeckPage,
        global_theme: dict,
        lane_outputs: list[dict[str, Any]],
    ) -> str:
        summary_blocks: list[str] = []
        visual_blocks: list[str] = []
        for lane_output in lane_outputs:
            lane_kind = str(lane_output.get("lane_kind") or "")
            content = str((lane_output.get("output") or {}).get("content") or "").strip()
            if not content:
                continue
            if lane_kind == LaneKind.NARRATIVE.value:
                summary_blocks.append(content)
            elif lane_kind in {LaneKind.CHART.value, LaneKind.DIAGRAM.value}:
                visual_blocks.append(content)

        title = page.title or "价值分析"
        goal = str((page.page_spec or {}).get("goal") or "用统一财务口径展示投资回报与成本变化")
        bg = global_theme.get("bg_color", "#FFFFFF")
        text = global_theme.get("text_color", "#000000")
        accent = global_theme.get("accent_color", "#0A2463")
        # 计算 accent rgba 变体
        _ah = accent.lstrip("#")
        _ar, _ag, _ab = int(_ah[:2], 16), int(_ah[2:4], 16), int(_ah[4:6], 16)
        accent_12 = f"rgba({_ar},{_ag},{_ab},0.12)"
        accent_24 = f"rgba({_ar},{_ag},{_ab},0.24)"
        summary_html = "\n".join(summary_blocks)
        visuals_html = "\n".join(
            f'<div style="min-width:0;">{block}</div>' for block in visual_blocks
        )

        return f'''<section data-page-id="{page.page_id}" class="deck-page" style="background:{bg};color:{text};width:100%;height:100%;padding:28px 32px;display:flex;flex-direction:column;gap:18px;overflow:hidden;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;">
    <div>
      <h1 style="margin:0;font-size:30px;line-height:1.2;font-weight:800;color:{text};">{title}</h1>
      <p style="margin:8px 0 0;font-size:13px;line-height:1.7;color:{text};opacity:0.7;max-width:900px;">{goal}</p>
    </div>
    <div style="padding:8px 12px;border-radius:999px;background:{accent_12};border:1px solid {accent_24};font-size:12px;color:{accent};white-space:nowrap;">统一 ROI 与回收期口径</div>
  </div>
  {summary_html}
  <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;flex:1;min-height:0;align-items:stretch;">
    {visuals_html}
  </div>
</section>'''

    def _basic_page_html(self, page: DeckPage, global_theme: dict, nc: dict) -> str:
        """基础页面模板 — 当 lane 全失败时的保底"""
        bg = global_theme.get("bg_color", "#FFFFFF")
        text = global_theme.get("text_color", "#000000")
        accent = global_theme.get("accent_color", "#0A2463")
        title = page.title or "未命名页面"
        core_msg = nc.get("core_message", "")

        return f'''<section data-page-id="{page.page_id}" class="deck-page" style="
            width: 100%; min-height: 100vh; display: flex; flex-direction: column;
            align-items: center; justify-content: center; padding: 60px 80px;
            background: {bg}; color: {text}; font-family: Inter, system-ui, sans-serif;
        ">
    <h2 style="font-size: 2.5rem; font-weight: 700; margin-bottom: 1rem; color: {accent};">
        {title}
    </h2>
    <p style="font-size: 1.2rem; opacity: 0.8; max-width: 600px; text-align: center; line-height: 1.6;">
        {core_msg}
    </p>
</section>'''

    def _apply_theme_shell(self, html: str, global_theme: dict) -> str:
        bg = global_theme.get("bg_color", "#FFFFFF")
        text = global_theme.get("text_color", "#000000")
        accent = global_theme.get("accent_color", "#0A2463")

        # 1. 在 <head> 末尾（或 <body> 前）注入 :root CSS 变量，
        #    让 LLM 引用的 var(--bg)/var(--text)/var(--accent) 真正生效。
        font_heading = global_theme.get("font_heading", "'Times New Roman', 'Garamond', Georgia, serif")
        font_body = global_theme.get("font_body", "Arial, Roboto, 'Helvetica Neue', sans-serif")
        css_injection = (
            f'<style id="deck-theme-vars">'
            f':root{{--accent:{accent};--bg:{bg};--text:{text}}}'
            f'section.deck-page{{background:{bg}!important;color:{text}!important}}'
            f'section.deck-page h1,section.deck-page h2,section.deck-page h3,section.deck-page h4{{font-family:{font_heading}!important}}'
            f'section.deck-page p,section.deck-page li,section.deck-page td,section.deck-page span{{font-family:{font_body}!important}}'
            f'</style>'
        )
        if "</head>" in html:
            html = html.replace("</head>", css_injection + "</head>", 1)
        elif "<body" in html:
            idx = html.index("<body")
            html = html[:idx] + css_injection + html[idx:]
        else:
            # 没有 head/body — 在 <section> 开标签后注入 style 块
            section_start = re.search(r"<section\b[^>]*>", html, flags=re.IGNORECASE)
            if section_start:
                insert_pos = section_start.end()
                html = html[:insert_pos] + css_injection + html[insert_pos:]

        # 2. 更新 <section> 的 inline style（保留原有逻辑）
        section_match = re.search(r"<section\b([^>]*)>", html, flags=re.IGNORECASE)
        if not section_match:
            return html

        attrs = section_match.group(1)
        style_match = re.search(r"style=(['\"])(.*?)\1", attrs, flags=re.IGNORECASE | re.DOTALL)
        theme_style = f"background:{bg}; color:{text};"

        if style_match:
            quote = style_match.group(1)
            existing_style = style_match.group(2).strip().rstrip(";")
            merged_style = f"{existing_style}; {theme_style}" if existing_style else theme_style
            new_attrs = (
                attrs[:style_match.start()]
                + f"style={quote}{merged_style}{quote}"
                + attrs[style_match.end():]
            )
        else:
            new_attrs = f"{attrs} style=\"{theme_style}\""

        return html[:section_match.start()] + f"<section{new_attrs}>" + html[section_match.end():]

    def _build_page_extra_instructions(self, page_spec: dict, revision_guidance: str) -> str:
        cr = page_spec.get("content_requirements", {})
        review_rules = page_spec.get("review_rules", [])
        lines = [
            f"10. 至少呈现 {cr.get('min_points', 3)} 个核心观点/信息点",
            f"11. 至少呈现 {cr.get('min_card_blocks', 0)} 个卡片块与 {cr.get('min_visual_blocks', 0)} 个视觉块",
            f"12. 必须包含的区块: {self._format_list(cr.get('must_include_blocks'))}",
            f"13. 是否需要详细概念解释: {'需要' if cr.get('require_detailed_explanation') else '不需要'}",
            f"14. 审稿硬规则: {self._format_list(review_rules)}",
            f"15. 上一轮修改指导: {revision_guidance or '无'}",
        ]
        context_prompt = format_context_layers_for_prompt(page_spec.get("context_layers") or {})
        if context_prompt != "无":
            lines.append(f"16. 对话上下文（仅作 framing，不可直接当证据）:\n{context_prompt}")
        lines.append(
            "17. 证据使用规则: "
            + format_evidence_refs_for_prompt(page_spec.get("evidence_details") or [])
        )
        if page_spec.get("page_kind") == PageKind.CHART_ANALYSIS.value:
            lines.append("18. 涉及 ROI、回收期、净收益、成本节省时，允许修正原始数字，但最终页面中的全部财务指标必须彼此可计算、自洽，并显式注明关键假设与计算口径")
        return "\n".join(lines)

    def _enrich_page_spec(self, page_spec: dict[str, Any], brief: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(page_spec or {})
        evidence_catalog = brief.get("evidence_catalog") if isinstance(brief.get("evidence_catalog"), dict) else {}
        evidence_refs = [
            str(item).strip()
            for item in enriched.get("evidence_refs") or []
            if str(item).strip()
        ]
        enriched["evidence_refs"] = evidence_refs
        enriched["evidence_details"] = [
            evidence_catalog[item]
            for item in evidence_refs
            if item in evidence_catalog
        ]
        enriched["context_layers"] = brief.get("context_layers") or {}
        return enriched

    def _build_revision_guidance(self, report: ReviewReport) -> str:
        rule_issues: dict[str, list[str]] = {}
        other_issues: list[str] = []
        for issue in report.issues:
            msg = str(issue.get("message") or "").strip()
            sug = str(issue.get("suggestion") or "").strip()
            if not msg:
                continue
            line = f"{msg}；修改方向: {sug}" if sug else msg
            rid = issue.get("rule_id") or ""
            if rid:
                rule_issues.setdefault(rid, []).append(line)
            else:
                other_issues.append(line)

        lines: list[str] = []
        if rule_issues:
            lines.append("## 设计规则违规（必须修复）")
            for rid, items in sorted(rule_issues.items()):
                lines.append(f"### {rid}")
                lines.extend(f"- {item}" for item in items)
        if other_issues:
            lines.append("## 其他问题")
            lines.extend(f"- {item}" for item in other_issues)

        for suggestion in report.suggestions:
            text = str(suggestion).strip()
            if text and text not in "\n".join(lines):
                lines.append(f"- 补充优化: {text}")

        if not lines:
            return "请严格按照 PageSpec 与审稿规则重写页面结构与结论表达"
        return "\n".join(lines)

    async def _emit_review_event(
        self,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        project_id: str,
        level: str,
        target_id: str,
        report: ReviewReport,
        retrying: bool,
    ) -> None:
        await send_fn({
            "type": "webdeck_review",
            "project_id": project_id,
            "level": level,
            "target_id": target_id,
            "passed": report.passed,
            "score": report.score,
            "issues": report.issues,
            "suggestions": report.suggestions,
            "retrying": retrying,
        })

    def _extract_html(self, content: str) -> str:
        """从 LLM 输出中提取 HTML"""
        # 去除 markdown 代码块标记
        content = re.sub(r'^```(?:html)?\s*\n?', '', content.strip())
        content = re.sub(r'\n?```\s*$', '', content.strip())
        return content.strip()

    # ── 暗色 hex 值黑名单 — _normalize_page_html 会将这些替换为主题背景色 ──
    _DARK_BG_COLORS = re.compile(
        r'(background(?:-color)?\s*:\s*[^;]*?)'
        r'(#0f172a|#1e293b|#1a1a2e|#16213e|#0f3460|#0a1628|#0f0f1a)',
        re.IGNORECASE,
    )
    _DARK_GRADIENT = re.compile(
        r'(background(?:-image)?\s*:\s*)linear-gradient\([^)]*'
        r'(?:#0f172a|#1e293b|#1a1a2e|#16213e|#0f3460|#0a1628|#0f0f1a)[^)]*\)',
        re.IGNORECASE,
    )

    def _normalize_page_html(self, html: str, page_id: str, global_theme: dict) -> str | None:
        """
        程序化 HTML 规范化 — 在 _extract_html 之后、_apply_theme_shell 之前调用。
        修复 LLM 常见的结构性违规:
          1. 检测无效输出（纯 JSON / <webdeck_brief> / 无 HTML 标签）
          2. 剥离完整 HTML 文档包装
          3. 替换非标准标签（<slide> → <section>）
          4. 确保 <section class="deck-page"> 包裹
          5. 清除暗色内联背景
          6. 清除禁止属性（box-shadow 等）
        返回 None 表示内容无法挽救，调用方应走 fallback。
        """
        if not html or not html.strip():
            return None

        text = html.strip()

        # ── 1. 检测无效输出 ──
        # 纯 JSON 或 <webdeck_brief>
        if text.startswith('{') or text.startswith('[') or '<webdeck_brief>' in text:
            logger.warning(f"[PageOrch] _normalize: 检测到非 HTML 输出 (JSON/brief), page={page_id}")
            return None
        # 无任何 HTML 标签
        if not re.search(r'<[a-zA-Z]', text):
            logger.warning(f"[PageOrch] _normalize: 无 HTML 标签, page={page_id}")
            return None

        # ── 2. 剥离完整文档包装 ──
        if '<!DOCTYPE' in text or '<html' in text.lower():
            # 提取 <body> 内容
            body_match = re.search(r'<body[^>]*>(.*)</body>', text, re.DOTALL | re.IGNORECASE)
            if body_match:
                text = body_match.group(1).strip()
            else:
                # 无 body 标签 — 移除 html/head 标签
                text = re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'</?html[^>]*>', '', text, flags=re.IGNORECASE)
                text = re.sub(r'<head>.*?</head>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'</?body[^>]*>', '', text, flags=re.IGNORECASE)
                text = text.strip()

        # ── 3. 替换非标准标签 ──
        # <slide ...> → <section ...>
        text = re.sub(r'<slide\b', '<section', text, flags=re.IGNORECASE)
        text = re.sub(r'</slide\s*>', '</section>', text, flags=re.IGNORECASE)
        # 清除 <webdeck> / </webdeck>
        text = re.sub(r'</?webdeck[^>]*>', '', text, flags=re.IGNORECASE)

        # ── 4. 确保 deck-page 包裹 ──
        if not re.search(r'<section[^>]*class="[^"]*deck-page', text, re.IGNORECASE):
            bg = global_theme.get("bg_color", "#FFFFFF")
            text_color = global_theme.get("text_color", "#000000")
            text = (
                f'<section data-page-id="{page_id}" class="deck-page" '
                f'style="width:100%;height:100%;background:{bg};color:{text_color};'
                f'padding:48px 56px;box-sizing:border-box;overflow:hidden;">'
                f'{text}</section>'
            )

        # ── 5. 清除暗色内联背景 ──
        bg = global_theme.get("bg_color", "#FFFFFF")
        # 替换暗色 hex 值
        text = self._DARK_BG_COLORS.sub(rf'\1{bg}', text)
        # 替换包含暗色的渐变
        text = self._DARK_GRADIENT.sub(rf'\1{bg}', text)
        # 替换暗色 color 值（文字色）
        text = re.sub(
            r'((?:^|;)\s*color\s*:\s*)(?:#e2e8f0|#cbd5e1|#94a3b8)',
            rf'\g<1>{global_theme.get("text_color", "#000000")}',
            text, flags=re.IGNORECASE,
        )

        # ── 6. 清除禁止属性 ──
        text = re.sub(r'box-shadow\s*:[^;]+;?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'text-shadow\s*:[^;]+;?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'transform\s*:[^;]*perspective[^;]*;?', '', text, flags=re.IGNORECASE)

        return text

    async def _auto_edit_html(
        self,
        page: DeckPage,
        bundle: "PageBundle",
        report: "ReviewReport",
        global_theme: dict,
        model: str | None = None,
    ) -> "PageBundle":
        """在所有重试失败后，通过 LLM 直接编辑 HTML 修复已知问题。

        不进行完整重新生成，只针对 review 报告中的问题进行精准修复，
        重点解决 16:9 布局溢出问题。
        """
        issues_text = self._build_revision_guidance(report)
        current_html = bundle.html or ""

        bg = global_theme.get("bg_color", "#FFFFFF")
        text_color = global_theme.get("text_color", "#000000")
        accent = global_theme.get("accent_color", "#0A2463")
        font_heading = global_theme.get("font_heading", "'Times New Roman', 'Garamond', Georgia, serif")
        font_body = global_theme.get("font_body", "Arial, Roboto, 'Helvetica Neue', sans-serif")
        design_rules = global_theme.get("design_rules", "")

        logger.info(
            f"[PageOrch] _auto_edit_html: page_id={page.page_id}, "
            f"issues={issues_text[:100]}"
        )

        auto_edit_prompt = f"""你是 Web Deck Page Layout Fixer。你的任务是修复单页 HTML 幻灯片的布局溢出问题，使其严格适配 16:9 单页展示。

## 修复原则
1. **不删内容** — 保留所有文字、数据、图表，只调整布局和样式；严禁删除文字节点或段落内容，只允许修改CSS样式属性
2. **压缩空间** — 减小 padding/margin，缩小字号，使用 gap 替代 margin
3. **强制约束** — 给关键容器加 overflow:hidden，使用 max-height 约束高度
4. **优先布局** — 使用 Flexbox/Grid 的 flex-shrink: 1; min-height: 0 防止内容撑破容器
5. **输出完整** — 输出完整修复后的 HTML section，只输出 HTML，不要任何说明

## 风格约束（修复时必须保持）
- 背景色: {bg}，文字色: {text_color}，强调色: {accent}
- 标题字体: {font_heading}；正文字体: {font_body}
- 设计风格: {design_rules}"""

        user_msg = (
            f"## 审稿发现的问题\n{issues_text}\n\n"
            f"## 当前 HTML（需要修复）\n{current_html}\n\n"
            f"请直接输出修复后的完整 HTML。"
        )

        response = await llm_chat(
            system=auto_edit_prompt,
            messages=[{"role": "user", "content": user_msg}],
            model=model,
            task_id=page.page_id,
        )

        new_html = self._extract_html(response.content)
        if not new_html or len(new_html) < 100:
            logger.warning(f"[PageOrch] _auto_edit_html 返回空结果，跳过")
            return bundle

        return PageBundle(
            page_id=bundle.page_id,
            status=bundle.status,
            html=new_html,
            css_tokens=bundle.css_tokens,
            artifacts=bundle.artifacts,
            review=report,
        )

    # ──────────── 溢出自动修复 ────────────

    # 注入到页面 <head> 末尾的 CSS，强制内容适配 16:9 画布
    _OVERFLOW_FIX_CSS = """
<style data-overflow-fix>
  /* 自动修复: 强制内容适配 16:9 单页画布 */
  html, body {
    margin: 0; padding: 0; overflow: hidden;
    width: 100vw; height: 100vh;
  }
  body > *:first-child,
  [data-page-id],
  section {
    max-height: 100vh !important;
    overflow: hidden !important;
    box-sizing: border-box;
    font-size: 0.9em;
  }
  /* 缩小底部间距和字号防止溢出 */
  body {
    font-size: clamp(12px, 1.4vw, 18px);
  }
  h1, h2, h3 { margin-top: 0.3em; margin-bottom: 0.2em; }
  p, li { margin-top: 0.15em; margin-bottom: 0.15em; line-height: 1.4; }
  table { font-size: 0.9em; }
  .card, .stat-card, [class*=card] {
    padding: 0.5em !important;
    margin: 0.3em !important;
  }
</style>"""

    def _apply_overflow_css_fix(self, bundle: "PageBundle") -> "PageBundle":
        """在审稿多次失败后，向 HTML 注入 CSS 强制约束 16:9 画布。

        此方法作为最终兜底手段，在 LLM 多次重试仍无法修复溢出时使用。
        通过 CSS overflow:hidden + 字号/间距压缩确保内容不超出视口。
        """
        # Mutates bundle.html in-place; also returns bundle for call-chaining convenience.
        html = bundle.html or ""
        if not html:
            return bundle

        # 避免重复注入
        if "data-overflow-fix" in html:
            return bundle

        # 优先插入到 </head> 前，其次插入到 <body> 前，最后前置
        if "</head>" in html:
            html = html.replace("</head>", f"{self._OVERFLOW_FIX_CSS}\n</head>", 1)
        elif "<body" in html:
            idx = html.find("<body")
            html = html[:idx] + self._OVERFLOW_FIX_CSS + "\n" + html[idx:]
        else:
            html = self._OVERFLOW_FIX_CSS + "\n" + html

        bundle.html = html
        return bundle
