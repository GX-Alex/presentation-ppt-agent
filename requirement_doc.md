

 ## 通用智能体平台 — 完整需求文档（V3.1）

---

### 一、项目概述

#### 1.1 产品定位

构建一个通用 AI 智能体平台，采用 learn-claude-code 提出的核心理念（Agent Loop + Tool Dispatch + Skill 按需加载 + Subagent 上下文隔离 + TodoWrite 计划追踪），**一阶段聚焦 PPT/文档生成模块**，同时预留通用对话、代码分析、深度研究等扩展能力的架构空间。

#### 1.2 核心设计理念（来自 learn-claude-code）

| 理念 | 原文 | 在本项目中的体现 |
|---|---|---|
| Agent Loop | "Bash is all you need" — `while + stop_reason + tool_dispatch` | 主循环不变，所有能力通过 Tool/Skill 扩展 |
| Tool Dispatch | "The loop didn't change" — 加工具只加 handler | Tool 为通用能力执行器，格式统一 |
| TodoWrite | "Plan before you act" — 可见计划提升完成率 | PPT 生成全程有计划列表+进度推送 |
| Subagent | "Process isolation = context isolation" — 独立 `messages[]` | 每页幻灯片由独立子 Agent 生成 |
| Skill | "Load on demand, not upfront" — 两层懒加载 | 领域知识按需注入，用户可自定义 |
| Compact | "Strategic forgetting" — 上下文压缩 | 四层记忆+自动压缩+记忆刷盘 |

#### 1.3 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | FastAPI + Python 3.12 | WebSocket 原生支持、LLM 生态最好 |
| Agent 框架 | 自实现 Agent Loop（参考 learn-claude-code） | 轻量可控，不依赖重框架 |
| 前端 | Next.js 15 + TypeScript + Tailwind CSS + shadcn/ui | 现代化组件丰富 |
| PPT 渲染 | reveal.js 5.x | 70.6k stars，纯 HTML `<section>`，API 完善 |
| 单页编辑 | contentEditable + 浮动工具栏 | 轻量，与 reveal.js 无缝集成 |
| 实时通信 | WebSocket（原生） | FastAPI 内置支持 |
| LLM | 多模型可配置，`litellm` 统一接口 | 默认 DeepSeek V3，可选 Claude / GPT-4o |
| 文档解析 | PyMuPDF + python-docx + python-pptx + openpyxl | 覆盖 PDF/Word/PPT/Excel/MD |
| 图片搜索 | Pexels API（免费 200req/h） | 零成本起步 |
| PDF 导出 | Playwright headless + DeckTape | 高质量截图 |
| PPTX 导出 | python-pptx + Playwright screenshot | 截图保真 + 可编辑文字双模式 |
| 数据库 | SQLite（一阶段）→ PostgreSQL + pgvector（扩展时） | 零配置启动 |
| 文件存储 | 本地 `data/` 目录 → 后续迁移对象存储 | 简单起步 |
| 部署 | Docker Compose（本地自托管，后续可扩展为 SaaS） | 一键启动 |

---

### 二、系统架构

#### 2.1 整体拓扑

```
┌─────────────────── 页面体系 ──────────────────────────┐
│    /chat/:id      /assets      /gallery     /settings  │
│       │              │            │             │       │
│       ▼              ▼            ▼             ▼       │
│  ┌──────────────────────────────────────────────────┐  │
│  │            Frontend (Next.js 15)                  │  │
│  │  Chat+Preview │ Assets │ Gallery │ Settings       │  │
│  └───────────────────┬──────────────────────────────┘  │
│                      │ WebSocket + REST                 │
│  ┌───────────────────▼──────────────────────────────┐  │
│  │          API Gateway (FastAPI)                     │  │
│  │  /ws/chat │ /api/files │ /api/tasks │ /api/assets │  │
│  └───────────────────┬──────────────────────────────┘  │
│                      │                                  │
│  ┌───────────────────▼──────────────────────────────┐  │
│  │          Coordinator Agent (主循环)                │  │
│  │  意图识别 → 路由 → TodoWrite 计划 → 调度执行       │  │
│  │         ┌──── Skills ────┐                        │  │
│  │         │ Layer1: 菜单    │                        │  │
│  │         │ Layer2: 按需加载 │                        │  │
│  │         └────────────────┘                        │  │
│  └──┬─────────┬─────────┬─────────┬─────────────────┘  │
│     │         │         │         │                     │
│  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──────┐              │
│  │ PPT │  │研究 │  │代码 │  │通用对话  │              │
│  │Agent│  │Agent│  │分析 │  │(直接LLM)│              │
│  │     │  │     │  │Agent│  │         │              │
│  └──┬──┘  └──┬──┘  └──┬──┘  └─────────┘              │
│     │        │        │                                │
│  ┌──▼────────▼────────▼─────────────────────────────┐  │
│  │              Tool Layer（系统内置）                 │  │
│  │  parse_document │ web_search │ generate_ppt_deck  │  │
│  │  parse_project  │ fetch_url  │ edit_slide         │  │
│  │  image_search   │ read_project_file │ load_skill │  │
│  │  save_to_memory │ search_memory                     │  │
│  └──────────────────────────────────────────────────┘  │
│                      │                                  │
│  ┌───────────────────▼──────────────────────────────┐  │
│  │              Data Layer                           │  │
│  │  SQLite/PostgreSQL │ 本地文件存储 │ Vector Index  │  │
│  │  tasks │ messages │ assets │ memories │ skills    │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

#### 2.2 Agent 主循环（核心）

```python
# 伪代码 — 主循环不变，所有能力通过 Tool/Skill 扩展
def agent_loop(messages, tools, skills):
    while True:
        response = llm.chat(
            system=build_system_prompt(skills, user_memories),
            messages=messages,
            tools=tools,
        )
        messages.append({"role": "assistant", "content": response.content})
        persist_message(response)  # 持久化到 DB
        push_to_client(response)   # WebSocket 推送

        if response.stop_reason != "tool_use":
            return  # 结束循环

        for tool_call in response.tool_calls:
            result = dispatch_tool(tool_call.name, tool_call.input)
            messages.append({"role": "tool", "content": result})
            persist_message(result)
            push_to_client(tool_call, result)
