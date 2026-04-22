# PresentationAgent 智能工作区平台
## 技术架构深度分析报告（完整版）

---

## 一、项目定位与愿景

### 1.1 项目概述

**PresentationAgent** 是一个基于 AI Agent 的智能工作区平台，旨在为用户提供从需求到产物的全链路智能服务。该平台通过统一的中间件链引擎驱动四大核心能力，让用户只需用自然语言描述需求，即可获得专业的演示文稿、流程图、Web 应用和技术文档。

在当今快节奏的工作环境中，制作高质量的技术演示文稿往往需要耗费大量时间和精力。PresentationAgent 的核心价值在于：**将复杂的 AI 能力封装为简单的用户交互**，让技术团队能够专注于内容本身，而非格式和排版。

### 1.2 核心特性矩阵

| 特性维度 | 具体描述 | 技术实现 |
|---------|---------|---------|
| **智能编排** | 自动解析用户意图，智能规划内容结构 | AgentFactory + MiddlewareChain |
| **多模态输出** | 一次生成，多种产物形态 | Web Deck + Draw.io + Web Sandbox + 文档 |
| **实时预览** | 所见即所得的编辑体验 | WebSocket + 双渲染引擎 |
| **增量编辑** | 支持页面级细粒度修改 | PageOrchestrator + edit_deck_page 工具 |
| **版本控制** | 完整的变更历史追溯 | DeckStateStore + 版本快照 |
| **多模型支持** | 灵活切换不同 LLM 提供商 | litellm 统一接口 |

### 1.3 目标用户画像

- **技术团队负责人**：需要快速制作技术架构分享演示
- **研发工程师**：需要生成代码评审、设计文档演示
- **产品经理**：需要制作产品路线图、功能演示
- **技术布道者**：需要进行技术分享、开源项目介绍

---

## 二、系统架构总览

### 2.1 整体架构设计

PresentationAgent 采用经典的**三层微服务架构**，各服务职责清晰，通过 Docker Compose 实现一键部署。整体架构遵循以下设计原则：

1. **松耦合**：服务间通过 WebSocket 和 REST API 通信，互不直接依赖
2. **高内聚**：每个服务内部高度内聚，职责单一明确
3. **可扩展**：各服务可根据负载独立扩展

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户交互层 (Next.js 14)                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        WorkspacePanel 工作区                         │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐ │   │
│  │  │  Web Deck  │  │   Draw.io  │  │Web Sandbox │  │  智能文档  │ │   │
│  │  │  演示文稿   │  │   流程图   │  │  Web 应用  │  │   Markdown │ │   │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              ↑ Zustand Store                               │
│                    ┌─────────┴─────────┐                                  │
│                    │    ChatPanel      │                                  │
│                    │   对话交互入口    │                                  │
│                    └─────────────────┘                                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ WebSocket (流式) + REST (控制)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Backend (FastAPI)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     AgentRuntime 主循环引擎                          │   │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐         │   │
│  │  │  AgentFactory │  │ MiddlewareChain │  │ chat_stream   │         │   │
│  │  │   动态构建器    │  │   14层中间件链   │  │   流式调用    │         │   │
│  │  └────────────────┘  └────────────────┘  └────────────────┘         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    WebDeckRuntime 编排系统                           │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────┐  │   │
│  │  │ Director│  │ Planner │  │Scheduler│  │Orchestr.│  │Reviewer│  │   │
│  │  │  总控   │  │  规划   │  │ Lane调度 │  │ 页面编排 │  │  质检  │  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  └────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        工具系统 (15个)                               │   │
│  │  edit_deck_page | dispatch_subagent | load_skill | run_code      │   │
│  │  web_search | fetch_url | image_search | parse_document           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│  LLM Provider       │   │  Native Renderer    │   │   Database          │
│  litellm            │   │  PptxGenJS           │   │   PostgreSQL        │
│  GPT-4/Claude       │   │  端口: 4100          │   │   会话持久化         │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

### 2.2 技术栈详解

#### 前端技术选型

