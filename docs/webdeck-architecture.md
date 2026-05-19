# WebDeck 功能架构文档

## 目录

1. [功能概述](#1-功能概述)
2. [整体架构与角色分工](#2-整体架构与角色分工)
3. [完整运行流程](#3-完整运行流程)
4. [各角色详解](#4-各角色详解)
5. [并发模型](#5-并发模型)
6. [超时配置](#6-超时配置)
7. [质量审查体系](#7-质量审查体系)
8. [依赖关系与调度逻辑](#8-依赖关系与调度逻辑)
9. [数据契约](#9-数据契约)
10. [前端通信协议](#10-前端通信协议)
11. [错误处理与重试机制](#11-错误处理与重试机制)
12. [最终组装与输出](#12-最终组装与输出)

---

## 1. 功能概述

WebDeck 是系统的核心产出物之一，将用户的演示需求（brief）转化为一份**可独立部署的单文件 HTML 演示稿**，具备全屏翻页、键盘导航、图表渲染、进度条等完整交互功能，并固定在 **1280×720 的 16:9 画布**内自适应缩放。

生成流程分为两个阶段：
- **规划阶段**：解析 brief → 生成结构化 DeckManifest（页面大纲）→ 等待用户确认
- **生成阶段**：用户确认后 → 多页并行生成 → 逐页质检 → Deck 级审稿 → 组装发布

---

## 2. 整体架构与角色分工

```
用户 Brief
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    DeckDirector                         │
│  入口控制器，持有 send_fn / model，自管数据库会话          │
│  协调: Planner → (用户确认) → Scheduler → Reviewer       │
│                          └→ Composer                    │
└─────────────────────────────────────────────────────────┘
    │
    ├──▶ DeckPlanner          将 brief 转化为 DeckManifest JSON
    │
    ├──▶ LaneScheduler        依赖感知的页面并发调度器
    │        │
    │        └──▶ PageOrchestrator   单页编排：Lane 流水线
    │                  │
    │                  └──▶ LaneRunner   各类 Lane 的 LLM 执行器
    │                            ├── narrative lane  叙述文案
    │                            ├── chart lane      ECharts 图表
    │                            ├── diagram lane    Draw.io 架构图
    │                            └── asset lane      辅助资产
    │
    ├──▶ DeckReviewer         页级 + Deck 级质量审查
    │
    └──▶ DeckComposer         最终 HTML 组装器
```

### 角色职责速查

| 角色 | 文件 | 核心职责 |
|------|------|----------|
| `DeckDirector` | `director.py` | 总控入口，状态机驱动，统一推送 WS 事件 |
| `DeckPlanner` | `planner.py` | Brief → DeckManifest，LLM 规划，回退兜底 |
| `LaneScheduler` | `scheduler.py` | 依赖拓扑排序，页面并发队列管理 |
| `PageOrchestrator` | `page_orchestrator.py` | 单页 Lane 流水线，Phase 顺序控制 |
| `LaneRunner` | `lane_runner.py` | 各 Lane 类型的 LLM 调用与解析 |
| `DeckReviewer` | `reviewer.py` | LLM 审稿 + 程序化规则检查 + 浏览器渲染溢出检测 |
| `DeckComposer` | `artifact_composer.py` | 将所有页面 HTML 组装成完整单文件 Web Deck |

---

## 3. 完整运行流程

### 阶段一：规划（Planner Phase）

```
1. agent_runner → 检测 webdeck 意图 → 自动触发 DeckDirector
2. Director._prepare_brief()
   └── prepare_planning_briefing()
       ├── 解析上传附件 / 网页内容
       ├── 执行 Pre-plan 研究（材料摘要、证据目录）
       └── 构建 context_layers / source_materials / research_summary
3. deck_state_store.create_project()   在 DB 创建 DeckProject 记录
4. DeckPlanner.plan()
   ├── 构造 PLANNER_SYSTEM_PROMPT（含设计规则、schema 约束）
   ├── LLM 调用（最多 2 次重试）
   ├── 解析 DeckManifest JSON
   └── _finalize_manifest()
       ├── 补全 narrative_contract / content_requirements
       ├── 注入默认资产需求（asset_requirements）
       ├── 设置 review_rules
       └── 推断默认依赖关系（closing 依赖最后 2 个核心页）
5. deck_state_store.save_manifest()    持久化 manifest
6. deck_state_store.create_pages_from_manifest()  创建所有 DeckPage 记录
7. WS 推送: webdeck_manifest           通知前端展示大纲
8. WS 推送: webdeck_status (plan_ready) 等待用户确认
```

### 阶段二：生成（Generation Phase）

```
用户确认 manifest
    │
    ▼
Director.execute_generation()
    │
    ├── 推送 webdeck_pages_init (所有页面初始状态)
    │
    ├── LaneScheduler.run()
    │   ├── 构建依赖拓扑图 (dependencies / dependents)
    │   ├── 跳过已完成页面 (断点续跑)
    │   ├── 并发执行 ready 页面 (最多 12 页同时运行)
    │   └── 每页完成后解锁下游依赖页
    │
    ├── DeckReviewer.review_deck()     Deck 级跨页审稿
    │
    ├── Director._assemble_final_deck()
    │   └── republish_project() → DeckComposer.compose()
    │       └── 组装完整单文件 HTML
    │
    └── WS 推送: webdeck_complete (含完整 HTML)
```

### 单页生成流程（PageOrchestrator）

```
Phase 1 [串行]: narrative lane
    │   └── LLM 生成叙述文案 HTML
    ▼
Phase 2 [并发]: asyncio.gather(chart lane, diagram lane, asset lane)
    │   ├── chart lane  → ECharts 图表 HTML
    │   ├── diagram lane → Draw.io XML + 预览 SVG
    │   └── asset lane  → 辅助资产
    ▼
Phase 3 [串行]: layout lane (仅高价值页面)
    │   └── LLM 组合 narrative + assets → 完整页面 HTML
    ▼
页级审稿 (DeckReviewer.review_page)
    │   ├── 程序化规则预检 (regex)
    │   ├── LLM 审稿 (PAGE_REVIEW_PROMPT)
    │   └── 浏览器渲染溢出检测 (Playwright)
    ▼
  通过 → 保存 HTML → WS 推送 webdeck_page_ready
  不通 → 最多 2 次重试（revision_guidance 回传上轮问题）
```

---

## 4. 各角色详解

### 4.1 DeckDirector

**入口分流点**，持有全局 `send_fn`（WebSocket 发送函数）和 `model`。

- 所有 DB 操作自管会话（`async with async_session()`）
- 状态机：`planning → plan_ready → generating → reviewing → completed / failed`
- 暴露 `retry_page()` 和 `retry_lane()` 接口供工具调用

### 4.2 DeckPlanner

**Brief 转 Manifest 的 LLM 规划器**。

核心设计：
- 系统提示词内嵌完整 JSON Schema，约束 LLM 输出格式
- 规划原则第 6 条：**独立页保持空 dependencies 数组**，支持并行
- `_finalize_manifest()` 在 LLM 输出基础上补全所有缺失字段
- 两次失败后使用 `_fallback_manifest()` 生成最小可用结构

**依赖推断规则**（代码 `_default_dependencies`）：
- cover / toc / content / architecture 等：**默认无依赖**
- closing 页：依赖最后 2 个核心页面
- LLM 设置的依赖直接采用，优先于默认规则

### 4.3 LaneScheduler

**依赖感知的并发调度器**。

核心数据结构：
```python
dependencies: dict[str, set[str]]   # 每页还需等待的上游 page_id 集合
dependents:   dict[str, set[str]]   # 每页完成后需要解锁的下游 page_id 集合
ready:        deque[str]            # 当前可执行的页面队列
running:      dict[Task, str]       # 正在运行的异步任务
```

调度循环：
1. 从 `ready` 队列取页面，直到达到 `max_page_concurrency`（当前 12）
2. `asyncio.wait(FIRST_COMPLETED)` 等待任意一页完成
3. 页面成功 → 从其依赖项中移除该 page_id，解锁满足条件的下游页
4. 页面失败 → `_cascade_dependency_failure()` 级联失败下游硬依赖页；软依赖页（content/comparison/closing/appendix）可继续执行

**断点续跑**：重新调度时跳过 `status=completed` 且有 HTML 的页面。

### 4.4 PageOrchestrator

**单页 Lane 流水线**，区分普通页和高价值页：

| 页面类型 | 触发 Lane | 流程 |
|----------|-----------|------|
| cover / toc | narrative | Phase 1 直接生成 |
| content / closing | narrative + (chart/diagram 按需) | Phase 1 → Phase 2 |
| summary / architecture / chart_analysis / roadmap | narrative + chart + diagram | Phase 1 → Phase 2 → Phase 3 (layout) |

**chart_analysis 特殊处理**：narrative 和 chart lane 使用内置财务模型（`_build_chart_analysis_finance_model`）确保 ROI、回收期等数据口径一致，不依赖 LLM 生成数字。

### 4.5 LaneRunner

各 Lane 类型的 **LLM 调用 + 输出解析**：

| Lane | 输出格式 | 特殊处理 |
|------|----------|----------|
| narrative | HTML 片段 | chart_analysis 走内置模板，其余 LLM 生成 |
| chart | ECharts HTML + `<script>` | 提取 `container_id`，验证 echarts 引用 |
| diagram | JSON `{drawio_xml, rendered_html}` | 多层降级解析：JSON → regex → 占位符 |
| asset | 空实现（占位） | 当前返回空内容 |

**自动重试**：遭遇瞬态错误（负载过高/rate limit/503/529）时指数退避重试，最多 3 次（2s → 8s → 32s）。

### 4.6 DeckReviewer

**三层质量检查**：

1. **程序化预检**（regex，`_programmatic_style_checks`）
   - RULE-3: 检测暗色背景、禁用颜色
   - RULE-4: 检测 box-shadow / text-shadow / perspective
   - RULE-7: 检测多栏布局缺失
   - RULE-9: 检测完整 HTML 文档输出

2. **LLM 审稿**（PAGE_REVIEW_PROMPT）
   - 逐条检查 9 条设计规则（RULE-1 至 RULE-9）
   - 评分 = 规则合规度 × 0.5 + 内容质量 × 0.5
   - 任意 error 级违规 → `passed=false`

3. **浏览器渲染溢出检测**（Playwright，`_check_render_overflow`）
   - 在 1280×720 视口渲染页面
   - 检测 scrollHeight 超界、offscreen 元素、滚动容器
   - 需要浏览器池就绪（`is_pool_ready()`）

**Deck 级审稿**：DECK_REVIEW_PROMPT 检查跨页重复、节奏、风格一致性、目录匹配、结论贯穿。

---

## 5. 并发模型

### 5.1 页面级并发

```
LaneScheduler
└── max_page_concurrency = 12  (同时运行的页面数上限)
```

**实际并发受依赖约束**：只有 `ready` 队列中的页面才能启动。如果 LLM 规划了链式依赖，实际并发远低于 12。典型场景：

- 大部分 content 页无依赖 → 批量进入 ready → 可达到接近 12 的并发
- summary 依赖 cover → 等 cover 完成后才解锁
- closing 依赖最后 2 页 → 最后执行

### 5.2 Lane 级并发（页内）

```
Phase 1: narrative lane                [单 LLM 调用，串行]
Phase 2: asyncio.gather(chart, diagram, asset)  [全并发，无限制]
Phase 3: layout lane                   [单 LLM 调用，串行]
```

**串行原因**：narrative 必须先于 chart/diagram（后者以 narrative 文案为上下文）；layout 必须在所有 Lane 完成后组合产物。

**Phase 2 最大并发数**由 `asset_requirements` 数量决定，通常为 1~3 个 LLM 调用。

### 5.3 整体并发估算

典型 12 页 deck（max_page_concurrency=12，content 页独立）：
- 并发峰值：~8 个 content 页同时运行 × 每页 2 个 Phase 2 Lane = ~16 个并发 LLM 调用
- 高价值页（architecture）额外增加 layout lane

### 5.4 并发瓶颈

| 层级 | 可配置上限 | 实际约束 |
|------|-----------|----------|
| 页面并发 | `DEFAULT_MAX_PAGE_CONCURRENCY=12` | 依赖拓扑中 ready 队列长度 |
| Lane 并发（Phase 2） | 无限制（asyncio.gather）| asset_requirements 数量（1-3） |
| LLM provider | 取决于 provider RPM | 约 30-40 并发时易触发 rate limit |

---

## 6. 超时配置

### 6.1 页面级超时（scheduler.py）

| 页面类型 | 超时（秒） | 说明 |
|----------|-----------|------|
| 默认 | 1200 | 约 20 分钟 |
| architecture | 1800 | 30 分钟，narrative 800s + diagram 600s + layout 300s |
| summary | 1800 | 同上 |
| chart_analysis | 1800 | 同上 |
| roadmap | 1800 | 同上 |

### 6.2 Lane 级超时（page_orchestrator.py）

| Lane 类型 | 超时（秒） | 说明 |
|-----------|-----------|------|
| narrative（普通页） | 400 | 5-7k tokens @ 35 tok/s ≈ 200s，留 200s 缓冲 |
| narrative（architecture） | 800 | 10k+ tokens |
| narrative（summary/chart_analysis/roadmap） | 600 | 复杂结构输出 |
| chart | 600 | SVG 复杂图表 + 多轮工具调用 |
| diagram | 600 | Draw.io XML + validation retry |
| asset | 300 | 静态资产 |
| layout | 300 | 组合 LLM，加 retry 缓冲 |

### 6.3 工具级超时（tool_dispatch.py）

| 工具 | 超时（秒） | 说明 |
|------|-----------|------|
| dispatch_subagent | 900 | 并行子 agent |
| run_code | 240 | 代码执行 |
| edit_deck_page | 240 | 页面编辑 |
| regenerate_deck_page | 600 | 单页重新生成 |
| retry_failed_deck_pages | 1800 | 批量重试失败页 |
| 其他工具 | 60（默认）| — |

---

## 7. 质量审查体系

### 7.1 页级审稿流程

```
生成 HTML
    │
    ├─1─▶ 程序化预检（regex）
    │      └── RULE-3/4/7/9 快速检测
    │
    ├─2─▶ LLM 审稿（PAGE_REVIEW_PROMPT）
    │      ├── 9 条设计规则逐条检查（RULE-1 至 RULE-9）
    │      └── 6 维度内容评分
    │
    └─3─▶ 浏览器渲染溢出检测（Playwright）
           └── 1280×720 实际渲染，检测 scrollHeight / offscreen 元素
```

### 7.2 设计规则（RULE-1 至 RULE-9）

| 规则 | 内容 | 违规级别 |
|------|------|----------|
| RULE-1 | 科技极简主义美学 | warning |
| RULE-2 | 衬线标题字体 + 无衬线正文字体 | error |
| RULE-3 | 白色背景 + 黑色文字 + 深宝蓝主色 | error |
| RULE-4 | 禁止 box-shadow / text-shadow / 3D 效果 | error |
| RULE-5 | 行动标题（So What 完整结论句） | error |
| RULE-6 | 使用复杂图表，禁止简单列表替代 | warning |
| RULE-7 | 2-3 栏 Grid 布局，信息密度 ≥70% | warning |
| RULE-8 | 禁止捏造数据，未知数字用占位符 | error |
| RULE-9 | 输出 `<section>` 片段，禁止完整 HTML 文档 | error |

### 7.3 重试机制

- 页级审稿不通过时最多重试 2 次（`MAX_PAGE_REVIEW_RETRIES=2`）
- 重试时将上轮问题作为 `revision_guidance` 注入 Lane 提示词
- 通过阈值：`score >= MIN_ACCEPTABLE_SCORE (0.85)`

### 7.4 Deck 级审稿

在所有页面完成后执行一次全局审查：
- 重复检测、节奏合理性、风格一致性
- 目录与实际页面匹配
- 核心结论贯穿全篇
- deck 级审稿的 error 降级处理（涉及"风格/背景/封面"的 error → warning）

---

## 8. 依赖关系与调度逻辑

### 8.1 依赖来源

依赖关系有两个来源（优先级从高到低）：

1. **LLM 规划时设置**：Planner 提示词第 6 条要求 LLM 只在真正需要上下文时设置依赖
2. **`_default_dependencies()` 兜底**：LLM 未设置时的默认策略
   - 绝大多数页面：`[]`（无依赖，可并行）
   - closing 页：依赖最后 2 个核心页面

### 8.2 软依赖 vs 硬依赖

| 类型 | 页面类型 | 上游失败时行为 |
|------|----------|---------------|
| 硬依赖 | architecture, summary, chart_analysis, roadmap | 级联失败，下游标记 failed |
| 软依赖 | content, comparison, closing, appendix | 上游失败后仍可尝试生成 |

软依赖定义在 `SOFT_DEPENDENCY_KINDS`，失败后从依赖集合中移除，解锁下游页。

### 8.3 调度循环伪代码

```python
while ready or running:
    # 启动新任务
    while ready and len(running) < max_page_concurrency:
        page_id = ready.popleft()
        task = asyncio.create_task(run_page_with_timeout(page_id))
        running[task] = page_id

    # 等待任意完成
    done, _ = await asyncio.wait(running.keys(), FIRST_COMPLETED, timeout=60)

    for task in done:
        if success:
            # 解锁满足条件的下游页
            for dep_id in dependents[page_id]:
                dependencies[dep_id].discard(page_id)
                if not dependencies[dep_id]:
                    ready.append(dep_id)
        else:
            _cascade_dependency_failure(page_id)
```

---

## 9. 数据契约

### 9.1 核心数据结构

```
DeckManifest
├── deck_id / title / subtitle
├── global_theme: GlobalTheme
│   ├── brand_mode / palette / motion / density
│   ├── accent_color / bg_color / text_color
│   ├── font_heading / font_body
│   └── design_rules (设计规则文本，注入所有 Lane 提示词)
├── toc: list[str]
└── pages: list[PageSpecEntry]
    ├── page_id / title / role / page_kind / goal
    ├── narrative_contract: {core_message, audience, tone}
    ├── content_requirements: {min_points, min_card_blocks, min_visual_blocks, ...}
    ├── asset_requirements: list[{type, kind, description, purpose, ...}]
    ├── evidence_refs: list[material_id]
    ├── review_rules: list[str]
    └── dependencies: list[page_id]
```

### 9.2 页面类型（PageKind）

| 值 | 说明 | 是否高价值页 |
|----|------|-------------|
| cover | 封面 | 否 |
| toc | 目录 | 否 |
| summary | 执行摘要 | ✓ |
| content | 普通内容 | 否 |
| architecture | 架构图页 | ✓ |
| chart_analysis | 图表分析 | ✓（内置财务模型） |
| roadmap | 路线图 | ✓ |
| comparison | 对比页 | 否 |
| closing | 结尾 | 否 |
| appendix | 附录 | 否 |

### 9.3 Lane 类型（LaneKind）

| 值 | 说明 | 执行阶段 |
|----|------|----------|
| narrative | 叙述文案 | Phase 1（串行，最先执行） |
| chart | ECharts 图表 | Phase 2（并发） |
| diagram | Draw.io 架构图 | Phase 2（并发） |
| asset | 辅助资产 | Phase 2（并发） |
| layout | 版式组合 | Phase 3（串行，最后执行，仅高价值页） |
| review | 页级质检 | Phase 4（审稿） |

---

## 10. 前端通信协议

所有事件通过 WebSocket `send_fn` 实时推送：

### 规划阶段事件

| 事件类型 | 触发时机 | 关键字段 |
|----------|----------|----------|
| `webdeck_status` | 状态变更 | `project_id, status, message` |
| `webdeck_manifest` | Planner 完成 | `project_id, manifest` |

### 生成阶段事件

| 事件类型 | 触发时机 | 关键字段 |
|----------|----------|----------|
| `webdeck_pages_init` | 生成开始 | `project_id, pages[]` |
| `webdeck_progress` | 每页启动时 | `current, total, page_id, completed, failed` |
| `webdeck_page_ready` | 单页完成/失败 | `page_id, page_index, html, status, error` |
| `webdeck_review` | 审稿结果 | `level(page/deck), passed, score, issues` |
| `webdeck_complete` | 全部完成 | `project_id, version, html, page_count` |
| `webdeck_status` | 阶段切换 | `status: generating/reviewing/completed/failed` |

---

## 11. 错误处理与重试机制

### 11.1 Lane 自动重试

```python
LANE_MAX_AUTO_RETRIES = 3
LANE_RETRY_BACKOFF_BASE_S = 2.0   # 2s → 8s → 32s

# 触发瞬态重试的错误模式：
_TRANSIENT_ERROR_PATTERNS = (
    "负载过高", "overloaded", "rate limit", "529", "503", "AI 模型调用失败"
)
```

### 11.2 页面审稿重试

- 审稿不通过 → 上轮 issues 注入 `revision_guidance` → 重新生成
- 最多 2 次重试（总共 3 次尝试）

### 11.3 级联失败处理

- 硬依赖页失败 → `_cascade_dependency_failure()` 递归标记所有下游页为 failed
- 软依赖页失败 → 下游页继续执行（缺少上下文但不阻断）

### 11.4 Planner 回退

- LLM 调用或 JSON 解析失败两次后 → `_fallback_manifest()` 生成基础骨架（cover + summary + content×N + closing）

### 11.5 Director 异常兜底

- 生成阶段任意异常 → `_fail_open_pages()` 将所有 in_progress 页面标记为 failed，推送前端

---

## 12. 最终组装与输出

### 12.1 DeckComposer

将所有页面 `<section>` 片段组装成**完整单文件 HTML**，包含：

| 组件 | 说明 |
|------|------|
| CSS Reset + 全局变量 | `--accent, --bg, --text, --s-surface-rgb` |
| 全屏幻灯片容器 | `.deck-slide` + `.deck-stage`（固定 1280×720） |
| P2 缩放适配 | JS `scale + translate`，自适应任意视口 |
| 顶部进度条 | 实时跟踪页码进度 |
| 右下角导航覆层 | 上/下页按钮，hover 显示 |
| 键盘导航 | `ArrowLeft/Right/Space` 翻页 |
| ECharts 延迟初始化 | `<script type="application/webdeck-chart-init">` 防止隐藏页提前执行 |
| shadcn/ui 组件类 | `.s-card / .s-grid-2/3/4 / .s-badge / .s-stat / .s-table` 等 |
| 打印支持 | `@media print` 每页独立输出 |

### 12.2 输出特性

- **单文件自包含**：除 ECharts CDN 和 Iconify CDN 外，无外部依赖
- **16:9 固定画布**：1280×720，通过 JS 缩放适配任意屏幕
- **图表延迟激活**：翻到对应页时才初始化 ECharts，避免性能浪费
- **Draw.io 双产物**：`drawio_xml`（可二次编辑）+ `rendered_html`（即时预览）

---

*文档生成自代码库，最后更新：2026-05-16*