```

---

### 三、页面体系与导航

#### 3.1 左侧导航栏（参考 MiniMax Agent）

```
┌──────────────────────────┐
│  [Logo]            [收起] │
│                          │
│  ⊕ 新建任务               │  → 创建新对话，进入 /chat/new
│  🔍 搜索                  │  → 全局搜索（资产+任务+画廊）
│  📁 资产                  │  → /assets 用户资产管理
│  🔲 画廊                  │  → /gallery 社区作品展示
│                          │
│  ── 实验室 ──             │  （二阶段扩展区）
│  🤖 探索专家               │  → 专家模板市场
│                          │
│  ── 任务记录 ──           │
│  📋 任务标题1...           │  → 点击跳转 /chat/:id1
│  📋 任务标题2...           │  → 点击跳转 /chat/:id2
│  📋 ...                   │
│  [查看全部]               │
└──────────────────────────┘
```

- 侧边栏可收起/展开（快捷键 `⌘.`）
- 任务记录按时间倒序，最新在上
- 支持任务标题搜索、重命名、删除、归档

#### 3.2 资产页（/assets）

```
┌──────────────────────────────────────────────────────────────┐
│  资产                                          [搜索框]      │
│                                                              │
│  [AI生成 ▾]  全部 | 文档 | PPT | 代码 | 图片 | 🔌 Skill      │
│   ├ 我的上传                                                  │
│   └ AI生成                                                   │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 缩略图    │ │ 缩略图    │ │ 📋       │ │ 缩略图    │       │
│  │ 报告.pdf  │ │ AI趋势.ppt│ │ 品牌规范  │ │ logo.png │       │
│  │ 1.2MB     │ │ AI生成    │ │ ✅ 已验证  │ │ 256KB    │       │
│  │ 2/25      │ │ 2/24      │ │ 调用23次  │ │ 2/20     │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                              │
│  点击文件 → 预览/下载                                          │
│  点击Skill → 编辑/测试/发布                                    │
│  点击AI生成的文件 → 跳转到原对话                                │
└──────────────────────────────────────────────────────────────┘
```

- Tab 分类筛选按文件类型
- 下拉区分来源（用户上传 / AI 生成）
- Skill tab 显示用户自定义 Skill 卡片，含状态（草稿/已验证）、调用次数
- 支持批量下载、删除

#### 3.3 画廊页（/gallery）

```
┌──────────────────────────────────────────────────────────────┐
│  画廊                                                        │
│                                                              │
│  推荐 | PPT | 研究 | 代码 | 🔌 Skill | 其他                   │
│                                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │  [预览图]     │ │  [预览图]     │ │  [预览图]     │         │
│  │ 金融科技PPT   │ │ 教学设计PPT   │ │ 品牌规范Skill │         │
│  │ @用户A       │ │ @系统预置     │ │ @用户B       │         │
│  │ Fork 16次    │ │ Fork 45次    │ │ Fork 12次    │         │
│  │ [预览] [Fork] │ │ [预览] [Fork] │ │ [预览] [Fork] │         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
│                                                              │
│  点击预览 → 弹窗查看完整内容                                    │
│  点击Fork → 复制到自己的资产空间                                │
└──────────────────────────────────────────────────────────────┘
```

- 系统预置模板 + 用户发布的公开作品
- 画廊新增 Skill tab，展示公开的 Skill 模板
- Fork（重组）功能：一键复制到自己资产空间并自动关联

**画廊内容治理**（一阶段基础规则）：
- 发布前：LLM 自动检测是否包含敏感/私密信息（如企业内部数据、个人隐私），检测到则弹窗警告要求用户二次确认
- 用户发布的内容默认带版权声明（CC BY 4.0 或用户自选许可协议）
- 支持举报功能（一键举报 → 管理员审核队列，一阶段人工审核）
- Skill 公开发布不允许包含 API Key、密码等凭证信息（格式校验阶段自动检测）

#### 3.4 页面间关联链路

为了让用户能清晰地在"任务 ↔ 资产 ↔ 画廊"之间流转，明确以下跳转关系：

| 起点 | 动作 | 终点 |
|---|---|---|
| 任务对话中 AI 生成了 PPT | 自动沉淀到资产 | 资产页可见该 PPT，标注"来源任务：xxx"，点击可回跳 |
| 资产页 - AI 生成的文件 | 点击"来源任务" | 跳转到 `/chat/:taskId`，定位到生成该文件的上下文 |
| 资产页 - 某个 Skill | 点击"发布到画廊" | 画廊新增该 Skill 条目，标注原作者 |
| 画廊 - 某个 PPT/Skill | 点击"Fork" | 复制到自己资产空间，标注"来自 @作者/作品名"，可一键回到画廊原始页 |
| 画廊 - Fork 得到的 Skill | 在资产空间修改 | 修改后可发布为"新版本"到画廊，保持与原作品的 Fork 链关系 |
| 侧边栏 - 任务记录 | 点击某条任务 | 跳转到 `/chat/:taskId`，恢复对话上下文+预览区状态 |

**Skill 画廊版本策略**：发布到画廊的 Skill 一经发布即冻结为不可变版本。用户修改后想更新画廊 → 发布为新版本（v2, v3...），旧版本继续可用，避免其他用户 Fork 后的依赖断裂。

#### 3.5 任务对话页（/chat/:id）— 主工作区

```
┌──────────────────────────────────────────────────────────────────┐
│  Logo   [新建任务]  [历史记录]                  [设置] [用户]      │
├──────────────────────┬───────────────────────────────────────────┤
│                      │                                           │
│   Chat Panel         │   Preview Panel                           │
│   (可收缩 ~40%)      │   (可拉伸 ~60%)                           │
│                      │                                           │
│  ┌─ 🔧 正在分析... ─┐ │  ── 随任务类型动态切换 ──                   │
│  │ (状态摘要，       │ │                                           │
│  │  不展示推理细节)  │ │  PPT任务 → reveal.js 幻灯片预览             │
│  └─────────────────┘ │  代码分析 → 项目树 + Monaco 代码查看          │
│                      │  研究报告 → Markdown 文档渲染                │
│  📎 已上传：报告.pdf  │  通用对话 → 侧边栏隐藏或最小化               │
│                      │                                           │
│  📋 生成计划：        │  ─── PPT 模式下的预览区 ───                 │
│  ✅ 1. 分析参考文档   │  ┌────────────────────────────────┐       │
│  ✅ 2. 生成大纲      │  │                                │       │
│  ▶️  3. 第3/10页     │  │    [当前幻灯片全屏渲染]           │       │
│  ⬚ 4. 第4/10页      │  │                                │       │
│                      │  │       ← 编辑工具栏 →             │       │
│  [直接生成] [先讨论]  │  │                                │       │
│                      │  └────────────────────────────────┘       │
│  💬 输入消息...       │                                           │
│  📎 [发送]           │  ┌───┬───┬───┬───┬───┬───┬───┬───┐      │
│                      │  │ 1 │ 2 │*3*│ 4 │ 5 │ 6 │ 7 │ 8 │      │
│                      │  └───┴───┴───┴───┴───┴───┴───┴───┘      │
│                      │  缩略图导航栏                               │
│                      │                                           │
│                      │  [全屏] [HTML↓] [PDF↓] [PPTX↓]           │
├──────────────────────┴───────────────────────────────────────────┤
│  进度条：████████░░░░ 生成中 3/10 页 — "市场分析"                  │
└──────────────────────────────────────────────────────────────────┘
```

---

### 四、核心功能模块

#### 4.1 对话与意图路由

聊天对话框**不局限于 PPT 场景**，Coordinator Agent 先进行意图识别再路由：

| 意图分类 | 触发示例 | Agent 行为 | 预览区 |
|---|---|---|---|
| `ppt` | "帮我做一个10页的AI趋势PPT" | 进入 PPT 工作流 | reveal.js 幻灯片 |
| `research` | "帮我研究2026年AI市场规模" | 联网搜索+汇总报告 | Markdown 文档 |
| `code_analysis` | "分析我上传的项目代码" | 项目结构分析+报告 | 项目树+代码 |
| `chat` | "量子计算是什么？" | 直接 LLM 回复 | 隐藏/最小化 |
| `composite` | "先研究AI趋势，再做PPT" | 拆解为研究→PPT 串行子任务 | 按阶段切换 |

- 意图识别后通过 WebSocket 推送 `{type: "intent_detected", intent: "ppt"}` 通知前端切换预览模式
- 同一对话中可切换意图（如先聊天再做 PPT）

#### 4.2 文件上传与解析

**支持格式**：

| 格式 | 库 | 解析输出 |
|---|---|---|
| PDF | `PyMuPDF (fitz)` | 文本 + 表格(Markdown) + 图片描述 |
| Word (.docx) | `python-docx` | 段落 + 标题层级 → 结构化 Markdown |
| Markdown (.md) | 直接读取 | 原文 |
| PPT (.pptx) | `python-pptx` | 每页标题/内容/布局类型 → JSON |
| Excel (.xlsx) | `openpyxl` | Sheet 名 + 表格数据 → Markdown 表格 |
| 代码文件 | 直接读取 + `pygments` | 源码文本 + 语言检测 |
| 项目文件夹 | `<input webkitdirectory>` 或 Zip 上传 | 项目结构树 + 语言/框架/依赖检测 |
| Git 仓库 URL | 服务端 `git clone --depth=1` | 同项目文件夹 |
| 图片 | `Pillow` 元数据 | 尺寸/格式（OCR 二阶段） |

**上传交互**：
- 聊天框底部附件按钮（📎）+ 拖拽上传
- 支持多文件、文件夹同时上传
- 上传后在对话中展示文件摘要卡片（文件名+类型+大小+页数）
- 解析按需进行（`parse_document` 工具在 Agent 需要时调用）
- 文件存储路径：`data/uploads/{user_id}/{task_id}/`

**项目代码上传特殊流程**：
1. 上传后自动生成项目结构树（排除 `node_modules`/`.git`/`__pycache__` 等）
2. 检测主要语言、框架（通过 `package.json`/`requirements.txt` 等）
3. 生成项目摘要卡片展示在对话中
4. Agent 通过 `read_project_file(path)` 工具按需读取具体文件

**文件上传安全约束**：

| 约束项 | 规则 |
|---|---|
| 单文件大小 | ≤ 50MB（代码/文档），≤ 200MB（Zip 压缩包） |
| 总存储配额 | 单用户 ≤ 2GB（一阶段），可配置 |
| 文件类型白名单 | 文档类：`.pdf .docx .md .pptx .xlsx .csv .txt`；代码类：`.py .js .ts .jsx .tsx .java .go .rs .c .cpp .h .css .html .json .yaml .yml .toml .xml .sql .sh`；图片类：`.png .jpg .jpeg .gif .svg .webp`；压缩包：`.zip`；**禁止**：`.exe .dll .so .bat .cmd .msi .dmg .app .sh`（可执行文件） |
| Zip 解压安全 | 防 Zip Slip（路径穿越检测），解压后总大小 ≤ 500MB，目录深度 ≤ 15 层，单压缩包文件数 ≤ 5000 |
| 项目文件读取 | `read_project_file(path)` 仅允许读取 `data/uploads/{user_id}/{task_id}/` 下的文件，路径做 `realpath` 规范化后校验前缀 |

#### 4.3 需求澄清（Superpower）

当用户需求不够清晰时，Agent 提供两条路径（通过 UI 按钮切换）：

**路径 A — 直接生成**：Agent 自行推断细节，直接进入大纲阶段

**路径 B — 先讨论需求**：
1. Agent 加载 `requirement_clarification` Skill
2. 按策略逐步追问：
   - 目标受众（内部汇报/客户提案/学术演讲/教学课件）
   - 风格偏好（商务简约/科技感/学术严谨/活泼创意）
   - 页数要求 & 时长估算
   - 重点章节或必须包含的内容
   - 品牌色/Logo（可选，可关联用户自定义 Skill）
   - 参考文档的使用方式（提取全部 vs 仅某章节）
3. 多轮对话后确认方案，进入大纲阶段

**前端交互**：在 Agent 首次响应时展示 `[直接生成]` `[先讨论需求]` 两个按钮，通过 WebSocket 发送 `{type: "mode", value: "direct"|"discuss"}`。

#### 4.4 PPT 生成引擎

##### 4.4.1 生成流程

```
用户需求 → [需求澄清] → generate_ppt_deck 规划与生成 → 预览 → 修改 → 导出
```

**零到一生成阶段**：
- Agent 调用 `generate_ppt_deck(topic, num_slides, theme, title, requirements)`
- MiniMax 插件工作流先生成页面蓝图，再返回结构化 `outline`、逐页 `slides` 和 DeckSpec 相关数据
- 后端沿用 `outline` → `slide_ready` → `ppt_completed` 事件协议，前端仍可先看大纲再逐页预览

**后续编辑**：
- 用户如需细调单页内容，继续调用 `edit_slide`
- 导出阶段基于持久化后的 DeckSpec / HTML 预览数据生成最终产物

##### 4.4.2 数据模型

```json
{
  "id": "pres_xxx",
  "task_id": "task_xxx",
  "title": "AI 趋势 2026",
  "theme": {
    "primary_color": "#2563EB",
    "bg_color": "#0f172a",
    "font_family": "Inter, 思源黑体",
    "style": "tech_dark"
  },
  "slides": [
    {
      "id": "slide-1",
      "index": 0,
      "type": "title",
      "html": "<section>...</section>",
      "speaker_notes": "开场白...",
      "version": 1,
      "versions": [
        { "version": 1, "html": "...", "timestamp": "...", "source": "ai" }
      ]
    }
  ],
  "outline": [
    { "title": "封面", "bullets": ["标题", "副标题", "日期"] }
  ],
  "source_docs": ["asset_xxx"],
  "created_at": "...",
  "updated_at": "..."
}
```

**幻灯片类型**：`title` | `content` | `two-column` | `image-focused` | `chart` | `quote` | `section-break` | `ending`

##### 4.4.3 过程展示

PPT 生成过程中，前端实时展示的信息分为两个层级：

| 展示元素 | 默认可见 | 说明 |
|---|---|---|
| **执行状态摘要** | ✅ 始终可见 | 一句话说明当前在做什么（"正在分析参考文档"、"正在生成第3页"） |
| **计划步骤列表** | ✅ 始终可见 | 带 ✅/▶️/⬚ 状态的 TodoWrite 列表 |
| **进度条** | ✅ 始终可见 | 底部全宽进度条 + 当前页描述 |
| **实时预览** | ✅ 始终可见 | 每页完成后即出现在右侧 reveal.js |
| **Thinking 推理细节** | ❌ 默认隐藏 | 通过设置页"开发者模式"开关启用；启用后以 `<details>` 折叠块可展开查看 |

Thinking 默认隐藏的理由：推理过程可能冗长、包含不必要的中间信息，对普通用户造成干扰。仅在调试或高级用户场景下按需开启。

#### 4.5 侧边栏预览与浏览

- **载体**：右侧可拉伸面板，内嵌 `<iframe>` 加载 reveal.js 演示
- **导航**：底部缩略图导航条 + 左右箭头 + 键盘方向键
- **选中态**：点击缩略图 → 高亮 → 聊天框显示 `[已选中第N页]`，后续修改指令自动绑定该页
- **全屏预览**：支持全屏模式展示（ESC 退出）
- **动态切换**：根据意图自动切换预览内容（PPT→幻灯片，代码→文件树，研究→Markdown）

#### 4.6 单页编辑（核心交互）

**两种编辑模式并存**：

**A. WYSIWYG 直接编辑**：
- 点击预览区某页 → 进入编辑态
- `contentEditable="true"` 激活文字编辑
- 浮动工具栏提供基础格式操作

**一阶段支持的编辑能力清单**：

| 类别 | 支持 ✅ | 不支持 ❌（二阶段或自然语言走） |
|---|---|---|
| **文本** | 修改标题/正文文字、换行 | — |
| **基础格式** | 加粗、斜体、字号（3档）、文字颜色（调色板） | 下划线、删除线、字间距 |
| **对齐** | 左对齐、居中、右对齐 | 两端对齐 |
| **图片** | 替换图片 URL、上传图片插入 | 裁剪、抠图、滤镜、大小拖拽 |
| **列表** | 无序列表、有序列表 | 嵌套列表、缩进调整 |
| **布局** | — | 自由拖拽布局、栅格编辑 |
| **表格** | — | 可视化表格编辑（通过自然语言指令） |
| **图表** | — | 可视化图表编辑器（通过自然语言指令） |

**contentEditable 已知风险与防护措施**：
- **粘贴清洗**：拦截 `paste` 事件，用 `DOMPurify` 过滤外部粘贴内容中的脏 HTML/CSS/JS
- **中文输入法兼容**：监听 `compositionstart/end` 事件，期间禁止触发保存/同步
- **撤销栈**：不依赖浏览器原生 undo，自行维护 html 版本快照栈，Ctrl+Z 回退到上一个快照
- **样式隔离**：编辑区的 CSS 用 scoped/shadow DOM 隔离，防止 reveal.js 全局样式干扰编辑器

**B. 自然语言修改**：
- 选中某页 + 在聊天框输入指令（如"加一个柱状图展示市场份额"）
- Agent 接收：当前页 HTML + 修改指令 → 生成新 HTML → 替换预览
- 单页替换，其余页不受影响
- 批量修改："所有页面换成深色主题" → Agent 逐页修改

**版本控制**：
- 每次修改保存版本快照（html + 时间戳 + 来源：`wysiwyg` | `ai` | `fork`）
- 支持查看某页版本历史列表、一键回退到任意版本

#### 4.7 导出

| 格式 | 技术方案 | 用户说明文案 |
|---|---|---|
| **HTML** | 打包 reveal.js + slides HTML + 内嵌资源为 zip | "网页格式 — 离线可直接用浏览器打开浏览" |
| **PDF** | Playwright headless `page.pdf({landscape: true})` 或 DeckTape | "PDF — 适合分享和打印，每页高保真" |
| **PPTX（保真）** | Playwright 截图每页 → python-pptx 图片拼接 | "PPTX 保真版 — 视觉效果与预览完全一致，但页面内容为图片不可编辑" |
| **PPTX（可编辑）** | 解析 HTML 结构 → python-pptx 文本框/形状 | "PPTX 可编辑版 — 文字可在 PowerPoint 中修改，但排版样式可能与预览有差异" |

导出按钮下拉菜单展示四个选项，每个附带上述说明文案，让用户在下载前清楚知道差异。
导出完成后通过 WebSocket 推送 `{type: "export_ready", format, url}`，文件同时存入用户资产空间。

#### 4.8 深度研究与外部搜索

**三种搜索场景**：

| 场景 | 用户行为 | Agent 行为 | 工具 |
|---|---|---|---|
| **按需自动搜索** | 无需操作，Agent 自行判断知识缺口 | 自行调用 `web_search` 补充信息 | `web_search` |
| **指定关键词搜索** | "搜索2026年 AI 市场规模" 或 "在 arxiv.org 上搜索 xxx" | Agent 调用 `web_search`，支持 `site:` 参数限制搜索域 | `web_search(query, site?)` |
| **指定 URL 阅读** | 发送 URL 或说"帮我读一下这个网页 https://..." | Agent 自动识别 URL → 调用 `read_url` 抓取内容 → 展示摘要 | `read_url` |

**搜索工具栈**：

| 工具 | 用途 | 方案 |
|---|---|---|
| `web_search(query, site?)` | 关键词搜索（支持 site 域限制） | 优先 Tavily（免费1000次/月，准确率93.3%）；备选 DuckDuckGo |
| `read_url(url)` | 读取指定网页 | `jina-ai/reader`（r.jina.ai 免费）或 `trafilatura` 本地解析 |
| `search_image(query)` | 搜索配图 | Pexels API（免费） |

**URL 抓取安全约束**：

| 约束项 | 规则 |
|---|---|
| 内网地址防护 | 禁止访问 `127.0.0.0/8`、`10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16`、`169.254.0.0/16`、`::1`、`fc00::/7` 等内网/保留 IP 段（SSRF 防护） |
| 重定向限制 | 最多跟随 3 次重定向，每次跳转目标均需过内网检测 |
| 响应大小限制 | 单次抓取内容 ≤ 5MB |
| 超时 | 连接超时 10s，读取超时 30s |
| 协议限制 | 仅允许 `http://` 和 `https://` |