| 技术 | 版本 | 用途说明 |
|------|------|---------|
| **Next.js** | 14 | React 框架，提供 App Router 和 SSR 能力 |
| **React** | 19 | UI 组件库，支持 hooks 和函数式编程 |
| **TypeScript** | 5.x | 类型安全，提高代码质量 |
| **Zustand** | 5.0 | 轻量级状态管理，替代 Redux |
| **Tailwind CSS** | 3.4 | 原子化 CSS，快速构建 UI |
| **Lucide React** | 最新 | 图标库，提供一致性图标风格 |

**状态管理设计**：平台采用双 Store 架构
- **deckStore**：管理 Web Deck 项目的所有状态，包括项目 ID、Manifest、页面列表、当前页索引、生成进度等
- **chatStore**：管理对话相关状态，包括消息历史、产物内容、处理状态、Token 计数等

#### 后端技术选型

| 技术 | 版本 | 用途说明 |
|------|------|---------|
| **FastAPI** | 0.104+ | 高性能异步 Web 框架 |
| **SQLAlchemy** | 2.0 | ORM 框架，支持异步操作 |
| **litellm** | 1.x | LLM 统一接口，封装多模型调用 |
| **WebSocket** | - | 实时通信，支持流式响应 |
| **Python** | 3.11+ | 后端开发语言 |

#### 部署架构

```yaml
services:
  backend:
    build: ./backend
    ports: ["8000:8000"]
    environment:
      - NATIVE_RENDERER_URL=http://native-renderer:4100
      - MODEL_CONTEXT_WINDOW=128000
      - DATABASE_URL=postgresql+asyncpg://...
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 1G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  native-renderer:
    build: ./native_renderer
    ports: ["4100:4100"]
    deploy:
      resources:
        limits:
          memory: 512M

  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on:
      backend:
        condition: service_healthy
```

---

## 三、Agent 运行时引擎（核心引擎）

### 3.1 AgentRuntime 主循环

AgentRuntime 是整个平台的"大脑"，负责协调用户请求、LLM 调用和工具执行的主循环。它的核心职责包括：

1. **接收用户消息**：通过 WebSocket 接收用户输入
2. **构建 Agent 上下文**：调用 AgentFactory 动态组装
3. **执行中间件链**：按顺序执行 14 层中间件
4. **流式调用 LLM**：支持实时响应的流式输出
5. **分发工具调用**：根据 LLM 响应调度对应工具
6. **管理对话状态**：维护消息历史和上下文

```python
class AgentRuntime:
    """
    Agent 运行时主循环引擎
    核心方法: run() - 异步主循环，处理单轮对话
    """
    
    async def run(
        self,
        task_id: str,
        user_id: str,
        user_message: str,
        session: AsyncSession,
        send_fn: Callable,
    ):
        # 1. 创建 Agent 上下文
        context, chain = await self.factory.create(...)
        
        # 2. 执行中间件链（前处理）
        await chain.execute_before(context, user_message)
        
        # 3. 流式调用 LLM
        async for chunk in chat_stream(context):
            # 4. 实时推送
            await send_fn({"type": "chunk", "content": chunk})
            
            # 5. 检测工具调用
            if chunk contains tool_call:
                # 6. 分发工具
                result = await dispatch(tool_call)
                # 7. 工具结果注入上下文
                context.messages.append(tool_result)
        
        # 8. 执行中间件链（后处理）
        await chain.execute_after(context)
```

### 3.2 AgentFactory 动态构建机制

AgentFactory 是"智能调度器"，根据用户意图动态组合不同的组件，实现"一个框架，多种场景"的灵活设计。

#### 动态组装流程

```
用户消息输入
     │
     ▼
意图检测 (Intent Detection)
     │
     ├──→ "ppt" 意图 ──→ 加载 PPT 中间件 + WebDeck 工具
     ├──→ "research" 意图 ──→ 加载研究工具集
     ├──→ "code_analysis" 意图 ──→ 加载代码分析工具
     ├──→ "webpage" 意图 ──→ 加载 Web Sandbox 工具
     ├──→ "drawio" 意图 ──→ 加载 Draw.io 工具
     └──→ "document" 意图 ──→ 加载文档工具
     │
     ▼
AgentFactory.create() 组装
     │
     ├──→ MiddlewareChain (中间件链)
     ├──→ ToolSet (工具集)
     ├──→ SystemPrompt (系统提示词)
     └──→ AgentContext (上下文对象)
     │
     ▼
返回 (AgentContext, MiddlewareChain)
```

