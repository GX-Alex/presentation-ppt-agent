# SubAgent 机制 + 执行过程 UI 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 General Agent 引入 SubAgent 并发调度机制，支持复合任务/项目分析/多材料/深度研究四个场景，并优化前端步骤卡片流 UI。

**Architecture:** Tool-based dispatch (`dispatch_subagent`) + Middleware 自动编排 (`SubagentOrchestrationMiddleware`)。每个 SubAgent 是独立 AgentContext + 完整 MiddlewareChain + 独立 DB session。前端用 ExecutionTimeline 替换 ReasoningBubble。

**Tech Stack:** Python 3.13 / FastAPI / asyncio / LiteLLM / React 18 / Zustand / Tailwind CSS

**Design Doc:** `docs/plans/2026-04-10-subagent-design.md`

---

## Task 1: SubAgent 数据模型与 Prompts

**Files:**
- Create: `backend/app/core/subagent.py`

**Step 1: 创建 subagent.py — 数据模型 + 5 个角色 prompt + 配置**

```python
# backend/app/core/subagent.py
"""SubAgent 子任务系统 — 数据模型、角色定义、Prompt 模板。"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any

# ── 数据模型 ─────────────────────────────────────────────

@dataclass
class SubAgentSpec:
    agent_type: str            # code_analyst | researcher | diagram | writer | ppt
    task_description: str
    tools: list[str] = field(default_factory=list)
    max_rounds: int = 8
    context: dict[str, Any] = field(default_factory=dict)
    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

@dataclass
class SubAgentResult:
    agent_type: str
    agent_id: str
    status: str                # completed | failed | timeout
    content: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(default_factory=dict)
    rounds_used: int = 0
    duration_ms: int = 0

# ── 角色配置 ─────────────────────────────────────────────

SUBAGENT_TIMEOUT_SECONDS = 120

SUBAGENT_ROLES: dict[str, dict[str, Any]] = {
    "code_analyst": {
        "max_rounds": 10,
        "tools": ["parse_project", "read_project_file"],
        "system_prompt": (
            "<role>你是代码架构分析专家 (Code Analyst Agent)。</role>\n"
            "<task>深入阅读用户提供的源码项目，产出结构化的 Markdown 分析报告。</task>\n"
            "<output_format>\n"
            "输出一份 Markdown 报告，包含：\n"
            "1. 项目概述（一句话）\n"
            "2. 核心技术栈表格\n"
            "3. 模块架构（ASCII 图）\n"
            "4. 核心文件功能表\n"
            "5. API 接口表\n"
            "6. 数据流说明\n"
            "</output_format>"
        ),
    },
    "researcher": {
        "max_rounds": 8,
        "tools": ["web_search", "fetch_url", "parse_document"],
        "system_prompt": (
            "<role>你是深度研究员 (Researcher Agent)。</role>\n"
            "<task>围绕用户给定的主题进行多角度搜索，交叉验证信息，产出结构化研究摘要。</task>\n"
            "<output_format>\n"
            "输出一份 Markdown 研究报告，包含：\n"
            "1. 研究主题\n"
            "2. 关键发现（3-5 条）\n"
            "3. 信息源列表\n"
            "4. 综合分析\n"
            "</output_format>"
        ),
    },
    "diagram": {
        "max_rounds": 3,
        "tools": [],
        "system_prompt": (
            "<role>你是架构图专家 (Diagram Agent)。</role>\n"
            "<task>基于提供的分析报告，生成 draw.io 兼容的 XML 架构图。</task>\n"
            "<output_format>\n"
            "直接输出完整的 draw.io XML（以 <mxfile> 开头），不要加 markdown 代码块包裹。\n"
            "要求：\n"
            "- 清晰体现模块层级和调用关系\n"
            "- 使用不同颜色区分层级\n"
            "- 用带箭头的连线表示数据流向\n"
            "</output_format>"
        ),
    },
    "writer": {
        "max_rounds": 3,
        "tools": [],
        "system_prompt": (
            "<role>你是技术写作专家 (Writer Agent)。</role>\n"
            "<task>综合多份子报告（分析报告、研究报告、图表），产出统一的最终文档。</task>\n"
            "<output_format>\n"
            "输出一份 Markdown 综合文档，结构清晰，语言简洁。\n"
            "将多份输入材料有机融合，不是简单拼接。\n"
            "</output_format>"
        ),
    },
    "ppt": {
        "max_rounds": 1,
        "tools": [],
        "system_prompt": "",  # PPT 走 WebDeck pipeline，此处仅占位
    },
}

MAX_RESULT_CHARS = 2000  # 子 agent 结果回传给 Lead 时的截断长度
```