**搜索过程展示**：
- 搜索开始：`{type: "search_start", query, source}`
- 搜索结果：`{type: "search_result", results: [{title, url, snippet}]}`
- PPT 中自动添加信息来源脚注引用

---

### 五、工具（Tool）体系

**定义**：系统内置的可调用函数，执行具体动作并返回结构化结果。代码实现，变更需改代码。

| 工具名 | 功能 | 输入 | 返回 |
|---|---|---|---|
| `parse_document` | 解析上传文档 | `{file_path, file_type}` | `{text, structure, tables, page_count}` |
| `parse_project` | 解析项目文件夹 | `{path}` | `{tree, languages, dependencies, summary}` |
| `read_project_file` | 读取项目中某个文件 | `{path}` | `{content, language}` |
| `web_search` | 联网搜索 | `{query, max_results?, site?}` | `[{title, url, snippet}]` |
| `fetch_url` | 抓取指定网页 | `{url}` | `{title, content_markdown}` |
| `image_search` | 搜索配图 | `{query, count?}` | `[{url, description, source}]` |
| `generate_ppt_deck` | 从零生成整套 PPT 演示稿 | `{topic, num_slides?, theme?, title?, requirements?}` | `{presentation_id, title, theme_id, outline, slides, deckspec?, workflow?}` |
| `edit_slide` | 修改指定页 | `{index, current_html, instruction}` | `{html_new, version}` |
| `export_presentation` | 导出 | `{format, mode?}` | `{file_url, file_size}` |
| `load_skill` | 加载 Skill 内容 | `{name}` | `<skill>...body...</skill>` |
| `save_to_memory` | 写入用户长期记忆 | `{category, content}` | `{success, memory_id}` |
| `search_memory` | 搜索历史记忆 | `{query, top_k?}` | `[{content, relevance, timestamp}]` |