#### 核心实现

```python
class AgentFactory:
    """动态 Agent 构建工厂"""
    
    def create(
        self,
        task: Task,
        user_message: str,
        session: AsyncSession,
        send_fn: Callable,
        model: str | None = None,
        intent_override: str | None = None,
    ) -> tuple[AgentContext, MiddlewareChain]:
        
        # Step 1: 检测意图
        intent = intent_override or self._detect_intent(user_message)
        
        # Step 2: 选择中间件链
        middlewares = self._select_middlewares(intent)
        
        # Step 3: 组装工具集
        tools = self._build_tools(intent)
        
        # Step 4: 定制系统提示词
        system_prompt = self._build_system_prompt(intent, task)
        
        # Step 5: 构建上下文
        context = AgentContext(
            task_id=task.id,
            user_id=task.user_id,
            user_message=user_message,
            intent=intent,
            system_prompt=system_prompt,
            messages=[],
            tools=tools,
            # ... 其他字段
        )
        
        # Step 6: 创建中间件链
        chain = MiddlewareChain(middlewares)
        
        return context, chain
```

### 3.3 14 层中间件链设计

中间件链是 Agent 运行时最具扩展性的设计。每个中间件职责单一，可以独立开发、测试和组合。这种设计借鉴了 Web 开发中的中间件模式，但针对 AI Agent 场景做了深度定制。

#### 中间件职责详解

| 层级 | 中间件名称 | 核心功能 | 详细说明 |
|------|-----------|---------|---------|
| 1 | **MemoryCaptureMiddleware** | 记忆检索注入 | 在每次请求前从长期记忆中检索相关信息，自动注入上下文 |
| 2 | **AttachmentInjectionMiddleware** | 附件解析注入 | 解析用户上传的文件（PDF/DOCX/PPTX），提取文本内容注入上下文 |
| 3 | **ToolErrorMiddleware** | 错误处理 | 捕获工具执行异常，进行分类处理（重试/降级/终止） |
| 4 | **IntentDetectionMiddleware** | 意图检测 | 分析用户消息，识别用户真实意图，决定后续处理流程 |
| 5 | **TokenBudgetMiddleware** | Token 预算监控 | 监控上下文 Token 使用量，超限时触发压缩或摘要 |
| 6 | **LoopDetectionMiddleware** | 循环检测 | 检测 Agent 是否陷入重复循环，防止死循环 |
| 7 | **CheckpointMiddleware** | 检查点保存 | 定期保存中间状态，支持中断恢复 |
| 8 | **SubagentOrchestrationMiddleware** | 子 Agent 编排 | 管理子 Agent 的创建、分发和结果收集 |
| 9 | **BriefEnrichmentMiddleware** | Brief 自动补充 | 当用户 Brief 不完整时，自动补充缺失信息 |
| 10 | **WebDeckContextMiddleware** | WebDeck 上下文注入 | 为 PPT 生成任务注入相关页面和样式上下文 |
| 11 | **PPTEventMiddleware** | PPT 专用事件 | 处理 PPT 特有的事件（如页面生成完成、样式更新等） |

#### 中间件执行模式

```python
class MiddlewareChain:
    """中间件链执行器"""
    
    def __init__(self, middlewares: list[BaseMiddleware]):
        self.middlewares = middlewares
    
    async def execute_before(self, context: AgentContext, user_message: str):
        """前处理：按顺序执行所有中间件的 before 方法"""
        for middleware in self.middlewares:
            await middleware.before(context, user_message)
    
    async def execute_after(self, context: AgentContext):
        """后处理：逆序执行所有中间件的 after 方法"""
        for middleware in reversed(self.middlewares):
            await middleware.after(context)
```

### 3.4 意图系统（Intent Detection）

意图系统是 Agent 的"智能路由"，能够准确识别用户需求并导向正确的处理流程。

#### 意图类型定义

