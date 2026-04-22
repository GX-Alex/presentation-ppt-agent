# backend/app/tools/dispatch_subagent.py
"""dispatch_subagent — 派发子任务给专职 Agent 并发执行。"""
import asyncio
import contextvars
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

# 运行时注入的引用 — 使用 contextvars 保证协程安全
_send_fn_var: contextvars.ContextVar = contextvars.ContextVar("dispatch_send_fn", default=None)
_task_var: contextvars.ContextVar = contextvars.ContextVar("dispatch_task", default=None)
_model_var: contextvars.ContextVar = contextvars.ContextVar("dispatch_model", default=None)


def set_runtime_context(send_fn, task, model=None):
    """在 tool dispatch 前设置运行时上下文（协程级隔离）。"""
    _send_fn_var.set(send_fn)
    _task_var.set(task)
    _model_var.set(model)


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """并发执行多个子 agent。"""
    from app.core.subagent import SubAgentSpec, run_subagent, SUBAGENT_ROLES

    agents_specs = params.get("agents", [])
    if not agents_specs:
        return {"error": "agents 列表为空"}

    send_fn = _send_fn_var.get(None)
    task = _task_var.get(None)
    model = _model_var.get(None)

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