---

### 六、技能（Skill）体系

**定义**：领域知识/策略/最佳实践的 Markdown 文档，通过两层懒加载机制注入 Agent 上下文指导决策。可系统预置、用户自定义、画廊 Fork。

#### 6.1 Skill vs Tool 边界

| 维度 | Tool | Skill |
|---|---|---|
| 本质 | 可执行的函数 | 知识/策略文档（Markdown） |
| 返回值 | 结构化数据 | 自然语言指导，`<skill>` 标签包裹 |
| 状态 | 无状态，每次调用独立 | 加载后持续影响当前会话 Agent 行为 |
| 来源 | 系统内置，代码实现 | 系统预置 + 用户自定义上传 |
| 变更门槛 | 改代码重启 | 改 .md 文件即刻生效 |

#### 6.2 两层加载机制

**Layer 1（系统提示，始终可见，~100 token/skill）**：

```
Skills available (use load_skill to access full instructions):

  [System Skills]
  - requirement_clarification: 需求澄清追问策略 [clarification]
  - ppt_design_principles: PPT排版配色原则 [design, ppt]
  - chart_selection: 图表类型选择决策树 [chart, data]
  - storytelling: 叙事结构模板 [narrative, story]
  - academic_writing: 学术规范引用格式 [academic]
  - code_review_report: 代码评审报告模板 [code, review]

  [Your Custom Skills]
  - brand_guideline: 我司品牌视觉规范 [品牌, 设计]  (作用域: 手动启用)
  - investment_bank_style: 投行PPT风格 [金融, 极简]  (作用域: 手动启用)
```