| 意图类型 | 触发关键词示例 | 中间件扩展 | 工具集配置 |
|---------|--------------|-----------|-----------|
| **ppt** | PPT、演示、幻灯片、做演示 | +PPTEventMiddleware | edit_deck_page, dispatch_subagent, image_search |
| **research** | 研究、分析报告、市场调研 | 无 | web_search, fetch_url, parse_document |
| **code_analysis** | 代码审查、性能分析、Bug 定位 | 无 | parse_document, run_code |
| **webpage** | 网页、Web 应用、做个网站 | 无 | run_code |
| **drawio** | 流程图、架构图、UML、示意图 | 无 | edit_deck_page |
| **document** | 文档、技术文档、用户手册 | 无 | 基本工具 |
| **chat** | 闲聊、问候、问题咨询 | 无 | 基本工具 |
| **composite** | 复合任务（多意图组合） | +PPTEventMiddleware | 完整工具集 |

#### 意图检测算法

```python
class IntentDetector:
    """意图检测器"""
    
    INTENT_PATTERNS = {
        "ppt": ["ppt", "演示", "幻灯片", "做演示", "presentation", "deck"],
        "research": ["研究", "调研", "分析报告", "research", "survey"],
        "code_analysis": ["代码", "审查", "review", "bug", "性能"],
        "webpage": ["网页", "网站", "web", "html", "前端"],
        "drawio": ["流程图", "架构图", "uml", "diagram", "示意图"],
        "document": ["文档", "手册", "文档", "spec", "documentation"],
    }
    
    def detect(self, message: str) -> str:
        """基于关键词匹配和语义分析检测意图"""
        message_lower = message.lower()
        
        # 精确匹配
        for intent, keywords in self.INTENT_PATTERNS.items():
            if any(kw in message_lower for kw in keywords):
                return intent
        
        # 默认返回对话意图
        return "chat"
```

### 3.5 工具系统（Tool Dispatch）

工具系统是 Agent 的"执行四肢"，负责完成具体的操作任务。

#### 工具分类

**核心编排工具**（PPT 生成专用）

| 工具名称 | 功能描述 | 输入参数 | 输出结果 |
|---------|---------|---------|---------|
| `edit_deck_page` | 编辑 Web Deck 页面 | project_id, page_id, instruction | 更新后的页面 HTML |
| `dispatch_subagent` | 并发分派子 Agent | agents[], task | 并行执行结果汇总 |
| `load_skill` | 加载专业 Skill | skill_name | 加载的技能配置 |

**执行工具**

| 工具名称 | 功能描述 | 支持语言 |
|---------|---------|---------|
| `run_code` | 执行代码脚本 | Node.js, Python, Shell |

**信息工具**

| 工具名称 | 功能描述 | 数据源 |
|---------|---------|--------|
| `web_search` | 联网搜索 | 搜索引擎 API |
| `fetch_url` | 网页内容抓取 | 指定 URL |
| `parse_document` | 文档解析 | PDF, DOCX, PPTX, TXT, MD, CSV |

**资产工具**

| 工具名称 | 功能描述 | 用途 |
|---------|---------|-----|
| `image_search` | 免费图片搜索 | PPT 配图（Pexels API） |

**记忆工具**

| 工具名称 | 功能描述 | 存储位置 |
|---------|---------|---------|
| `save_to_memory` | 长期记忆保存 | 向量数据库 |
| `search_memory` | 长期记忆检索 | 向量数据库 |

#### 工具分发流程

```
LLM Response (tool_calls 字段)
         │
         ▼
filter_tools_by_intent() ─── 根据意图过滤可用工具
         │
         ▼
dispatch() ─── 路由到具体工具处理器
         │
    ┌────┴────┐
    │         │
    ▼         ▼
edit_deck   dispatch
_page()    _subagent()
    │         │
    │    ┌────┴────┐
    │    │         │
    │    ▼         ▼
    │  code_   web_
    │ analyst researcher
    │    │         │
    └────┴────┬────┘
              ▼
         结果聚合
              │
              ▼
    context.messages.append() ─── 结果注入上下文
```

---

## 四、智能工作区四大核心能力

### 4.1 Web Deck — 智能演示文稿

