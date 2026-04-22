# SubAgent 机制 + 执行过程 UI 设计方案

**日期**: 2026-04-10
**状态**: Approved

---

## 1. 目标

为 General Agent 引入 SubAgent 并发调度机制，覆盖四个场景：
- **复合任务**：分析 + 画图 + 生成 PPT 一条消息完成
- **项目分析**：大型 codebase 深度分析（避免上下文溢出）
- **多材料分析**：多文档/多附件并行分析汇总
- **深度 research**：多搜索方向并发 + 交叉验证

同时优化前端执行过程 UI，采用步骤卡片流显示。

---

## 2. SubAgent 核心机制

### 2.1 数据结构

```python
@dataclass
class SubAgentSpec:
    agent_type: str          # "code_analyst" | "researcher" | "diagram" | "writer" | "ppt"
    task_description: str    # Lead Agent 给子 agent 的任务描述
    tools: list[str]         # 允许使用的工具子集
    max_rounds: int = 8      # 子 agent 最大轮次
    context: dict = None     # 注入的额外上下文

@dataclass
class SubAgentResult:
    agent_type: str
    agent_id: str
    status: str              # "completed" | "failed" | "timeout"
    content: str             # 子 agent 产出
    artifacts: list[dict]    # 生成的附件
    token_usage: dict
    rounds_used: int
    duration_ms: int
```

### 2.2 SubAgentRunner

- 复用 `AgentFactory.create()` 构建独立 `AgentContext` + 完整 `MiddlewareChain`
- 独立 DB session（`async with async_session()`），不共享父 session
- 独立消息历史、独立 token 计数
- 专职 system prompt（按 agent_type 选择）
- 工具集通过白名单过滤
- 结果回传到 Lead Agent 的 tool_result

### 2.3 五个 SubAgent 角色

| Agent | 工具白名单 | max_rounds | 输出 |
|-------|-----------|------------|------|
| `code_analyst` | `parse_project`, `read_project_file` | 10 | Markdown 分析报告 |
| `researcher` | `web_search`, `fetch_url`, `parse_document` | 8 | Markdown 研究报告 |
| `diagram` | 无（纯生成） | 3 | draw.io XML |
| `writer` | 无（纯生成） | 3 | Markdown 综合文档 |
| `ppt` | 桥接 WebDeck pipeline | N/A | WebDeck HTML |

---

## 3. 调度机制

### 3.1 Tool 层：`dispatch_subagent`

注册为标准工具，Lead Agent 主动调用：

```python
TOOL_DEFINITION = {
    "name": "dispatch_subagent",
    "parameters": {
        "properties": {
            "agents": {
                "type": "array",
                "items": {
                    "properties": {
                        "agent_type": {"enum": [...]},
                        "task": {"type": "string"},
                        "context": {"type": "object"}
                    }
                }
            }
        }
    }
}
```

一次 tool_use 可派发多个子 agent，`execute()` 内部 `asyncio.gather()` 并发执行。

### 3.2 Middleware 层：`SubagentOrchestrationMiddleware`

仅对 `composite` 和 `research` intent 生效：

- `on_request_start`: 分析用户消息，预生成 subtask plan
- `on_before_llm`: 将 plan 注入 system prompt，引导 Lead Agent 使用 `dispatch_subagent`

### 3.3 并发规则

- `code_analyst` + `researcher` 可并发
- `diagram` 和 `writer` 依赖前序结果
- `ppt` 依赖 writer 输出

---

## 4. WS 事件扩展

| 事件 | 时机 | 数据 |
|------|------|------|
| `subagent_start` | 子 agent 启动 | `{agent_type, task, agent_id}` |
| `subagent_progress` | 子 agent 每轮 | `{agent_id, round, tool_name, status}` |
| `subagent_content_delta` | 子 agent 流式输出 | `{agent_id, content}` |
| `subagent_complete` | 子 agent 完成 | `{agent_id, status, summary, duration_ms}` |

---

## 5. 错误处理

- 单个子 agent 超时: 120s
- 单个子 agent 失败: 返回 failed result，Lead Agent 自主决策
- 全部超时: 降级为单 agent 模式
- Token: 每个子 agent 独立计算，结果回传截断至 max 2000 chars

---

## 6. 前端 UI — 步骤卡片流

### 6.1 组件树

```
ExecutionTimeline
├── StepCard (Lead Agent round / 工具调用)
│   ├── StepHeader: [图标] [标题] [状态badge] [耗时] [展开箭头]
│   ├── StepContent
│   │   ├── ThinkingBlock (LLM 思考)
│   │   ├── ToolCall (工具调用行)
│   │   └── ContentStream (流式文本)
│   └── SubAgentCards (嵌套子 agent)
│       └── SubAgentCard
│           ├── AgentHeader: [角色图标] [类型] [状态] [进度]
│           └── AgentSteps (迷你步骤)
└── StreamingBlock (当前流式输出)
```

### 6.2 状态样式

| 状态 | 样式 | 图标 |
|------|------|------|
| pending | `bg-slate-100 text-slate-500` | 空心圆 |
| running | `bg-blue-100 text-blue-600` + 脉冲 | spinner |
| completed | `bg-emerald-100 text-emerald-600` | ✓ |
| failed | `bg-red-100 text-red-600` | ✗ |

### 6.3 交互

- 当前步骤自动展开，完成后自动收起
- 子 agent 内部步骤默认收起，点击展开
- Lead Agent 最终回复以正常 MessageBubble 显示

### 6.4 Zustand Store 扩展

```typescript
interface ExecutionStep {
  id: string
  type: 'thinking' | 'tool_call' | 'subagent_dispatch' | 'content'
  status: 'pending' | 'running' | 'completed' | 'failed'
  title: string
  content?: string
  toolName?: string
  duration?: number
  subAgents?: SubAgentState[]
}

interface SubAgentState {
  agentId: string
  agentType: string
  task: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  currentRound: number
  maxRounds: number
  steps: ExecutionStep[]
  result?: string
}
```