**Layer 2（按需加载，通过 `load_skill` 工具注入完整内容）**：

Agent 判断需要或用户指令触发 → 调用 `load_skill("brand_guideline")` → 返回完整 Skill body → 以 `tool_result` 注入对话 → 后续生成受该 Skill 指导。

**查找优先级**：用户空间 `user_skills` 表 → 系统预置 `.skills/` 目录

#### 6.3 Skill 文件格式

```markdown
---
name: ppt_design_principles
description: PPT排版、配色、字体、留白设计原则
tags: design, ppt, layout, color
required_tools:                    # 可选：依赖哪些工具
---

# PPT 设计原则

## 排版
- 标题字号 28-36pt，正文 16-18pt
- 每页内容不超过 5 个要点
- 留白不少于 30%
...（完整指导内容）
```

#### 6.4 系统预置 Skill 清单

| Skill | 描述 | 加载场景 |
|---|---|---|
| `requirement_clarification` | 需求澄清追问策略 | 用户需求模糊时 |
| `ppt_design_principles` | 排版/配色/字体/留白原则 | 生成幻灯片时 |
| `chart_selection` | 数据→图表类型决策树 | 需要数据可视化时 |
| `storytelling` | 叙事结构模板（问题→方案→效果） | 构建 PPT 叙事线时 |
| `academic_writing` | 学术规范/引用格式/论证逻辑 | 学术报告/论文 PPT |
| `code_review_report` | 代码评审报告模板/关注维度 | 代码分析任务 |

#### 6.5 用户自定义 Skill

**资产空间操作**：
- `/assets` → Skill tab → `[+ 新建 Skill]`
- 编辑界面：左侧 Markdown 编辑器，右侧实时预览
- 也可直接上传 `.md` 文件

**数据模型**：

```sql
CREATE TABLE user_skills (
    id              UUID PRIMARY KEY,
    user_id         UUID NOT NULL,
    name            VARCHAR(63) NOT NULL,       -- 唯一标识
    display_name    VARCHAR(127),               -- 显示名称
    description     TEXT NOT NULL,              -- Layer1 摘要
    tags            TEXT,                       -- 逗号分隔
    body            TEXT NOT NULL,              -- Markdown 完整内容
    required_tools  TEXT,                       -- 依赖的工具
    status          VARCHAR(20) DEFAULT 'draft', -- draft | validated | published
    is_enabled      BOOLEAN DEFAULT FALSE,      -- 是否在当前用户默认启用
    is_public       BOOLEAN DEFAULT FALSE,      -- 是否公开到画廊
    scope           VARCHAR(20) DEFAULT 'manual', -- manual（手动启用）| auto（对所有任务自动生效）
    validation_result JSONB,                    -- 校验结果
    validated_at    TIMESTAMP,
    usage_count     INT DEFAULT 0,
    fork_count      INT DEFAULT 0,
    source_skill_id UUID,                       -- 若从画廊 Fork，记录来源
    gallery_version INT,                        -- 画廊发布版本号
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP,
    UNIQUE(user_id, name)
);
```

**校验测试流程**（一键校验按钮触发）：