Web Deck 是 PresentationAgent 的核心能力，提供从 Brief 到专业演示文稿的完整链路。

#### 4.1.1 产品定位

Web Deck 解决的问题：
- **效率问题**：传统 PPT 制作耗时长，需要手动排版
- **质量问题**：非设计师制作的 PPT 往往缺乏专业感
- **协作问题**：多人协作时版本管理混乱

Web Deck 的核心价值：
- **AI 驱动**：用户只需描述需求，AI 自动生成专业演示
- **所见即所得**：实时预览，页面级细粒度编辑
- **版本可控**：完整的变更历史，随时回溯

#### 4.1.2 编排架构（Director-Planner-Scheduler）

Web Deck 的编排流程遵循经典的"总控-规划-执行-质检"模式：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          WebDeck 完整编排流程                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   用户 Brief 输入                                                            │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ topic: 演示主题                                                       │   │
│   │ audience: 目标受众                                                    │   │
│   │ goal: 演示目标                                                        │   │
│   │ page_count: 页数（可选）                                               │   │
│   │ style: 风格偏好（可选）                                                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         DeckDirector (总控)                          │   │
│   │  • 接收 brief，创建项目                                                │   │
│   │  • 管理整体流程状态                                                    │   │
│   │  • 协调各组件协作                                                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         DeckPlanner (规划器)                         │   │
│   │  • 调用 LLM 分析内容结构                                               │   │
│   │  • 生成 DeckManifest（页面列表、类型、核心信息）                         │   │
│   │  • 确定页面顺序和分组                                                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       LaneScheduler (车道调度器)                      │   │
│   │  • 将页面任务拆分为多个 Lane（叙事、图表、资产、布局、审稿）              │   │
│   │  • 多 Lane 并行执行，提高生成效率                                       │   │
│   │  • 管理 Lane 间依赖关系                                                │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│           ┌────────────────────────┼────────────────────────┐               │
│           ▼                        ▼                        ▼               │
│   ┌───────────────┐        ┌───────────────┐        ┌───────────────┐        │
│   │ narrative Lane│        │   chart Lane │        │   asset Lane  │        │
│   │   叙事车道    │        │   图表车道    │        │   资产车道    │        │
│   │ 生成页面文案   │        │ 生成图表代码  │        │ 搜索配图资源  │        │
│   └───────────────┘        └───────────────┘        └───────────────┘        │
│           │                        │                        │                │
│           └────────────────────────┼────────────────────────┘                │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                     PageOrchestrator (页面编排器)                     │   │
│   │  • 组合各 Lane 产物                                                    │   │
│   │  • 生成最终页面 HTML                                                   │   │
│   │  • 发起页级质量审核                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       DeckReviewer (质量审核)                         │   │
│   │  • 页级审核：内容完整性、格式规范性                                     │   │
│   │  • 整体审核：结构合理性、风格一致性                                     │   │
│   │  • 不合格时触发重生成                                                   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      Native Renderer (原生渲染)                       │   │
│   │  • HTML 语义分析                                                      │   │
│   │  • DeckSpec 规范转换                                                  │   │
│   │  • PptxGenJS 生成 PPTX                                               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 4.1.3 Lane 并行调度机制

Lane 是 Web Deck 编排的核心创新。它将页面生成任务拆分为多个独立子任务，通过并行执行大幅提升效率。

**Lane 类型定义**

| Lane 类型 | 职责 | 超时配置 | 并行度 |
|----------|------|---------|-------|
| `narrative` | 生成页面文案和结构 | 180s | 核心 Lane |
| `chart` | 生成图表代码（ECharts） | 150s | 高价值页面 |
| `diagram` | 生成架构图代码 | 150s | 高价值页面 |
| `asset` | 搜索和下载配图资源 | 90s | 可选 |
| `layout` | 组合最终布局 | 60s | 必须 |
| `review` | 质量审核 | - | 必须 |

**高价值页面识别**

```python
# 以下页面类型使用多 Lane 编排
HIGH_VALUE_PAGE_KINDS = {
    PageKind.SUMMARY,       # 总结页
    PageKind.ARCHITECTURE,  # 架构图页
    PageKind.CHART_ANALYSIS, # 图表分析页
    PageKind.ROADMAP,       # 路线图页
}
```

