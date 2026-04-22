"""
Web Deck 数据契约 — 定义 DeckManifest / PageSpec / PageBundle / LaneRun 等核心 JSON 结构。
所有运行时模块通过这些契约做数据交互，保证结构显式、可审计、可恢复。

对齐 high.md §6: 新的数据契约
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ────────────────────────── 枚举定义 ──────────────────────────

class DeckStatus(str, Enum):
    """Deck 项目的整体状态"""
    DRAFT = "draft"               # 初始草稿
    PLANNING = "planning"         # 正在规划
    PLAN_READY = "plan_ready"     # 规划完成，等待用户确认
    GENERATING = "generating"     # 页面生成中
    REVIEWING = "reviewing"       # 全局审稿中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    ARCHIVED = "archived"         # 已归档


class PageStatus(str, Enum):
    """单页的状态"""
    PENDING = "pending"           # 等待执行
    IN_PROGRESS = "in_progress"   # 正在生成
    REVIEWING = "reviewing"       # 页级审稿中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    RETRYING = "retrying"         # 重试中


class LaneStatus(str, Enum):
    """子任务 lane 的状态"""
    PENDING = "pending"           # 等待执行
    RUNNING = "running"           # 执行中
    COMPLETED = "completed"       # 完成
    FAILED = "failed"             # 失败
    RETRYING = "retrying"         # 重试中
    SKIPPED = "skipped"           # 跳过


class LaneKind(str, Enum):
    """Lane 类型 — 对应 high.md §5.3 的 Specialized Subagents"""
    NARRATIVE = "narrative"       # 叙述文案
    CHART = "chart"               # 图表 (ECharts / Chart.js)
    DIAGRAM = "diagram"           # 架构图 (Draw.io / SVG)
    ASSET = "asset"               # 图片 / 图标 / 参考资产
    LAYOUT = "layout"             # 版式组合
    REVIEW = "review"             # 页级质检


class PageKind(str, Enum):
    """页面类型 — 高价值页面优先接入多 subagent"""
    COVER = "cover"                       # 封面页
    SUMMARY = "summary"                   # 执行摘要
    TOC = "toc"                           # 目录
    CONTENT = "content"                   # 普通内容页
    ARCHITECTURE = "architecture"         # 架构图页
    CHART_ANALYSIS = "chart_analysis"     # 图表分析页
    ROADMAP = "roadmap"                   # 路线图页
    COMPARISON = "comparison"             # 对比页
    CLOSING = "closing"                   # 结尾页
    APPENDIX = "appendix"                 # 附录页


class AssetKind(str, Enum):
    """资产节点类型"""
    HTML = "html"
    SVG = "svg"
    CHART_CONFIG = "chart_config"   # ECharts / Chart.js 配置
    IMAGE = "image"
    ICON = "icon"
    TEXT_BLOCK = "text_block"
    CODE_BLOCK = "code_block"


# ────────────────────────── 辅助函数 ──────────────────────────

def _new_id(prefix: str = "") -> str:
    """生成带可选前缀的唯一 UUID"""
    short = uuid.uuid4().hex[:12]
    return f"{prefix}{short}" if prefix else short


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


# ────────────────────────── 全局主题 Token ──────────────────────────

@dataclass
class GlobalTheme:
    """全局设计 Token — 控制整份 deck 的视觉一致性"""
    brand_mode: str = "executive_clean"   # 品牌风格
    palette: str = "slate_cyan"           # 色板
    motion: str = "subtle"                # 动效级别
    density: str = "medium"               # 信息密度
    font_heading: str = "'Times New Roman', 'Garamond', Georgia, serif"
    font_body: str = "Arial, Roboto, 'Helvetica Neue', sans-serif"
    accent_color: str = "#0A2463"
    bg_color: str = "#FFFFFF"
    text_color: str = "#000000"
    design_rules: str = ""  # 用户指定或默认设计风格规则，透传给所有生成 agent

    def to_dict(self) -> dict:
        return {
            "brand_mode": self.brand_mode,
            "palette": self.palette,
            "motion": self.motion,
            "density": self.density,
            "font_heading": self.font_heading,
            "font_body": self.font_body,
            "accent_color": self.accent_color,
            "bg_color": self.bg_color,
            "text_color": self.text_color,
            "design_rules": self.design_rules,
        }


# ────────────────────────── DeckManifest ──────────────────────────

@dataclass
class NarrativeContract:
    """叙述契约 — 指导单页内容生成的约束"""
    core_message: str = ""          # 核心信息
    audience: str = "管理层"         # 目标受众
    tone: str = "professional"      # 语调
    max_words: int = 0              # 兼容旧字段，当前运行时不再用它限制长度

    def to_dict(self) -> dict:
        return {
            "core_message": self.core_message,
            "audience": self.audience,
            "tone": self.tone,
            "max_words": self.max_words,
        }


@dataclass
class ContentRequirements:
    """信息密度契约 — 约束单页最低信息量与结构块分配"""
    min_points: int = 3
    require_detailed_explanation: bool = False
    min_card_blocks: int = 0
    min_visual_blocks: int = 0
    must_include_blocks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "min_points": self.min_points,
            "require_detailed_explanation": self.require_detailed_explanation,
            "min_card_blocks": self.min_card_blocks,
            "min_visual_blocks": self.min_visual_blocks,
            "must_include_blocks": self.must_include_blocks,
        }


@dataclass
class AssetRequirement:
    """资产需求 — PageSpec 中声明该页需要的资产类型"""
    type: str = "text_block"       # diagram / chart / asset / text_block
    kind: str = ""                 # architecture / before_after / metric_cards 等
    description: str = ""          # 对资产的描述
    purpose: str = ""              # 该资产承担的论证目的
    data_dimensions: list[str] = field(default_factory=list)
    required_elements: list[str] = field(default_factory=list)
    caption: str = ""              # 图表/图示说明文案

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "kind": self.kind,
            "description": self.description,
            "purpose": self.purpose,
            "data_dimensions": self.data_dimensions,
            "required_elements": self.required_elements,
            "caption": self.caption,
        }


@dataclass
class PageSpecEntry:
    """DeckManifest 中每页的规格定义 (对齐 high.md §6.2)"""
    page_id: str = ""
    title: str = ""
    role: str = "content"                  # summary / content / architecture / chart / roadmap
    page_kind: str = "content"             # PageKind 值
    goal: str = ""                         # 该页目标
    narrative_contract: NarrativeContract = field(default_factory=NarrativeContract)
    content_requirements: ContentRequirements = field(default_factory=ContentRequirements)
    asset_requirements: list[AssetRequirement] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)                  # 引用的素材 ID
    review_rules: list[str] = field(default_factory=list)                   # 审稿规则
    dependencies: list[str] = field(default_factory=list)                   # 依赖的其他 page_id

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "role": self.role,
            "page_kind": self.page_kind,
            "goal": self.goal,
            "narrative_contract": self.narrative_contract.to_dict(),
            "content_requirements": self.content_requirements.to_dict(),
            "asset_requirements": [a.to_dict() for a in self.asset_requirements],
            "evidence_refs": self.evidence_refs,
            "review_rules": self.review_rules,
            "dependencies": self.dependencies,
        }


@dataclass
class DeckManifest:
    """
    Deck 规划产物 — 机器可读的演示大纲 (对齐 high.md §6.1)。
    由 Deck Planner 产出，供 Lane Scheduler 消费。
    """
    deck_id: str = field(default_factory=lambda: _new_id("deck_"))
    title: str = ""
    subtitle: str = ""
    global_theme: GlobalTheme = field(default_factory=GlobalTheme)
    toc: list[str] = field(default_factory=list)
    pages: list[PageSpecEntry] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "deck_id": self.deck_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "global_theme": self.global_theme.to_dict(),
            "toc": self.toc,
            "pages": [p.to_dict() for p in self.pages],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DeckManifest":
        """从 JSON dict 反序列化"""
        theme_data = data.get("global_theme", {})
        theme = GlobalTheme(**{k: v for k, v in theme_data.items() if k in GlobalTheme.__dataclass_fields__})

        pages = []
        for p in data.get("pages", []):
            nc_data = p.get("narrative_contract", {})
            nc = NarrativeContract(**{k: v for k, v in nc_data.items() if k in NarrativeContract.__dataclass_fields__})
            cr_data = p.get("content_requirements", {})
            cr = ContentRequirements(**{k: v for k, v in cr_data.items() if k in ContentRequirements.__dataclass_fields__})
            ar = [
                AssetRequirement(**{k: v for k, v in a.items() if k in AssetRequirement.__dataclass_fields__})
                for a in p.get("asset_requirements", [])
            ]
            pages.append(PageSpecEntry(
                page_id=p.get("page_id", ""),
                title=p.get("title", ""),
                role=p.get("role", "content"),
                page_kind=p.get("page_kind", "content"),
                goal=p.get("goal", ""),
                narrative_contract=nc,
                content_requirements=cr,
                asset_requirements=ar,
                evidence_refs=p.get("evidence_refs", []),
                review_rules=p.get("review_rules", []),
                dependencies=p.get("dependencies", []),
            ))

        return cls(
            deck_id=data.get("deck_id", _new_id("deck_")),
            title=data.get("title", ""),
            subtitle=data.get("subtitle", ""),
            global_theme=theme,
            toc=data.get("toc", []),
            pages=pages,
            created_at=data.get("created_at", _now_iso()),
        )


# ────────────────────────── AssetNode ──────────────────────────

@dataclass
class AssetNode:
    """资产节点 — 页面中的原子资产 (对齐 high.md §6.3)"""
    asset_id: str = field(default_factory=lambda: _new_id("asset_"))
    kind: str = "text_block"    # AssetKind 值
    content: str = ""           # HTML / SVG / JSON config / URL
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "kind": self.kind,
            "content": self.content,
            "metadata": self.metadata,
        }


# ────────────────────────── ReviewReport ──────────────────────────

@dataclass
class ReviewReport:
    """评审报告 — 由 Reviewer Agent 产出"""
    passed: bool = False
    score: float = 0.0
    issues: list[dict] = field(default_factory=list)    # [{level, message, suggestion}]
    suggestions: list[str] = field(default_factory=list)
    reviewed_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": self.score,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "reviewed_at": self.reviewed_at,
        }


# ────────────────────────── PageBundle ──────────────────────────

@dataclass
class PageBundle:
    """
    页面产出物 — 单页的最终可组合结果 (对齐 high.md §6.3)。
    包含渲染好的 HTML、CSS token、JS 模块和子资产列表。
    """
    page_id: str = ""
    status: str = "pending"          # PageStatus 值
    html: str = ""                   # <section data-page-id="...">...</section>
    css_tokens: dict = field(default_factory=dict)   # 页级 CSS 变量覆盖
    js_modules: list[str] = field(default_factory=list)
    artifacts: list[AssetNode] = field(default_factory=list)
    review: ReviewReport | None = None

    def to_dict(self) -> dict:
        return {
            "page_id": self.page_id,
            "status": self.status,
            "html": self.html,
            "css_tokens": self.css_tokens,
            "js_modules": self.js_modules,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "review": self.review.to_dict() if self.review else None,
        }


# ────────────────────────── LaneRun ──────────────────────────

@dataclass
class LaneRunSpec:
    """Lane 运行规格 — 描述一个子任务的执行计划"""
    lane_id: str = field(default_factory=lambda: _new_id("lane_"))
    page_id: str = ""
    kind: str = "narrative"      # LaneKind 值
    status: str = "pending"      # LaneStatus 值
    input_data: dict = field(default_factory=dict)   # 输入参数
    output_data: dict = field(default_factory=dict)  # 输出结果
    error: str | None = None
    retries: int = 0
    max_retries: int = 2
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "lane_id": self.lane_id,
            "page_id": self.page_id,
            "kind": self.kind,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "error": self.error,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


# ────────────────────────── Deck Shell 配置 ──────────────────────────

@dataclass
class DeckShellConfig:
    """Deck Shell 配置 — 控制最终 Web Deck 的壳层"""
    enable_toc: bool = True           # 是否显示目录
    enable_page_numbers: bool = True  # 是否显示页码
    enable_progress: bool = True      # 是否显示进度条
    enable_url_sync: bool = True      # 是否 URL 同步
    transition: str = "slide"         # 页面切换效果
    auto_play: bool = False           # 是否自动播放
    auto_play_interval: int = 5000    # 自动播放间隔 (ms)

    def to_dict(self) -> dict:
        return {
            "enable_toc": self.enable_toc,
            "enable_page_numbers": self.enable_page_numbers,
            "enable_progress": self.enable_progress,
            "enable_url_sync": self.enable_url_sync,
            "transition": self.transition,
            "auto_play": self.auto_play,
            "auto_play_interval": self.auto_play_interval,
        }