| 步骤 | 校验内容 | 方式 |
|---|---|---|
| 1. 格式校验 | frontmatter 完整性、name 规范 `^[a-z][a-z0-9_]{2,62}$`、body 非空 ≥50 字符、tags ≤10 | 规则引擎 |
| 2. 安全校验 | 检测是否包含 API Key、密码、Token 等凭证信息（正则 + 模式匹配） | 自动检测 |
| 3. 内容校验 | 指导内容是否清晰可操作、是否自相矛盾、与已有 Skill 重叠度 | LLM 评估 |
| 4. 功能测试 | 自动构造测试场景 → Agent 加载该 Skill → 生成一页测试 PPT → 用户预览 | 模拟调用 |

校验通过 → `status='validated'`，可发布到画廊。

#### 6.6 Skill 作用域与冲突策略

**作用域**：

| 作用域 | 含义 | 适用场景 |
|---|---|---|
| `manual` | 仅当用户在对话中指令触发或 Agent 判断需要时才加载（默认） | 大多数 Skill |
| `auto` | 对该用户所有新任务自动生效，始终注入 Layer 1 菜单 | 品牌规范、个人写作风格等"始终应用"的 Skill |

用户在资产空间编辑 Skill 时可选择作用域。`auto` 类型的 Skill 上限 5 个（避免系统提示过度膨胀）。

**冲突策略**：

| 冲突类型 | 处理方式 |
|---|---|
| 用户 Skill 与系统 Skill 同名 | **用户优先**。系统 Skill 被遮蔽。UI 在资产管理页显示提示："⚠️ 此 Skill 覆盖了同名系统技能" |
| 多个用户 Skill 内容冲突（如两个品牌规范） | 同一任务中仅加载最先触发的一个。Agent 若检测到冲突会在对话中主动确认"你有两个品牌规范 Skill，使用哪一个？" |
| Fork 来的 Skill 与自己已有 Skill 同名 | Fork 时自动重命名为 `{原名}_forked`，用户可手动改名 |

#### 6.7 Agent 感知逻辑

- **启动时**：扫描系统 `.skills/` 目录 + 查询当前用户 `user_skills` 表（含 `auto` 作用域的 Skill）→ 合并生成 Layer 1 菜单注入系统提示
- **运行时**：Agent 根据任务需要自动调用 `load_skill`，或响应用户指令（"用我的品牌规范"）匹配 Skill 名称
- **统计**：每次 `load_skill` 调用 → `usage_count += 1`

---

### 七、记忆与上下文系统

#### 7.1 四层记忆架构

```
┌───────────┬──────────────┬──────────────┬───────────────────┐
│  Layer 0  │   Layer 1    │   Layer 2    │   Layer 3         │
│  工作记忆  │   会话记忆    │   用户记忆    │   知识记忆         │
│ (Context) │  (Session)   │  (User)      │  (Knowledge)      │
├───────────┼──────────────┼──────────────┼───────────────────┤
│ 当前LLM   │ 单任务全程    │ 跨任务持久    │ 外部知识库         │
│ 调用的     │ 含压缩摘要    │ 用户偏好/事实 │ 上传文档+搜索缓存  │
│ messages  │              │              │                   │
│           │              │              │                   │
│ 生命周期:  │ 生命周期:     │ 生命周期:     │ 生命周期:          │
│ 单次调用  │ 任务创建→归档  │ 永久(可清)   │ 手动管理           │
│           │              │              │                   │
│ 存储:     │ 存储:         │ 存储:        │ 存储:              │
│ 内存      │ DB messages  │ DB memories  │ DB chunks          │
│           │ + checkpoint │ + vector     │ + vector           │
└───────────┴──────────────┴──────────────┴───────────────────┘
```

#### 7.2 Layer 0 — 工作记忆（每次 LLM 调用的 context window）

**上下文组装顺序**：

```
System Prompt
├── 1. 角色定义 + 核心指令                        ~500 tokens
├── 2. 工具描述列表                               ~2,000 tokens
├── 3. Skill 菜单（Layer 1 摘要）                  ~300 tokens
├── 4. 用户画像（from Layer 2 检索）               ~200 tokens
├── 5. 相关长期记忆（from Layer 2 top-5）          ~500 tokens
├── 6. 当前任务上下文摘要                          ~300 tokens

Messages
├── 7. [若有] 历史摘要消息                         ~500 tokens
├── 8. 近期对话消息（保留完整）                     剩余空间
└── 9. 当前用户消息
```

**上下文压缩策略**：

| 阶段 | 触发条件 | 动作 |
|---|---|---|
| 微压缩 | 每次 LLM 调用前 | 旧 `tool_result` 截断至前 200 字符 + "...已截断" |
| 自动压缩 | 总 token > 窗口 70% | ① 触发记忆刷盘 ② LLM 摘要旧消息 → 替换为 `[summary]` 消息 ③ 标记旧消息 `is_compressed=true` |
| 手动压缩 | 用户 `/compact` 命令 | 同自动压缩，强制执行 |

**记忆刷盘**（参考 OpenClaw 的 pre-compaction flush）：
压缩前，系统注入提示让 Agent 主动调用 `save_to_memory` 保存重要信息到 Layer 2，避免压缩后丢失。

#### 7.3 Layer 1 — 会话记忆（单任务全程）

```sql
CREATE TABLE task_messages (
    id              UUID PRIMARY KEY,
    task_id         UUID NOT NULL,
    role            VARCHAR(20) NOT NULL,   -- user | assistant | system | tool
    content         TEXT,
    msg_type        VARCHAR(30),            -- text | thinking | plan | slide |
                                            -- clarification | summary | skill_load
    tool_name       VARCHAR(63),
    tool_input      JSONB,
    is_compressed   BOOLEAN DEFAULT FALSE,  -- 已被摘要替代
    token_count     INT,
    created_at      TIMESTAMP
);

CREATE TABLE task_checkpoints (
    id          UUID PRIMARY KEY,
    task_id     UUID NOT NULL,
    step_index  INT NOT NULL,
    state       JSONB NOT NULL,             -- Agent 状态快照
    summary     TEXT,
    created_at  TIMESTAMP,
    UNIQUE(task_id, step_index)
);
```

**检查点用途**：
- 回滚：用户点击"回到第 N 步" → 从 checkpoint 恢复 + 截断后续消息
- 恢复：页面刷新 → 加载最近 checkpoint + 重放最新消息
- 对应 MiniMax Agent 的"恢复检查点 / Edit & Regenerate"

**会话消息保留策略**：任务消息持久保留，不自动删除。用户可主动归档或删除任务（关联消息一并软删除）。

#### 7.4 Layer 2 — 用户记忆（跨任务持久）