**Step 2: 验证模块可导入**

Run: `cd /Users/guoguo/quantlearn/generalagent/backend && python -c "from app.core.subagent import SubAgentSpec, SubAgentResult, SUBAGENT_ROLES; print(f'OK: {len(SUBAGENT_ROLES)} roles')"`
Expected: `OK: 5 roles`

---

## Task 2: SubAgentRunner

**Files:**
- Modify: `backend/app/core/subagent.py` (append)
- Modify: `backend/app/core/agent_factory.py` (add create_subagent method)

**Step 1: 在 agent_factory.py 中添加 create_subagent 方法**

在 `AgentFactory` 类末尾（`_create_middleware` 方法之后）追加：

```python
def create_subagent(
    self,
    *,
    spec: "SubAgentSpec",
    parent_task: "Task",
    send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    model: str | None = None,
) -> tuple["AgentContext", "MiddlewareChain"]:
    """为子 agent 构建独立的 context + chain。"""
    from app.core.subagent import SUBAGENT_ROLES

    role_cfg = SUBAGENT_ROLES.get(spec.agent_type, {})
    user_id = parent_task.user_id or DEFAULT_USER_ID

    # 构建注入上下文的用户消息
    injected_context = ""
    if spec.context:
        injected_context = f"\n\n<context>\n{json.dumps(spec.context, ensure_ascii=False)[:4000]}\n</context>"

    user_message = spec.task_description + injected_context

    ctx = AgentContext(
        task_id=parent_task.id,
        user_id=user_id,
        user_message=user_message,
        model=model,
        intent=spec.agent_type,
        max_rounds=spec.max_rounds or role_cfg.get("max_rounds", 8),
        session=None,  # 子 agent 自己开 session
        send_fn=send_fn,
    )
    ctx.system_prompt = role_cfg.get("system_prompt", "")

    chain = self._build_chain(None)  # 子 agent 用基础 chain（无 intent extra）
    return ctx, chain
```

需要在文件顶部添加 `import json`。

**Step 2: 在 subagent.py 中添加 run_subagent 函数**

在 `subagent.py` 末尾追加：