#### 4.1.4 状态机与生命周期

Web Deck 采用完整的状态机管理，支持从创建到完成的完整生命周期：

```typescript
// 状态枚举定义
enum DeckStatus {
  draft = "draft",           // 草稿状态
  planning = "planning",      // 规划中
  plan_ready = "plan_ready",  // 规划就绪（待用户确认）
  generating = "generating",   // 生成中
  reviewing = "reviewing",     // 审核中
  completed = "completed",   // 完成
  failed = "failed"           // 失败
}

// 页面状态枚举
enum PageStatus {
  pending = "pending",         // 等待生成
  in_progress = "in_progress",   // 生成中
  reviewing = "reviewing",       // 审核中
  completed = "completed",     // 完成
  failed = "failed"             // 失败
}
```

**状态流转图**

```
                    ┌─────────┐
         创建项目    │  draft  │
              └──────►│  草稿  │
                     └────┬────┘
                          │ Director.run()
                          ▼
                     ┌──────────┐
                     │ planning │
                     │  规划中  │
                     └────┬─────┘
                          │ Planner 生成 Manifest
                          ▼
                     ┌────────────┐
                     │ plan_ready │
                     │ 规划就绪   │ ◄─── 用户确认
                     └────┬───────┘
                          │ 用户确认
                          ▼
                     ┌───────────┐
                     │ generating │
                     │  生成中   │
                     └─────┬─────┘
                           │ 所有页面生成完成
                           ▼
                     ┌───────────┐
                     │ reviewing │
                     │  审核中   │
                     └─────┬─────┘
                           │ 审核通过
                           ▼
                     ┌───────────┐
                     │ completed │
                     │   完成    │
                     └───────────┘

         任何阶段失败 ──► failed
```

#### 4.1.5 双渲染引擎

双渲染引擎是 Web Deck 的核心技术亮点，实现"Web 预览 + PPTX 下载"的完美结合。

**渲染流程**

```
                    HTML 生成
                        │
                        ▼
            ┌───────────────────────┐
            │   语义分析器           │
            │   分析 HTML 布局类型   │
            │   (card/table/chart)   │
            └───────────┬───────────┘
                        │
                        ▼
            ┌───────────────────────┐
            │   DeckSpec 规范        │
            │   标准化中间表示        │
            │   {layout, elements}   │
            └───────────┬───────────┘
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
    ┌──────────────┐       ┌──────────────┐
    │   Web Deck   │       │     PPTX     │
    │   HTML/CSS   │       │  PptxGenJS   │
    │   实时预览    │       │   可下载文件  │
    └──────────────┘       └──────────────┘
```

**前端渲染组件**

```typescript
// DeckViewer - 主查看器
export function DeckViewer() {
  const { pages, currentPageIndex } = useDeckStore();
  
  return (
    <div className="viewer-container">
      <DeckPagePreview />      {/* 当前页预览 */}
      <DeckTocPanel />         {/* 目录导航 */}
      <DeckLanePanel />        {/* Lane 进度 */}
    </div>
  );
}

// DeckPagePreview - 页面预览
export function DeckPagePreview() {
  // 支持 HTML 渲染和 PPTX 下载
  // 1280x720 固定画布，JS 缩放适配视口
}
```

#### 4.1.6 页面类型定义

| 页面类型 | 用途 | Lane 配置 |
|---------|------|----------|
| `cover` | 封面页 | narrative + asset |
| `toc` | 目录页 | narrative |
| `content` | 普通内容页 | narrative |
| `architecture` | 架构图页 | narrative + diagram + layout |
| `chart_analysis` | 图表分析页 | narrative + chart + layout |
| `comparison` | 对比页 | narrative + layout |
| `timeline` | 时间线页 | narrative + layout |
| `summary` | 总结页 | narrative + asset |

### 4.2 Draw.io — 流程图与架构图

Draw.io 集成提供专业的图表编辑能力，让用户可以创建流程图、架构图、UML 图等。

#### 4.2.1 产品特性

