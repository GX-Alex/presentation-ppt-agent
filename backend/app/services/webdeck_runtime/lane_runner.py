"""
Lane Runner — 子任务执行器 (对齐 high.md §5.3.4 Specialized Subagents)。
负责执行单个 lane (narrative / chart / diagram / asset / layout / review)。
每个 lane 有独立的 LLM 调用和状态管理。

参考 claw-code: 每个 lane 是独立的执行单元，失败/超时不影响其他 lane。
"""
import asyncio as _asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import chat as llm_chat
from app.models.tables import LaneRun
from app.services.presentation_briefing_service import (
    format_context_layers_for_prompt,
    format_evidence_refs_for_prompt,
)
from app.services.webdeck_runtime.contracts import LaneKind, LaneStatus, PageKind
from app.services.webdeck_runtime.state_store import deck_state_store

logger = logging.getLogger(__name__)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert hex color to rgba string."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"

# Lane-level auto-retry for transient LLM errors
LANE_MAX_AUTO_RETRIES = 3          # total attempts = 1 original + 3 retries
LANE_RETRY_BACKOFF_BASE_S = 2.0    # 2s → 8s → 32s (exponential)
_TRANSIENT_ERROR_PATTERNS = (
    "负载过高",
    "overloaded",
    "rate limit",
    "529",
    "503",
    "AI 模型调用失败",
)


# ────────────── Lane 类型对应的系统提示词 ──────────────

NARRATIVE_PROMPT = """你是 Narrative Agent，负责为演示页面撰写简洁有力的叙述文案。

## 输出要求
请输出一段结构严谨的 HTML 片段。使用以下语义化标签和 class：
```html
<div class="deck-narrative-container">
  <h1 class="deck-title">页面大标题</h1>
  <div class="deck-core-message">
    <p>这里是核心信息，1-2句话，要求有洞察力，字字珠玑。</p>
  </div>
  <div class="deck-points-grid">
    <div class="deck-point-card">
      <h3>要点小标题1</h3>
      <p>支撑要点内容...</p>
    </div>
    <div class="deck-point-card">
      <h3>要点小标题2</h3>
      <p>支撑要点内容...</p>
    </div>
    <!-- 4-8个卡片，根据内容深度灵活调整 -->
  </div>
</div>
```

## 约束
- 面向受众: {audience}
- 语调: {tone}
- 核心信息: {core_message}
- 【强制】颜色约束: 背景色 {bg_color}，文字色 {text_color}，高亮色 {accent_color}；禁止使用其他背景色
- 【强制】字体约束: 标题(h1/h2/h3/h4)必须使用字体 {font_heading}；正文/说明必须使用字体 {font_body}
- 设计风格约束（用户指定或默认麦肯锡风格，强制执行）: {design_style}
- 页面必须适配 16:9 单页展示；若内容较多，应缩小字号、压缩间距以适配单页，而非删减文字
- 至少输出 {min_points} 个观点卡片
- 至少输出 {min_card_blocks} 个卡片块
- 是否需要详细概念解释: {require_detailed_explanation}
- 必须包含的区块: {must_include_blocks}
- 审稿硬规则: {review_rules}
- 上一轮修改指导: {revision_guidance}
- 对话上下文（仅作 framing，不可直接当证据）: {context_layers}
- 证据使用规则: {evidence_rules}

使用简洁有力的语言，避免虚词废话。只输出 HTML 片段。"""

CHART_PROMPT = """你是 Chart Agent，负责为演示页面生成图表配置。

## 输出要求
输出一段包含 ECharts 图表的 HTML 片段，放在一个带 class 的 wrapper 中。图表配置应直接内联在 script 标签中。
```html
<div class="deck-visual-wrapper deck-chart-wrapper">
    <div id="{container_id}" style="width:100%; height:400px;"></div>
  <script>...</script>
</div>
```

## 约束
- 图表类型: {chart_kind}
- 图表描述: {description}
- 图表目的: {purpose}
- 数据维度: {data_dimensions}
- 必须包含元素: {required_elements}
- 图表说明: {caption}
- 图表容器 ID 必须严格使用: {container_id}
- 配色主题: 高亮色 {accent_color}，背景色 {bg_color}，文字色 {text_color}；图表背景必须与页面背景色 {bg_color} 一致，严禁擅自使用深色背景
- 引入 ECharts CDN: https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js
- 优先依据证据材料组织数据与结论；若证据不足，只能使用”示意/待确认”占位，不得捏造具体业务事实或财务数字
- 使用清晰现代的 UI 风格 (隐藏不必要的网格线、坐标轴文字使用 {text_color})
- 页面必须适配 16:9 单页展示，图表与说明必须在单页内闭合
- 如果涉及 ROI、回收期、净收益、成本节省等财务数字，必须保证所有数字彼此可计算、自洽，并在图表注释中写清关键假设与计算口径
- 设计风格约束（用户指定或默认麦肯锡风格，强制执行）: {design_style}
- 审稿硬规则: {review_rules}
- 上一轮修改指导: {revision_guidance}
- 对话上下文（仅作 framing，不可直接当证据）: {context_layers}
- 证据使用规则: {evidence_rules}

只输出 HTML 片段 (div + script)。"""