```python
import asyncio
import logging
import time
from typing import Callable, Awaitable

from app.db import async_session
from app.core.tool_dispatch import dispatch, get_tool_definitions, filter_tools_by_intent

logger = logging.getLogger(__name__)


async def run_subagent(
    spec: SubAgentSpec,
    parent_task,
    send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    model: str | None = None,
) -> SubAgentResult:
    """运行单个子 agent，返回结果。使用独立 DB session。"""
    from app.core.agent_factory import AgentFactory
    from app.core.agent_runner import AgentRunner

    factory = AgentFactory()
    t0 = time.monotonic()
    agent_id = spec.agent_id

    # ── 发送 subagent_start 事件 ──
    await send_fn({
        "type": "subagent_start",
        "agent_id": agent_id,
        "agent_type": spec.agent_type,
        "task": spec.task_description[:200],
    })

    try:
        async with async_session() as session:
            # 构建子 agent 的 send_fn（转发进度事件）
            async def sub_send_fn(msg: dict[str, Any]) -> None:
                msg_type = msg.get("type", "")
                if msg_type == "status":
                    await send_fn({
                        "type": "subagent_progress",
                        "agent_id": agent_id,
                        "agent_type": spec.agent_type,
                        "detail": msg.get("text", ""),
                    })
                elif msg_type == "content_delta":
                    await send_fn({
                        "type": "subagent_content_delta",
                        "agent_id": agent_id,
                        "content": msg.get("content", ""),
                    })
                elif msg_type in ("stream_start", "stream_end", "thinking"):
                    await send_fn({
                        "type": "subagent_progress",
                        "agent_id": agent_id,
                        "agent_type": spec.agent_type,
                        "detail": msg_type,
                    })

            ctx, chain = factory.create_subagent(
                spec=spec,
                parent_task=parent_task,
                send_fn=sub_send_fn,
                model=model,
            )
            ctx.session = session

            # 过滤工具集
            if spec.tools:
                all_tools = get_tool_definitions()
                ctx.tools = [t for t in all_tools if t["function"]["name"] in spec.tools]
            else:
                ctx.tools = []

            # 注入用户消息到 ctx.messages
            ctx.messages = [{"role": "user", "content": ctx.user_message}]

            # 运行子 agent 主循环（简化版：直接调用 _main_loop 逻辑）
            runner = AgentRunner(ctx, chain)
            await asyncio.wait_for(
                runner._run_subagent_loop(ctx, chain),
                timeout=SUBAGENT_TIMEOUT_SECONDS,
            )

            # 提取最终内容
            content = ""
            for msg in reversed(ctx.messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    content = msg["content"]
                    break

            duration_ms = int((time.monotonic() - t0) * 1000)
            result = SubAgentResult(
                agent_type=spec.agent_type,
                agent_id=agent_id,
                status="completed",
                content=content[:MAX_RESULT_CHARS],
                token_usage=ctx.get_meta("token_usage") or {},
                rounds_used=ctx.round_count,
                duration_ms=duration_ms,
            )

    except asyncio.TimeoutError:
        duration_ms = int((time.monotonic() - t0) * 1000)
        result = SubAgentResult(
            agent_type=spec.agent_type,
            agent_id=agent_id,
            status="timeout",
            content=f"子 agent {spec.agent_type} 执行超时 ({SUBAGENT_TIMEOUT_SECONDS}s)",
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.monotonic() - t0) * 1000)
        logger.exception(f"[SubAgent] {spec.agent_type} failed: {e}")
        result = SubAgentResult(
            agent_type=spec.agent_type,
            agent_id=agent_id,
            status="failed",
            content=f"子 agent {spec.agent_type} 执行失败: {e}",
            duration_ms=duration_ms,
        )

    # ── 发送 subagent_complete 事件 ──
    await send_fn({
        "type": "subagent_complete",
        "agent_id": agent_id,
        "agent_type": spec.agent_type,
        "status": result.status,
        "summary": result.content[:300],
        "duration_ms": result.duration_ms,
        "rounds_used": result.rounds_used,
    })

    return result
```

**Step 3: 在 AgentRunner 中添加 _run_subagent_loop 方法**

在 `agent_runner.py` 的 `AgentRunner` 类中添加一个精简版主循环供子 agent 使用（不持久化消息到 DB，不做 context 压缩）：