```sql
CREATE TABLE user_memories (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL,
    category    VARCHAR(30) NOT NULL,   -- preference | fact | instruction | feedback
    content     TEXT NOT NULL,
    embedding   VECTOR(1536),           -- pgvector 语义嵌入
    source      VARCHAR(30),            -- auto_captured | user_explicit | agent_inferred
    source_task_id UUID,
    confidence  FLOAT DEFAULT 1.0,
    supersedes  UUID,                   -- 替代了哪条旧记忆
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);
```

**记忆分类**：

| 类别 | 示例 | 来源 |
|---|---|---|
| `preference` | "偏好深色科技风格PPT" | 自动捕获 / 用户明说 |
| `fact` | "公司是XX科技，职位产品经理" | 自动捕获 |
| `instruction` | "PPT 始终使用中文" | 用户明说 |
| `feedback` | "不喜欢渐变背景" | 从修改行为推断 |

**自动捕获**（异步后台，参考 Mem0 AutoCapture）：
每轮对话结束后 → 轻量模型提取值得记住的用户偏好/事实 → 新建/更新记忆 → 生成 embedding。

**记忆检索与注入**：
每次新对话或每 5 轮 → 用当前消息做向量相似搜索（top-5, threshold>0.3）→ 格式化注入系统提示 `<user_context>` 块。

**用户控制与默认策略**：

| 项目 | 策略 |
|---|---|
| **默认开关** | 长期记忆默认**开启**，仅自动捕获 `preference` 和 `instruction` 类；`fact` 类需用户在设置中手动开启（考虑隐私敏感度） |
| **可见性** | 所有自动捕获的记忆均在设置页可见，用户可随时查看 |
| **审核机制** | 自动捕获的记忆标注"🤖 AI 自动识别"标签，用户可一键确认或删除 |
| **可删除** | 支持单条删除、按类别批量删除、一键清空全部 |
| **可编辑** | 支持手动修改记忆内容（修改后 source 变为 `user_explicit`） |
| **可手动添加** | 设置页 `[+ 添加记忆]` 按钮，手动输入 |
| **可导出** | 支持导出为 JSON 文件（后续可用于迁移或备份） |
| **保留期限** | 用户记忆长期保留，不自动过期。用户可随时手动清除 |

**用户记忆管理界面**（`/settings` → 记忆管理）：

```
┌──────────────────────────────────────────────────────────┐
│  记忆管理                     [导出JSON]  [清空全部]       │
│                                                          │
│  记忆开关：                                               │
│  ☑ 自动记住我的偏好和指令                                  │
│  ☐ 自动记住关于我的事实信息（公司、职位等）                   │
│                                                          │
│  📌 偏好 (3条)                                            │
│  • 偏好深色科技风格PPT  🤖      [确认✓] [编辑] [删除]      │
│  • 图表偏好使用英文标注  🤖      [确认✓] [编辑] [删除]      │
│  • PPT始终使用中文      👤      [编辑] [删除]              │
│                                                          │
│  💬 指令 (1条)                                            │
│  • 引用来源放在脚注      🤖      [确认✓] [编辑] [删除]      │
│                                                          │
│  📋 事实 (0条) — 已关闭自动捕获                              │
│  • 暂无                                                   │
│                                                          │
│  [+ 手动添加记忆]                                          │
└──────────────────────────────────────────────────────────┘
```

#### 7.5 Layer 3 — 知识记忆（文档向量索引）

```sql
CREATE TABLE document_chunks (
    id          UUID PRIMARY KEY,
    asset_id    UUID NOT NULL,          -- 关联 assets 表
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    embedding   VECTOR(1536),
    metadata    JSONB,                  -- {page_num, heading, file_name}
    created_at  TIMESTAMP
);
```

- 用户上传文档 → 分块 → 生成嵌入 → 存入 `document_chunks`
- Agent 需要引用参考文档时按语义检索相关片段
- 搜索结果缓存：抓取过的 URL 内容分块存入，避免重复抓取

---

### 八、数据模型全景

```sql
-- 用户
CREATE TABLE users (
    id          UUID PRIMARY KEY,
    email       VARCHAR(255) UNIQUE,
    name        VARCHAR(127),
    avatar_url  VARCHAR(1024),
    settings    JSONB,                  -- 偏好设置（主题、默认模型、记忆开关等）
    created_at  TIMESTAMP
);

-- 任务（对话）
CREATE TABLE tasks (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL,
    title       VARCHAR(255),
    status      VARCHAR(20) DEFAULT 'active',  -- active | completed | archived
    intent      VARCHAR(30),                    -- ppt | research | code_analysis | chat
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

-- 消息
CREATE TABLE task_messages ( ... );          -- 见 7.3

-- 检查点
CREATE TABLE task_checkpoints ( ... );       -- 见 7.3

-- 资产
CREATE TABLE assets (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL,
    title       VARCHAR(255) NOT NULL,
    file_type   VARCHAR(30) NOT NULL,        -- document | ppt | code | image | audio | video | skill
    source      VARCHAR(30) NOT NULL,        -- upload | ai_generated | remix
    mime_type   VARCHAR(127),
    file_url    VARCHAR(1024),
    thumbnail_url VARCHAR(1024),
    file_size   BIGINT,
    task_id     UUID,                        -- 关联产生该资产的任务（可跳转回对话）
    parent_id   UUID,                        -- Fork 来源资产 ID
    metadata    JSONB,
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

-- 画廊
CREATE TABLE gallery_items (
    id          UUID PRIMARY KEY,
    asset_id    UUID NOT NULL,
    author_id   UUID NOT NULL,
    category    VARCHAR(30) NOT NULL,        -- ppt | research | code | skill | other
    title       VARCHAR(255),
    description TEXT,
    preview_url VARCHAR(1024),
    is_featured BOOLEAN DEFAULT FALSE,
    remix_count INT DEFAULT 0,
    view_count  INT DEFAULT 0,
    version     INT DEFAULT 1,               -- 画廊发布版本号（发布即冻结）
    license     VARCHAR(30) DEFAULT 'cc-by-4.0', -- 版权许可协议
    published_at TIMESTAMP
);

-- 用户 Skill
CREATE TABLE user_skills ( ... );            -- 见 6.5

-- 用户记忆
CREATE TABLE user_memories ( ... );          -- 见 7.4

-- 文档分块向量
CREATE TABLE document_chunks ( ... );        -- 见 7.5

-- PPT 数据
CREATE TABLE presentations (
    id          UUID PRIMARY KEY,
    task_id     UUID NOT NULL,
    title       VARCHAR(255),
    theme       JSONB NOT NULL,
    outline     JSONB,
    source_docs JSONB,                       -- 关联的参考文档 asset_id 列表
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP
);

CREATE TABLE slides (
    id              UUID PRIMARY KEY,
    presentation_id UUID NOT NULL,
    index           INT NOT NULL,
    type            VARCHAR(30),
    html            TEXT NOT NULL,
    speaker_notes   TEXT,
    version         INT DEFAULT 1,
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);

CREATE TABLE slide_versions (
    id          UUID PRIMARY KEY,
    slide_id    UUID NOT NULL,
    version     INT NOT NULL,
    html        TEXT NOT NULL,
    source      VARCHAR(20),                 -- wysiwyg | ai | fork
    created_at  TIMESTAMP
);
```