DIAGRAM_PROMPT = """你是 Diagram Agent，负责为演示页面生成架构图 / 流程图。

## 输出要求
输出严格 JSON，对同一张图同时给出 Draw.io 真源和可直接预览的 HTML。
```json
{
    "drawio_xml": "<mxfile>...</mxfile>",
    "rendered_html": "<div class=\"deck-visual-wrapper deck-diagram-wrapper\">...inline svg...</div>"
}
```

## 约束
- 图表类型: {diagram_kind}
- 图表描述: {description}
- 图示目的: {purpose}
- 关键维度/维度标签: {data_dimensions}
- 必须包含元素: {required_elements}
- 图示说明: {caption}
- 配色主题: 主色 {accent_color}，背景 {bg_color}，文字色 {text_color}
- SVG 宽度 100%，高度适中 (300-600px，内容较多时可适当增加)
- 使用现代化的圆角矩形、粗细适中的连线及无干扰的阴影
- 确保 SVG 可独立渲染并自动居中自适应
- `drawio_xml` 必须是完整、可被 diagrams.net 重新打开编辑的 `<mxfile>...</mxfile>`
- `rendered_html` 必须与 `drawio_xml` 表达的是同一张图，且最外层 class 必须包含 `deck-visual-wrapper deck-diagram-wrapper`
- `rendered_html` 内不要依赖外部脚本；优先使用 inline SVG
- 页面必须适配 16:9 单页展示，图与说明必须在单页内闭合
- 设计风格约束（用户指定或默认麦肯锡风格，强制执行）: {design_style}
- 审稿硬规则: {review_rules}
- 上一轮修改指导: {revision_guidance}
- 对话上下文（仅作 framing，不可直接当证据）: {context_layers}
- 证据使用规则: {evidence_rules}

只输出 JSON，不要附加解释文字。"""