```python
async def _run_subagent_loop(self, ctx: AgentContext, chain: MiddlewareChain) -> None:
    """子 agent 精简主循环 — 不持久化消息，不压缩上下文。"""
    from app.core.llm_client import chat_stream
    from app.core.tool_dispatch import dispatch

    await chain.run_request_start(ctx)
    if ctx.should_stop:
        return

    while ctx.round_count < ctx.max_rounds:
        ctx.round_count += 1

        await chain.run_before_llm(ctx)
        if ctx.should_stop:
            return

        # LLM 调用
        response = await self._call_llm_streaming(ctx, chain, None, ctx.tools)
        if response is None:
            return

        if response.stop_reason == "end_turn":
            # 追加最终内容到 messages
            if response.content:
                ctx.messages.append({"role": "assistant", "content": response.content})
            await chain.run_round_end(ctx)
            return

        if response.stop_reason == "tool_use":
            # 处理工具调用（不持久化）
            if response.content:
                ctx.messages.append({"role": "assistant", "content": response.content})

            tool_calls_msg = {
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.input, ensure_ascii=False)}}
                    for tc in response.tool_calls
                ],
            }
            ctx.messages.append(tool_calls_msg)

            for tc in response.tool_calls:
                params = tc.input
                intercepted = await chain.run_tool_start(ctx, tc.name, params)
                if intercepted is None:
                    tool_result = {"error": "blocked by middleware"}
                else:
                    params = intercepted
                    try:
                        tool_result = await dispatch(tc.name, params, session=ctx.session, user_id=ctx.user_id)
                    except Exception as e:
                        tool_result = {"error": str(e)}

                await chain.run_tool_end(ctx, tc.name, params, tool_result)
                ctx.messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:MAX_SUBAGENT_TOOL_RESULT],
                })

            await chain.run_round_end(ctx)

    await chain.run_request_end(ctx)
```

需要在 `agent_runner.py` 顶部添加 `MAX_SUBAGENT_TOOL_RESULT = 1500`。

---

## Task 3: dispatch_subagent 工具

**Files:**
- Create: `backend/app/tools/dispatch_subagent.py`
- Modify: `backend/app/core/tool_dispatch.py` (添加 category)

**Step 1: 创建 dispatch_subagent.py**

```python
# backend/app/tools/dispatch_subagent.py
"""dispatch_subagent — 派发子任务给专职 Agent 并发执行。"""
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "dispatch_subagent",
        "description": (
            "派发子任务给专职 Agent 并发执行。可同时派发多个子 agent。"
            "可用角色: code_analyst(代码分析), researcher(深度研究), "
            "diagram(架构图生成), writer(综合写作)。"
            "每个子 agent 独立运行，完成后将结果汇总返回。"
        ),
        "parameters": {
            "type": "object",
            "required": ["agents"],
            "properties": {
                "agents": {
                    "type": "array",
                    "description": "要派发的子 agent 列表",
                    "items": {
                        "type": "object",
                        "required": ["agent_type", "task"],
                        "properties": {
                            "agent_type": {
                                "type": "string",
                                "enum": ["code_analyst", "researcher", "diagram", "writer"],
                                "description": "子 agent 角色类型",
                            },
                            "task": {
                                "type": "string",
                                "description": "分配给子 agent 的具体任务描述",
                            },
                            "context": {
                                "type": "object",
                                "description": "传递给子 agent 的上下文（如先前分析结果）",
                            },
                        },
                    },
                },
            },
        },
    },
}

# 运行时注入的引用（由 execute 中动态获取）
_current_send_fn = None
_current_task = None
_current_model = None


def set_runtime_context(send_fn, task, model=None):
    """在 tool dispatch 前设置运行时上下文。"""
    global _current_send_fn, _current_task, _current_model
    _current_send_fn = send_fn
    _current_task = task
    _current_model = model


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """并发执行多个子 agent。"""
    from app.core.subagent import SubAgentSpec, run_subagent, SUBAGENT_ROLES

    agents_specs = params.get("agents", [])
    if not agents_specs:
        return {"error": "agents 列表为空"}

    send_fn = _current_send_fn
    task = _current_task
    model = _current_model

    if not send_fn or not task:
        return {"error": "dispatch_subagent 缺少运行时上下文，请重试"}

    # 构建 SubAgentSpec 列表
    specs: list[SubAgentSpec] = []
    for agent_def in agents_specs:
        agent_type = agent_def.get("agent_type", "")
        if agent_type not in SUBAGENT_ROLES:
            continue
        role_cfg = SUBAGENT_ROLES[agent_type]
        specs.append(SubAgentSpec(
            agent_type=agent_type,
            task_description=agent_def.get("task", ""),
            tools=role_cfg.get("tools", []),
            max_rounds=role_cfg.get("max_rounds", 8),
            context=agent_def.get("context") or {},
        ))

    if not specs:
        return {"error": "没有有效的子 agent 配置"}

    logger.info(f"[dispatch_subagent] 派发 {len(specs)} 个子 agent: {[s.agent_type for s in specs]}")

    # 并发执行
    tasks = [run_subagent(spec, task, send_fn, model) for spec in specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 汇总结果
    output: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            output.append({
                "agent_type": specs[i].agent_type,
                "status": "failed",
                "content": str(r),
            })
        else:
            output.append({
                "agent_type": r.agent_type,
                "agent_id": r.agent_id,
                "status": r.status,
                "content": r.content,
                "rounds_used": r.rounds_used,
                "duration_ms": r.duration_ms,
            })

    return {"subagent_results": output}
```