---

### 九、WebSocket 消息协议

#### 9.1 服务端 → 客户端

```typescript
type ServerMessage =
  // 对话类
  | { type: "message"; role: "assistant"; content: string }
  | { type: "thinking"; content: string }                  // 仅开发者模式下推送
  | { type: "status"; text: string }                       // 执行状态摘要（始终可见）
  | { type: "clarification"; question: string; options?: string[] }
  | { type: "intent_detected"; intent: "ppt"|"research"|"code_analysis"|"chat" }

  // 计划与进度类
  | { type: "plan"; items: Array<{ id: string; text: string; status: "pending"|"in_progress"|"completed" }> }
  | { type: "progress"; current: number; total: number; label: string }

  // PPT 类
  | { type: "outline"; slides: Array<{ title: string; bullets: string[]; type: string }> }
  | { type: "slide_ready"; index: number; html: string }
  | { type: "slide_updated"; index: number; html: string; version: number }

  // 文件与搜索类
  | { type: "file_parsed"; filename: string; summary: string; page_count?: number }
  | { type: "project_tree"; tree: string; languages: string[]; summary: string }
  | { type: "search_start"; query: string; source: "tavily"|"ddg"|"url" }
  | { type: "search_result"; results: Array<{ title: string; url: string; snippet: string }> }

  // Skill 与预览类
  | { type: "skill_loaded"; name: string }
  | { type: "preview_mode"; mode: "slides"|"code"|"document"|"none" }

  // 导出类
  | { type: "export_ready"; format: "html"|"pdf"|"pptx"; url: string; file_size: number }

  // 错误
  | { type: "error"; message: string; recoverable: boolean }
```

#### 9.2 客户端 → 服务端

```typescript
type ClientMessage =
  // 对话
  | { type: "chat"; content: string; selected_slide?: number }
  | { type: "mode"; value: "direct"|"discuss" }

  // 文件上传
  | { type: "upload"; files: FileRef[] }
  | { type: "upload_folder"; files: FileRef[] }
  | { type: "search_url"; url: string }

  // PPT 操作
  | { type: "outline_confirm"; outline: OutlineItem[]; action: "generate"|"edit" }
  | { type: "slide_edit"; index: number; html: string }    // WYSIWYG 保存
  | { type: "export"; format: "html"|"pdf"|"pptx"; mode?: "screenshot"|"editable" }

  // 画廊
  | { type: "publish_gallery"; asset_id: string; category: string; license: string }
```

---

### 十、非功能需求

| 维度 | 要求 |
|---|---|
| **响应速度** | 首 token 输出 < 2秒（通用对话），PPT 单页生成 < 15秒 |
| **并发** | 一阶段单用户，架构支持后续多用户扩展（用户隔离通过 `user_id` 前缀） |
| **数据安全** | 用户数据按 `user_id` 分目录存储，文件路径做 realpath 校验防穿越，URL 抓取做 SSRF 防护 |
| **可扩展性** | 新增 Tool 只加 handler 不改循环；新增 Skill 放 .md 文件或用户上传 |
| **容错** | Agent 执行出错时返回友好提示（`{type: "error", recoverable: true}`）而非崩溃；工具调用超时 30s 有回退策略 |
| **可观测性** | Agent 执行全过程可追踪（tool_use + 结果均持久化）；开发者模式下可查看 thinking 推理 |
| **国际化** | 一阶段中文优先，界面预留 i18n 结构（key-value 翻译文件） |

---

### 十一、一阶段范围与二阶段规划

#### 一阶段（当前实现）

| 模块 | 范围 |
|---|---|
| 对话 | 通用对话 + PPT 生成/修改（意图路由） |
| PPT | 完整流程：需求澄清→大纲→生成→预览→编辑→导出 |
| 文件上传 | PDF / Word / MD / PPT / Excel / 代码文件 / 文件夹（含安全约束） |
| 搜索 | web_search（支持 site 限制）+ read_url（含 SSRF 防护）+ search_image |
| Skill | 系统预置 6 个 + 用户自定义（含校验测试+作用域+冲突策略） |
| 记忆 | 四层架构完整实现（含用户可控开关、审核、管理界面） |
| 资产 | 上传文件管理 + AI 生成物 + Skill 管理 + 任务回跳 |
| 画廊 | 系统预置模板 + 用户发布（含版本冻结、版权声明、敏感信息检测）+ Fork |
| 导出 | HTML / PDF / PPTX 保真 / PPTX 可编辑（四选项，各附说明文案） |
| 过程展示 | 状态摘要+计划列表+进度条+实时预览（Thinking 仅开发者模式） |
| 编辑 | WYSIWYG（明确支持/不支持清单）+ 自然语言混合编辑 |
| 部署 | Docker Compose 本地自托管 |

#### 一阶段明确不做

| 模块 | 说明 |
|---|---|
| PPT 模板市场 | 不支持用户上传 PPTX 模板进行还原。仅内置 3-5 个主题（dark/light/corporate/academic/creative） |
| 多用户 SaaS 鉴权/计费 | 仅预留 `user_id` 字段和 RLS-ready 的数据模型，不实现认证/支付 |
| AI 图片生成 | 仅搜图（Pexels），不接入 FLUX/DALL-E |
| OCR | 图片/扫描 PDF 不做文字识别 |
| 协同编辑 | 单用户，不支持多人实时编辑 |
| MCP 集成 | 架构兼容但不实现 MCP Server/Client |
| 桌面端 | 无 Electron/Tauri 封装 |

#### 二阶段（后续扩展）

| 模块 | 内容 |
|---|---|
| AI 图片生成 | 接入 FLUX / DALL-E |
| OCR | 图片/扫描 PDF 文字识别 |
| 深度研究 Agent | 独立研究流程（多源搜索→反思→报告），带 Reflection Loop |
| 代码分析 Agent | 架构图生成、代码质量评估 |
| 定时任务 | Celery Beat + 自然语言 → cron |
| 专家系统 | 保存可复用 Agent 配置组合 |
| MCP 集成 | 能力抽象为 MCP Server |
| 协同编辑 | 多人实时编辑同一 PPT |
| 多用户 SaaS | Supabase Auth + 订阅计费 + RLS |
| 桌面端 | Electron / Tauri 封装 |
| 模板市场 | 用户上传自定义 PPT 模板 |
| browser-use | 深度页面交互/抓取 |

---