- **在线编辑**：无需安装软件，浏览器直接编辑
- **丰富模板**：提供流程图、架构图、UML 等多种模板
- **实时保存**：自动保存机制，防止数据丢失
- **导出灵活**：支持 SVG、PNG、XML 等多种格式

#### 4.2.2 嵌入模式实现

Draw.io 通过 iframe 嵌入到工作区，实现无缝集成：

```typescript
export function DrawIoViewer({ embedded = false }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const { artifactContent, setArtifactContent } = useChatStore();
  
  // 获取 Draw.io 嵌入 URL
  const drawIoUrl = useMemo(() => getDrawIoEmbedUrl(), []);
  
  // 监听 iframe 消息
  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      const msg = parseDrawIoMessage(e.data);
      
      switch (msg.event) {
        case "init":
          // 编辑器初始化完成，加载内容
          iframeRef.current?.contentWindow?.postMessage({
            action: "load",
            xml: artifactContent || BLANK_XML
          }, "*");
          break;
          
        case "autosave":
        case "save":
          // 自动保存或用户保存
          setArtifactContent(msg.xml);
          break;
          
        case "exit":
          // 用户退出编辑器
          break;
      }
    };
    
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [artifactContent]);
  
  return (
    <iframe
      ref={iframeRef}
      src={drawIoUrl}
      className="drawio-iframe"
    />
  );
}
```

#### 4.2.3 消息协议详解

| 消息事件 | 方向 | 说明 | 典型 payload |
|---------|------|------|-------------|
| `configure` | Iframe → React | 编辑器配置请求 | `{config: {compressXml: false}}` |
| `init` | Iframe → React | 编辑器就绪 | `{}` |
| `autosave` | Iframe → React | 自动保存 | `{xml: "<mxfile>..."}` |
| `save` | Iframe → React | 手动保存 | `{xml: "<mxfile>..."}` |
| `exit` | Iframe → React | 用户退出 | `{}` |
| `load` | React → Iframe | 加载内容 | `{xml: "<mxfile>..."}` |
| `status` | React → Iframe | 状态反馈 | `{message: "loaded"}` |

### 4.3 Web Sandbox — Web 应用预览

Web Sandbox 提供即时的 Web 应用预览能力，支持 HTML/CSS/JavaScript 混合代码。

#### 4.3.1 产品特性

- **即时预览**：代码变更实时反映在预览中
- **安全沙箱**：隔离环境，防止恶意代码执行
- **多语言支持**：HTML、CSS、JavaScript 原生支持
- **响应式设计**：预览窗口自适应各种设备尺寸

#### 4.3.2 沙盒实现原理

```typescript
export function WebSandboxViewer() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [renderCounter, setRenderCounter] = useState(0);
  
  // 优先使用 htmlArtifactContent（跨复合任务保留）
  const htmlArtifactContent = useChatStore((s) => s.htmlArtifactContent);
  const artifactContent = useChatStore((s) => s.artifactContent);
  const content = htmlArtifactContent || artifactContent;
  
  // 代码变更时触发重新渲染
  useEffect(() => {
    setRenderCounter((c) => c + 1);
  }, [content]);
  
  return (
    <div className="sandbox-container">
      {/* 浏览器 Chrome 模拟 */}
      <div className="browser-chrome">
        <div className="traffic-lights">
          <span className="red" />
          <span className="yellow" />
          <span className="green" />
        </div>
        <div className="address-bar">localhost:3000 / Web 沙盒预览</div>
        <button onClick={() => setRenderCounter(c => c + 1)}>
          刷新
        </button>
      </div>
      
      {/* 沙箱 iframe */}
      <iframe
        key={renderCounter}  // key 变化强制完全重新加载
        ref={iframeRef}
        srcDoc={content}    // 直接注入 HTML 内容
        sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
        title="Web Sandbox Preview"
      />
    </div>
  );
}
```

#### 4.3.3 渲染流程

```
用户描述需求（如"做一个 Todo 应用"）
           │
           ▼
    Agent 生成代码
    <general-artifact type="webpage">
      <!DOCTYPE html>
      <html>
        <head>
          <style>...</style>
        </head>
        <body>
          <script>...</script>
        </body>
      </html>