**Step 2: 在 tool_dispatch.py 中注册 category**

在 `TOOL_CATEGORIES` dict 中添加：
```python
"dispatch_subagent": [ToolCategory.UNIVERSAL],
```

---

## Task 4: SubagentOrchestrationMiddleware

**Files:**
- Modify: `backend/app/core/agent_middlewares.py` (追加新 middleware)
- Modify: `backend/app/core/agent_factory.py` (注册到 _INTENT_EXTRA 和 _create_middleware)

**Step 1: 在 agent_middlewares.py 底部追加**

```python
class SubagentOrchestrationMiddleware(AgentMiddleware):
    """对 composite/research intent 自动规划子 agent 方案，注入 system prompt。"""

    _COMPOSITE_PLAN_TEMPLATE = (
        "\n<subagent_capability>\n"
        "你可以使用 dispatch_subagent 工具将任务分配给专职子 Agent 并发执行。\n"
        "可用子 Agent 角色:\n"
        "- code_analyst: 代码架构深度分析\n"
        "- researcher: 多角度网络搜索与研究\n"
        "- diagram: 基于分析报告生成 draw.io 架构图\n"
        "- writer: 综合多份子报告产出最终文档\n\n"
        "建议策略: 先派发 code_analyst 和/或 researcher 收集信息，"
        "再将结果传给 diagram/writer 生成最终产出。\n"
        "一次 dispatch_subagent 调用可并发多个子 agent。\n"
        "</subagent_capability>"
    )

    async def on_before_llm(self, ctx: AgentContext) -> None:
        if ctx.intent not in ("composite", "research", None):
            return
        # 仅首轮注入
        if ctx.round_count > 1:
            return
        # 检查消息是否包含复合关键词
        msg = ctx.user_message.lower()
        composite_keywords = ["分析", "研究", "搜索", "架构图", "流程图", "演示文稿", "ppt", "报告"]
        if not any(kw in msg for kw in composite_keywords):
            return
        ctx.system_prompt += self._COMPOSITE_PLAN_TEMPLATE
```

**Step 2: 在 agent_factory.py 中注册**

在 `_BASE_MIDDLEWARES` 列表中在 `"brief_enrichment"` 之前添加 `"subagent_orchestration"`。

在 `_create_middleware` 方法的 factory dict 中添加：
```python
"subagent_orchestration": lambda: SubagentOrchestrationMiddleware()
```

需要在 import 区域添加 `SubagentOrchestrationMiddleware`。

---

## Task 5: AgentRunner 集成 — 在 tool dispatch 前注入运行时上下文

**Files:**
- Modify: `backend/app/core/agent_runner.py` (_handle_tool_use 方法)

**Step 1: 在 _handle_tool_use 中，dispatch 调用前注入 context**

在 `_handle_tool_use` 方法中，tool 循环内（`dispatch()` 调用之前），添加：

```python
# 为 dispatch_subagent 注入运行时上下文
if tc.name == "dispatch_subagent":
    from app.tools.dispatch_subagent import set_runtime_context
    set_runtime_context(ctx.send_fn, task, ctx.model)
```

---

## Task 6: 前端 — chatStore 类型扩展

**Files:**
- Modify: `frontend/src/stores/chatStore.ts`