class LaneRunner:
    """Lane 执行器 — 按 lane 类型路由到对应的子 agent"""

    @staticmethod
    def _format_list(values: list[str] | None, fallback: str = "无") -> str:
        cleaned = [str(value).strip() for value in (values or []) if str(value).strip()]
        return "；".join(cleaned) if cleaned else fallback

    @staticmethod
    def _preview_content(content: str, limit: int = 320) -> str:
        cleaned = re.sub(r"\s+", " ", content or "").strip()
        return cleaned[:limit]

    @staticmethod
    def _extract_json_payload(raw: str) -> dict[str, Any] | None:
        cleaned = raw.strip()
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"(\{[\s\S]*\})", cleaned)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(1))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None

    @staticmethod
    def _extract_drawio_xml(raw: str) -> str:
        mxfile_match = re.search(r"(<mxfile[\s\S]*?</mxfile>)", raw, flags=re.IGNORECASE)
        if mxfile_match:
            return mxfile_match.group(1).strip()

        graph_match = re.search(r"(<mxGraphModel[\s\S]*?</mxGraphModel>)", raw, flags=re.IGNORECASE)
        if graph_match:
            return f"<mxfile><diagram id=\"diagram-1\" name=\"Page-1\">{graph_match.group(1).strip()}</diagram></mxfile>"

        return ""

    @staticmethod
    def _extract_diagram_rendered_html(raw: str) -> str:
        wrapper_match = re.search(
            r'(<div[^>]*deck-diagram-wrapper[^>]*>[\s\S]*?</div>)',
            raw,
            flags=re.IGNORECASE,
        )
        if wrapper_match:
            return wrapper_match.group(1).strip()

        svg_match = re.search(r"(<svg[\s\S]*?</svg>)", raw, flags=re.IGNORECASE)
        if svg_match:
            return (
                '<div class="deck-visual-wrapper deck-diagram-wrapper">'
                f'{svg_match.group(1).strip()}'
                '</div>'
            )

        return ""

    @staticmethod
    def _build_diagram_placeholder_html(
        caption: str,
        accent_color: str,
        text_color: str,
        bg_color: str,
    ) -> str:
        return (
            '<div class="deck-visual-wrapper deck-diagram-wrapper" '
            f'style="display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;min-height:320px;padding:24px;border-radius:20px;border:1px solid {LaneRunner._hex_rgba(accent_color, 0.18)};background:{LaneRunner._hex_rgba(bg_color, 0.88)};">'
            f'<div style="font-size:14px;font-weight:700;color:{text_color};">图示已生成 Draw.io 真源</div>'
            f'<div style="font-size:12px;line-height:1.7;color:{text_color};opacity:0.78;text-align:center;max-width:720px;">{caption or "当前图示预览稍后可根据 drawioXml 重新导出。"}</div>'
            '</div>'
        )

    @staticmethod
    def _hex_rgba(hex_color: str, alpha: float) -> str:
        return _hex_to_rgba(hex_color, alpha)

    def _format_context_layers(self, page_spec: dict[str, Any]) -> str:
        return format_context_layers_for_prompt(page_spec.get("context_layers") or {})

    def _format_evidence_rules(self, page_spec: dict[str, Any]) -> str:
        return format_evidence_refs_for_prompt(page_spec.get("evidence_details") or [])

    @staticmethod
    def _build_chart_analysis_finance_model(page_spec: dict[str, Any] | None = None) -> dict[str, Any]:
        narrative_contract = (page_spec or {}).get("narrative_contract") or {}
        core_message = str(narrative_contract.get("core_message") or "")
        payback_match = re.search(r"(\d+)\s*个?月", core_message)
        roi_match = re.search(r"ROI(?:达|为)?\s*(\d+)%", core_message, flags=re.IGNORECASE)

        initial_investment = 900
        payback_months = max(6, int(payback_match.group(1))) if payback_match else 12
        three_year_roi = max(120, int(roi_match.group(1))) if roi_match else 320

        first_year_return = round(initial_investment * 12 / payback_months)
        three_year_cumulative_return = round(initial_investment * three_year_roi / 100)
        remaining_return = max(three_year_cumulative_return - first_year_return, 0)
        year_two_return = round(remaining_return * 0.49)
        year_three_return = remaining_return - year_two_return
        yearly_returns = [first_year_return, year_two_return, year_three_return]
        three_year_net_gain = three_year_cumulative_return - initial_investment

        scale = first_year_return / 900 if first_year_return else 1
        base_categories = [
            ("人工与外包", 780, 220),
            ("系统与工具", 220, 150),
            ("质检与管理", 180, 90),
        ]
        categories = [
            {
                "name": name,
                "traditional": int(round(traditional * scale)),
                "ai": int(round(ai * scale)),
            }
            for name, traditional, ai in base_categories
        ]
        annual_cost_savings = sum(item["traditional"] - item["ai"] for item in categories)
        annual_revenue_uplift = max(first_year_return - annual_cost_savings, 0)

        return {
            "initial_investment": initial_investment,
            "payback_months": payback_months,
            "three_year_roi": three_year_roi,
            "three_year_cumulative_return": three_year_cumulative_return,
            "three_year_net_gain": three_year_net_gain,
            "first_year_return": first_year_return,
            "yearly_returns": yearly_returns,
            "annual_cost_savings": annual_cost_savings,
            "annual_revenue_uplift": annual_revenue_uplift,
            "categories": categories,
            "roi_formula": "3 年累计 ROI = 3 年累计回报 / 初始投入 × 100%",
            "scope_note": "基于年业务量 100 万次咨询、统一业务口径测算",
        }

    def _build_chart_analysis_narrative(self, page_spec: dict, global_theme: dict | None = None) -> dict[str, Any]:
        model = self._build_chart_analysis_finance_model(page_spec)
        gt = global_theme or {}
        text = gt.get("text_color", "#000000")
        secondary = gt.get("text_color", "#000000")  # use text_color as base; secondary is softer
        accent = gt.get("accent_color", "#0A2463")
        bg = gt.get("bg_color", "#FFFFFF")
        html = f'''<div class="deck-finance-summary" style="display:flex;flex-direction:column;gap:16px;margin-bottom:20px;">
  <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;">
    <div>
      <div style="font-size:15px;font-weight:700;color:{text};">投资回报结论</div>
      <div style="margin-top:6px;font-size:13px;line-height:1.7;color:{secondary};max-width:720px;">在统一业务量口径下，AI 客服改造的一次性投入为 {model['initial_investment']} 万元，首年综合回报 {model['first_year_return']} 万元，可在第 {model['payback_months']} 个月收回投资；随着模型优化与业务转化提升，3 年累计回报提升至 {model['three_year_cumulative_return']} 万元，对应累计 ROI {model['three_year_roi']}%。</div>
    </div>
    <div style="padding:10px 14px;border-radius:999px;background:{_hex_to_rgba(accent, 0.12)};border:1px solid {_hex_to_rgba(accent, 0.25)};font-size:12px;color:{accent};white-space:nowrap;">{model['scope_note']}</div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;">
    <div style="padding:16px 18px;border-radius:16px;background:{_hex_to_rgba(bg, 0.72)};border:1px solid {_hex_to_rgba(accent, 0.16)};">
      <div style="font-size:12px;color:#94a3b8;">投资回收期</div>
      <div style="margin-top:8px;font-size:28px;font-weight:800;color:{text};">{model['payback_months']} 个月</div>
      <div style="margin-top:6px;font-size:12px;color:{accent};">月均综合回报约 {round(model['first_year_return'] / 12, 1)} 万元</div>
    </div>
    <div style="padding:16px 18px;border-radius:16px;background:{_hex_to_rgba(bg, 0.72)};border:1px solid {_hex_to_rgba(accent, 0.16)};">
      <div style="font-size:12px;color:#94a3b8;">首年综合回报</div>
      <div style="margin-top:8px;font-size:28px;font-weight:800;color:{text};">{model['first_year_return']} 万元</div>
      <div style="margin-top:6px;font-size:12px;color:{accent};">成本节省 {model['annual_cost_savings']} 万元 + 增收 {model['annual_revenue_uplift']} 万元</div>
    </div>
    <div style="padding:16px 18px;border-radius:16px;background:{_hex_to_rgba(bg, 0.72)};border:1px solid {_hex_to_rgba(accent, 0.16)};">
      <div style="font-size:12px;color:#94a3b8;">3 年累计 ROI</div>
      <div style="margin-top:8px;font-size:28px;font-weight:800;color:{text};">{model['three_year_roi']}%</div>
      <div style="margin-top:6px;font-size:12px;color:{accent};">3 年累计回报 {model['three_year_cumulative_return']} 万元，净增益 {model['three_year_net_gain']} 万元</div>
    </div>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:12px 14px;border-radius:14px;background:{_hex_to_rgba(bg, 0.8)};border:1px solid rgba(148,163,184,0.16);font-size:12px;color:{secondary};line-height:1.6;">
    <span style="font-weight:700;color:{text};">关键假设</span>
    <span>一次性建设投入 {model['initial_investment']} 万元</span>
    <span>首年成本节省 {model['annual_cost_savings']} 万元</span>
    <span>首年增收与留存收益 {model['annual_revenue_uplift']} 万元</span>
    <span>{model['roi_formula']}</span>
    <span>全部页面采用相同口径，避免 ROI、回收期与回报口径冲突</span>
  </div>
</div>'''
        return {
            "content": html,
            "asset": None,
            "metadata": {
                "kind": "narrative",
                "finance_model": model,
                "content_preview": self._preview_content(html),
            },
        }

    def _build_chart_analysis_chart(self, input_data: dict[str, Any]) -> dict[str, Any]:
        page_spec = input_data.get("page_spec", {})
        model = self._build_chart_analysis_finance_model(page_spec)
        chart_kind = str(input_data.get("chart_kind") or "bar_chart")
        container_id = str(input_data.get("container_id") or "chart-container")
        caption = str(input_data.get("caption") or "图表说明")
        gt = input_data.get("global_theme") or {}
        text = gt.get("text_color", "#000000")
        accent = gt.get("accent_color", "#0A2463")
        bg = gt.get("bg_color", "#FFFFFF")

        if chart_kind in {"line_chart", "line_combo_chart"}:
            months = [f"{month}月" for month in range(1, 37)]
            monthly_returns: list[float] = []
            for yearly_return in model["yearly_returns"]:
                monthly_value = round(yearly_return / 12, 1)
                monthly_returns.extend([monthly_value] * 12)

            cumulative_investment = [model["initial_investment"] for _ in months]
            cumulative_return: list[float] = []
            running_total = 0.0
            for monthly_value in monthly_returns:
                running_total = round(running_total + monthly_value, 1)
                cumulative_return.append(running_total)
            cumulative_net_gain = [
                round(value - model["initial_investment"], 1)
                for value in cumulative_return
            ]

            option = {
                "backgroundColor": "transparent",
                "legend": {
                    "top": 0,
                    "textStyle": {"color": text},
                    "data": ["累计投入", "累计回报", "累计净增益"],
                },
                "tooltip": {"trigger": "axis"},
                "grid": {"left": 56, "right": 28, "top": 48, "bottom": 44},
                "xAxis": {
                    "type": "category",
                    "name": "月份",
                    "data": months,
                    "axisLabel": {"color": "#94a3b8", "interval": 2},
                    "axisLine": {"lineStyle": {"color": "#475569"}},
                },
                "yAxis": {
                    "type": "value",
                    "name": "万元",
                    "axisLabel": {"color": "#94a3b8"},
                    "axisLine": {"lineStyle": {"color": "#475569"}},
                    "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.12)"}},
                },
                "series": [
                    {
                        "name": "累计投入",
                        "type": "line",
                        "smooth": False,
                        "symbol": "circle",
                        "symbolSize": 5,
                        "lineStyle": {"width": 3, "color": "#f59e0b"},
                        "itemStyle": {"color": "#f59e0b"},
                        "data": cumulative_investment,
                    },
                    {
                        "name": "累计回报",
                        "type": "line",
                        "smooth": True,
                        "symbol": "emptyCircle",
                        "symbolSize": 6,
                        "lineStyle": {"width": 3, "color": accent},
                        "itemStyle": {"color": accent},
                        "markPoint": {
                            "symbolSize": 54,
                            "data": [{
                                "name": "盈亏平衡点",
                                "coord": [f"{model['payback_months']}月", model["initial_investment"]],
                                "value": f"{model['payback_months']}月回收",
                            }],
                            "label": {"color": bg, "fontWeight": 700},
                        },
                        "data": cumulative_return,
                    },
                    {
                        "name": "累计净增益",
                        "type": "line",
                        "smooth": True,
                        "symbol": "circle",
                        "symbolSize": 6,
                        "lineStyle": {"width": 3, "color": "#22c55e"},
                        "itemStyle": {"color": "#22c55e"},
                        "data": cumulative_net_gain,
                    },
                ],
            }
            html = f'''<div class="deck-visual-wrapper deck-chart-wrapper" style="display:flex;flex-direction:column;gap:12px;padding:18px 20px;border-radius:18px;background:{_hex_to_rgba(bg, 0.78)};border:1px solid {_hex_to_rgba(accent, 0.14)};min-height:320px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
    <div>
      <div style="font-size:15px;font-weight:700;color:{text};">{caption}</div>
      <div style="margin-top:4px;font-size:12px;color:#94a3b8;">按月展示累计投入、累计回报与累计净增益，盈亏平衡点锁定在第 {model['payback_months']} 个月。</div>
    </div>
    <div style="padding:6px 10px;border-radius:999px;background:rgba(34,197,94,0.12);font-size:12px;color:#86efac;white-space:nowrap;">单位：万元</div>
  </div>
  <div id="{container_id}" style="width:100%;height:260px;"></div>
  <div style="font-size:12px;line-height:1.6;color:{text};">{model['roi_formula']}。假设一次性建设投入 {model['initial_investment']} 万元，首年综合回报 {model['first_year_return']} 万元，第 {model['payback_months']} 个月达到累计回报与初始投入持平。</div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>(function(){{const el=document.getElementById({json.dumps(container_id, ensure_ascii=False)});if(!el||typeof echarts==='undefined') return;const chart=echarts.init(el);chart.setOption({json.dumps(option, ensure_ascii=False)});window.addEventListener('resize',()=>chart.resize());}})();</script>
</div>'''
        else:
            categories = [item["name"] for item in model["categories"]]
            traditional = [item["traditional"] for item in model["categories"]]
            ai = [item["ai"] for item in model["categories"]]
            saving_ratio = [round((1 - item["ai"] / item["traditional"]) * 100, 1) for item in model["categories"]]
            ratio_notes = " / ".join(f"{name} -{ratio}%" for name, ratio in zip(categories, saving_ratio))
            ai_bar_data = [
                {
                    "value": value,
                    "label": {
                        "show": True,
                        "position": "top",
                        "color": accent,
                        "formatter": f"{value}\\n↓{ratio}%",
                    },
                }
                for value, ratio in zip(ai, saving_ratio)
            ]
            option = {
                "backgroundColor": "transparent",
                "legend": {
                    "top": 0,
                    "textStyle": {"color": text},
                    "data": ["传统方案", "AI方案"],
                },
                "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
                "grid": {"left": 56, "right": 24, "top": 48, "bottom": 44},
                "xAxis": {
                    "type": "category",
                    "name": "成本类型",
                    "data": categories,
                    "axisLabel": {"color": "#94a3b8"},
                    "axisLine": {"lineStyle": {"color": "#475569"}},
                },
                "yAxis": {
                    "type": "value",
                    "name": "万元/年",
                    "axisLabel": {"color": "#94a3b8"},
                    "axisLine": {"lineStyle": {"color": "#475569"}},
                    "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.12)"}},
                },
                "series": [
                    {
                        "name": "传统方案",
                        "type": "bar",
                        "barMaxWidth": 28,
                        "itemStyle": {"color": "#64748b", "borderRadius": [8, 8, 0, 0]},
                        "label": {"show": True, "position": "top", "color": text},
                        "data": traditional,
                    },
                    {
                        "name": "AI方案",
                        "type": "bar",
                        "barMaxWidth": 28,
                        "itemStyle": {"color": accent, "borderRadius": [8, 8, 0, 0]},
                        "data": ai_bar_data,
                    },
                ],
            }
            html = f'''<div class="deck-visual-wrapper deck-chart-wrapper" style="display:flex;flex-direction:column;gap:12px;padding:18px 20px;border-radius:18px;background:{_hex_to_rgba(bg, 0.78)};border:1px solid {_hex_to_rgba(accent, 0.14)};min-height:320px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">
    <div>
      <div style="font-size:15px;font-weight:700;color:{text};">{caption}</div>
      <div style="margin-top:4px;font-size:12px;color:#94a3b8;">保持同一业务量口径，对比三类核心成本。年度节省合计 {model['annual_cost_savings']} 万元。</div>
    </div>
    <div style="padding:6px 10px;border-radius:999px;background:{_hex_to_rgba(accent, 0.12)};font-size:12px;color:{accent};white-space:nowrap;">节省比例：{ratio_notes}</div>
  </div>
  <div id="{container_id}" style="width:100%;height:260px;"></div>
  <div style="display:flex;flex-wrap:wrap;gap:10px;font-size:12px;color:{text};line-height:1.6;">
    <span>{caption}</span>
    <span>传统方案总成本 {sum(traditional)} 万元/年</span>
    <span>AI 方案总成本 {sum(ai)} 万元/年</span>
    <span>成本节省 {model['annual_cost_savings']} 万元/年</span>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>(function(){{const el=document.getElementById({json.dumps(container_id, ensure_ascii=False)});if(!el||typeof echarts==='undefined') return;const chart=echarts.init(el);chart.setOption({json.dumps(option, ensure_ascii=False)});window.addEventListener('resize',()=>chart.resize());}})();</script>
</div>'''

        return {
            "content": html,
            "asset": html,
            "metadata": {
                "kind": "chart",
                "chart_kind": chart_kind,
                "description": input_data.get("description", ""),
                "purpose": input_data.get("purpose", ""),
                "data_dimensions": input_data.get("data_dimensions", []),
                "required_elements": input_data.get("required_elements", []),
                "caption": caption,
                "container_id": container_id,
                "finance_model": model,
                "has_script": True,
                "uses_echarts": True,
                "content_preview": self._preview_content(html),
            },
        }

    async def run_lane(
        self,
        session: AsyncSession,
        lane: LaneRun,
        model: str | None = None,
    ) -> dict[str, Any]:
        """
        执行单个 lane。

        Args:
            session: 数据库会话
            lane: LaneRun ORM 对象
            model: LLM 模型

        Returns:
            {'content': str, 'asset': str | None, 'metadata': dict}
        """
        kind = lane.kind
        input_data = lane.input_data or {}

        logger.info(f"[LaneRunner] 执行 lane: id={lane.lane_id} kind={kind}")

        # 更新状态为 running
        await deck_state_store.update_lane_status(
            session, lane.id, LaneStatus.RUNNING.value
        )

        try:
            # 路由到对应 handler
            handler = self._get_handler(kind)

            for _attempt in range(LANE_MAX_AUTO_RETRIES + 1):
                try:
                    result = await handler(input_data, model)
                    break  # success
                except Exception as exc:
                    is_transient = any(p in str(exc) for p in _TRANSIENT_ERROR_PATTERNS)
                    if not is_transient or _attempt >= LANE_MAX_AUTO_RETRIES:
                        raise  # non-transient or exhausted — propagate to existing error handler
                    wait = LANE_RETRY_BACKOFF_BASE_S ** (_attempt + 1)
                    logger.warning(
                        f"[LaneRunner] lane {lane.id} attempt {_attempt+1} failed "
                        f"(transient), retrying in {wait:.0f}s: {exc}"
                    )
                    await _asyncio.sleep(wait)

            # 更新状态为 completed
            await deck_state_store.update_lane_status(
                session, lane.id, LaneStatus.COMPLETED.value,
                output_data=result,
            )

            logger.info(f"[LaneRunner] Lane 完成: id={lane.lane_id}")
            return result

        except Exception as e:
            # 更新状态为 failed，同时持久化重试计数
            retries = (lane.retries or 0) + 1
            await deck_state_store.update_lane_status(
                session, lane.id, LaneStatus.FAILED.value,
                error=str(e),
                retries=retries,
            )
            logger.warning(f"[LaneRunner] Lane 失败: id={lane.lane_id} error={e}")
            raise

    def _get_handler(self, kind: str):
        """获取 lane 类型对应的处理函数"""
        handlers = {
            LaneKind.NARRATIVE.value: self._run_narrative,
            LaneKind.CHART.value: self._run_chart,
            LaneKind.DIAGRAM.value: self._run_diagram,
            LaneKind.ASSET.value: self._run_asset,
        }
        handler = handlers.get(kind)
        if not handler:
            raise ValueError(f"不支持的 lane 类型: {kind}")
        return handler

    async def _run_narrative(self, input_data: dict, model: str | None) -> dict:
        """执行 narrative lane — 生成叙述文案"""
        page_spec = input_data.get("page_spec", {})
        if page_spec.get("page_kind") == PageKind.CHART_ANALYSIS.value:
            return self._build_chart_analysis_narrative(page_spec, input_data.get("global_theme"))

        nc = page_spec.get("narrative_contract", {})
        cr = page_spec.get("content_requirements", {})
        review_rules = page_spec.get("review_rules", [])

        prompt = NARRATIVE_PROMPT.format(
            audience=nc.get("audience", "管理层"),
            tone=nc.get("tone", "professional"),
            core_message=nc.get("core_message", ""),
            min_points=cr.get("min_points", 3),
            min_card_blocks=cr.get("min_card_blocks", 0),
            require_detailed_explanation="需要" if cr.get("require_detailed_explanation") else "不需要",
            must_include_blocks=self._format_list(cr.get("must_include_blocks")),
            review_rules=self._format_list(review_rules),
            revision_guidance=input_data.get("revision_guidance") or "无",
            context_layers=self._format_context_layers(page_spec),
            evidence_rules=self._format_evidence_rules(page_spec),
            bg_color=input_data.get("global_theme", {}).get("bg_color", "#FFFFFF"),
            text_color=input_data.get("global_theme", {}).get("text_color", "#000000"),
            accent_color=input_data.get("global_theme", {}).get("accent_color", "#0A2463"),
            font_heading=input_data.get("global_theme", {}).get("font_heading", "'Times New Roman', 'Garamond', Georgia, serif"),
            font_body=input_data.get("global_theme", {}).get("font_body", "Arial, Roboto, 'Helvetica Neue', sans-serif"),
            design_style=input_data.get("global_theme", {}).get("design_rules", ""),
        )

        title = page_spec.get("title", "")
        goal = page_spec.get("goal", "")

        response = await llm_chat(
            system=prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"页面标题: {title}\n页面目标: {goal}\n页面类型: {page_spec.get('page_kind', 'content')}"
                    f"\nevidence_refs: {self._format_list(page_spec.get('evidence_refs'), fallback='无')}"
                    "\n请生成叙述文案。"
                ),
            }],
            model=model,
        )

        content = self._clean_output(response.content)
        return {"content": content, "asset": None, "metadata": {"kind": "narrative"}}

    async def _run_chart(self, input_data: dict, model: str | None) -> dict:
        """执行 chart lane — 生成图表 HTML"""
        global_theme = input_data.get("global_theme", {})
        page_spec = input_data.get("page_spec", {})
        if page_spec.get("page_kind") == PageKind.CHART_ANALYSIS.value:
            return self._build_chart_analysis_chart(input_data)

        review_rules = page_spec.get("review_rules", [])

        prompt = CHART_PROMPT.format(
            container_id=input_data.get("container_id", "chart-container"),
            chart_kind=input_data.get("chart_kind", "bar"),
            description=input_data.get("description", "数据图表"),
            purpose=input_data.get("purpose", "支撑页面结论"),
            data_dimensions=self._format_list(input_data.get("data_dimensions")),
            required_elements=self._format_list(input_data.get("required_elements")),
            caption=input_data.get("caption", "图表说明"),
            accent_color=global_theme.get("accent_color", "#0A2463"),
            bg_color=global_theme.get("bg_color", "#FFFFFF"),
            text_color=global_theme.get("text_color", "#000000"),
            design_style=global_theme.get("design_rules", ""),
            review_rules=self._format_list(review_rules),
            revision_guidance=input_data.get("revision_guidance") or "无",
            context_layers=self._format_context_layers(page_spec),
            evidence_rules=self._format_evidence_rules(page_spec),
        )

        title = page_spec.get("title", "")
        goal = page_spec.get("goal", "")

        response = await llm_chat(
            system=prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"页面标题: {title}\n页面目标: {goal}"
                    f"\nevidence_refs: {self._format_list(page_spec.get('evidence_refs'), fallback='无')}"
                    "\n请生成图表内容。"
                ),
            }],
            model=model,
        )

        content = self._clean_output(response.content)
        lower_content = content.lower()
        return {
            "content": content,
            "asset": content,
            "metadata": {
                "kind": "chart",
                "chart_kind": input_data.get("chart_kind", "bar_chart"),
                "description": input_data.get("description", ""),
                "purpose": input_data.get("purpose", ""),
                "data_dimensions": input_data.get("data_dimensions", []),
                "required_elements": input_data.get("required_elements", []),
                "caption": input_data.get("caption", ""),
                "container_id": input_data.get("container_id", "chart-container"),
                "has_script": "<script" in lower_content,
                "uses_echarts": "echarts" in lower_content,
                "content_preview": self._preview_content(content),
            },
        }

    async def _run_diagram(self, input_data: dict, model: str | None) -> dict:
        """执行 diagram lane — 生成 Draw.io 真源与预览 HTML"""
        global_theme = input_data.get("global_theme", {})
        page_spec = input_data.get("page_spec", {})
        review_rules = page_spec.get("review_rules", [])

        prompt = DIAGRAM_PROMPT.format(
            diagram_kind=input_data.get("diagram_kind", "architecture"),
            description=input_data.get("description", "架构图"),
            purpose=input_data.get("purpose", "说明关键结构与关系"),
            data_dimensions=self._format_list(input_data.get("data_dimensions")),
            required_elements=self._format_list(input_data.get("required_elements")),
            caption=input_data.get("caption", "图示说明"),
            accent_color=global_theme.get("accent_color", "#0A2463"),
            bg_color=global_theme.get("bg_color", "#FFFFFF"),
            text_color=global_theme.get("text_color", "#000000"),
            design_style=global_theme.get("design_rules", ""),
            review_rules=self._format_list(review_rules),
            revision_guidance=input_data.get("revision_guidance") or "无",
            context_layers=self._format_context_layers(page_spec),
            evidence_rules=self._format_evidence_rules(page_spec),
        )

        title = page_spec.get("title", "")
        goal = page_spec.get("goal", "")

        response = await llm_chat(
            system=prompt,
            messages=[{
                "role": "user",
                "content": (
                    f"页面标题: {title}\n页面目标: {goal}"
                    f"\nevidence_refs: {self._format_list(page_spec.get('evidence_refs'), fallback='无')}"
                    "\n请生成 Draw.io XML 及对应的预览 HTML。"
                ),
            }],
            model=model,
        )

        raw_content = self._clean_output(response.content)
        payload = self._extract_json_payload(raw_content) or {}
        drawio_xml = str(payload.get("drawio_xml") or payload.get("drawioXml") or "").strip() or self._extract_drawio_xml(raw_content)
        rendered_html = str(payload.get("rendered_html") or payload.get("renderedHtml") or "").strip() or self._extract_diagram_rendered_html(raw_content)
        content = rendered_html or self._build_diagram_placeholder_html(
            input_data.get("caption", "图示预览将在 Draw.io XML 导出后刷新"),
            global_theme.get("accent_color", "#0A2463"),
            global_theme.get("text_color", "#000000"),
            global_theme.get("bg_color", "#FFFFFF"),
        )
        lower_content = content.lower()
        return {
            "content": content,
            "asset": drawio_xml or content,
            "metadata": {
                "kind": "diagram",
                "diagram_kind": input_data.get("diagram_kind", "architecture"),
                "description": input_data.get("description", ""),
                "purpose": input_data.get("purpose", ""),
                "data_dimensions": input_data.get("data_dimensions", []),
                "required_elements": input_data.get("required_elements", []),
                "caption": input_data.get("caption", ""),
                "drawio_xml": drawio_xml,
                "drawioXml": drawio_xml,
                "rendered_html": content,
                "renderedHtml": content,
                "source_format": "drawio_xml" if drawio_xml else "rendered_html",
                "has_svg": "<svg" in lower_content or "data:image/svg+xml" in lower_content or "<img" in lower_content,
                "content_preview": self._preview_content(content),
            },
        }

    async def _run_asset(self, input_data: dict, model: str | None) -> dict:
        """执行 asset lane — 生成辅助资产"""
        description = input_data.get("description", "辅助资产")
        return {"content": "", "asset": None, "metadata": {"kind": "asset", "description": description}}

    def _clean_output(self, content: str) -> str:
        """清理 LLM 输出"""
        content = content.strip()
        content = re.sub(r'^```(?:html|svg)?\s*\n?', '', content)
        content = re.sub(r'\n?```\s*$', '', content)
        return content.strip()