**Step 1: 添加 ExecutionStep 和 SubAgentState 类型**

在 `ChatMessage` 接口之后添加：

```typescript
// ── SubAgent 执行状态 ──────────────────────────────────
export type StepStatus = "pending" | "running" | "completed" | "failed";

export interface ExecutionStep {
  id: string;
  type: "thinking" | "tool_call" | "subagent_dispatch" | "content" | "status";
  status: StepStatus;
  title: string;
  content?: string;
  toolName?: string;
  startTime?: number;
  duration?: number;
  subAgents?: SubAgentState[];
}

export interface SubAgentState {
  agentId: string;
  agentType: string;
  task: string;
  status: StepStatus;
  currentRound: number;
  maxRounds: number;
  steps: ExecutionStep[];
  result?: string;
  duration?: number;
}
```

**Step 2: 在 store 的 state 中添加 executionSteps**

在 store 的 state interface 中添加：
```typescript
executionSteps: ExecutionStep[];
```

添加 actions：
```typescript
addExecutionStep: (step: ExecutionStep) => void;
updateExecutionStep: (id: string, updates: Partial<ExecutionStep>) => void;
clearExecutionSteps: () => void;
addSubAgentToStep: (stepId: string, subAgent: SubAgentState) => void;
updateSubAgent: (agentId: string, updates: Partial<SubAgentState>) => void;
```

---

## Task 7: 前端 — ExecutionTimeline 组件

**Files:**
- Create: `frontend/src/components/chat/ExecutionTimeline.tsx`
- Modify: `frontend/src/components/chat/MessageList.tsx` (替换 ReasoningBubble 调用)

**Step 1: 创建 ExecutionTimeline.tsx**

包含 `ExecutionTimeline`、`StepCard`、`SubAgentCard` 三个组件。

**Step 2: 修改 MessageList.tsx**

在 `renderItems` 的 `"reasoning"` 分支中，将 `<ReasoningBubble>` 替换为 `<ExecutionTimeline>`，同时保留 `ReasoningBubble` 作为 fallback（当 executionSteps 为空时使用）。

---

## Task 8: 前端 — WS handler 处理 subagent 事件

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`

**Step 1: 添加 subagent 事件处理 case**

在 `_handleMessage` switch 中添加：

```typescript
case "subagent_start":
  store.addSubAgentToStep(currentStepId, {
    agentId: data.agent_id,
    agentType: data.agent_type,
    task: data.task || "",
    status: "running",
    currentRound: 0,
    maxRounds: 10,
    steps: [],
  });
  break;

case "subagent_progress":
  store.updateSubAgent(data.agent_id, {
    currentRound: data.round || 0,
    steps: [...(existingSteps), {
      id: `${data.agent_id}-${Date.now()}`,
      type: "status",
      status: "completed",
      title: data.detail || "",
    }],
  });
  break;

case "subagent_content_delta":
  store.updateSubAgent(data.agent_id, {
    result: (existingResult || "") + (data.content || ""),
  });
  break;

case "subagent_complete":
  store.updateSubAgent(data.agent_id, {
    status: data.status === "completed" ? "completed" : "failed",
    duration: data.duration_ms,
    result: data.summary || "",
  });
  break;
```

---

## Task 9: 验证与集成测试

**Step 1: 后端语法验证**

```bash
cd /Users/guoguo/quantlearn/generalagent/backend
python -c "
from app.core.subagent import SubAgentSpec, SubAgentResult, SUBAGENT_ROLES, run_subagent
from app.tools.dispatch_subagent import TOOL_DEFINITION, execute
from app.core.agent_factory import AgentFactory
from app.core.agent_runner import AgentRunner
print('All imports OK')
"
```

**Step 2: 前端构建验证**

```bash
cd /Users/guoguo/quantlearn/generalagent/frontend && npm run build
```

**Step 3: 重启后端并进行 E2E 测试**

使用 Playwright 测试复合指令（分析 + 架构图 + PPT）是否正确触发 dispatch_subagent。
