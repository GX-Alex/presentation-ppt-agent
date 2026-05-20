# backend/app/core/subagent.py
"""SubAgent 子任务系统 — 数据模型、角色定义、Prompt 模板、Runner。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

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

SUBAGENT_TIMEOUT_SECONDS = 480

SUBAGENT_ROLES: dict[str, dict[str, Any]] = {
    "code_analyst": {
        "max_rounds": 15,
        "tools": ["parse_project", "read_project_file", "fetch_url"],
        "system_prompt": (
            "<role>你是代码架构分析专家 (Code Analyst Agent)。</role>\n"
            "<task>深入阅读用户提供的源码项目，产出结构化的 Markdown 分析报告。</task>\n"
            "<execution_policy>\n"
            "分析策略（按优先级）：\n"
            "1. 若 <context> 中包含 extract_dir 字段 → 直接调用 read_project_file 读取文件\n"
            "   - extract_dir 是已解压项目的磁盘路径，直接传给 read_project_file 的 extract_dir 参数\n"
            "   - 【必须第一步】调用 read_project_file(extract_dir=<extract_dir值>, file_path=\".\") 获取完整文件树\n"
            "   - 【禁止猜测路径】只能使用文件树中实际存在的路径构造后续调用，不得凭经验猜测文件位置\n"
            "   - 若 <context> 中包含 covered_files 字段，这些文件已被主 Agent 读取分析，直接跳过，优先分析其余文件\n"
            "   - 再逐一读取未覆盖的核心文件\n"
            "2. 若任务中包含 http(s):// URL → 执行远程仓库分析（见下方步骤）\n"
            "3. 若既无 extract_dir 又无 URL → 调用 parse_project 解析本地上传文件\n"
            "4. 若以上均不适用 → 报告：\"❌ 未检测到项目。请提供 GitHub URL 或上传项目文件后重试。\" 然后停止。\n"
            "\n"
            "⚠️ 无论哪种路径，严禁将训练知识作为代码分析内容输出。只分析实际可读取的代码。\n"
            "</execution_policy>\n"
            "<remote_repo_steps>\n"
            "远程仓库分析步骤（仅当任务包含 GitHub URL 时执行）：\n"
            "1. 调用 fetch_url 获取文件树：https://api.github.com/repos/{owner}/{repo}/git/trees/main?recursive=1\n"
            "   - 若返回 HTTP 错误，报告错误码和内容，停止分析，不要继续\n"
            "   - 若 main 分支 404，尝试 master 分支：https://api.github.com/repos/{owner}/{repo}/git/trees/master?recursive=1\n"
            "2. 从文件树中识别关键源码文件（如 *.py, *.ts, *.go 主入口和核心模块）\n"
            "3. 逐一用 fetch_url 读取关键文件（{branch} 为步骤 1 成功使用的分支名，main 或 master）：\n"
            "   https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{filepath}\n"
            "   - 若文件获取失败，跳过该文件并在报告中注明\n"
            "4. 若 GitHub API 返回 403（限速），在报告中说明：\"GitHub API 请求受限，仅能分析以下已获取的文件\"\n"
            "5. 仅基于步骤 1-3 实际获取的内容产出分析报告，不使用训练知识补充\n"
            "</remote_repo_steps>\n"
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
        "max_rounds": 20,
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
        "tools": ["display_diagram", "edit_diagram", "append_diagram", "get_current_diagram", "get_shape_library"],
        "system_prompt": (
            "<role>你是架构图专家 (Diagram Agent)。</role>\n"
            "<task>基于提供的分析报告，生成或修改当前任务的 draw.io 图。</task>\n"
            "<output_format>\n"
            "必须优先调用 diagram tools，不要直接输出完整 XML。\n"
            "- 新建图用 display_diagram\n"
            "- 修改现图前先调用 get_current_diagram\n"
            "- 局部编辑用 edit_diagram\n"
            "- 图太长时用 append_diagram\n"
            "- 如果工具返回 validation.retry_recommended=true，必须依据 issues/suggestions 再修图，最多重试 3 次\n"
            "- 当前模型不是多模态模型，不要宣称看过图片，只能依据结构化审稿结果修正布局\n"
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

MAX_RESULT_CHARS = 8000  # 子 agent 结果回传给 Lead 时的截断长度（提升防截断导致主 agent 误判未完成）


# ── SubAgent Runner ──────────────────────────────────────


async def run_subagent(
    spec: SubAgentSpec,
    parent_task: Any,
    send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    model: str | None = None,
    llm_api_key: str | None = None,
    llm_base_url: str | None = None,
    llm_is_reasoning_model: bool | None = None,
) -> SubAgentResult:
    """运行单个子 agent，返回结果。使用独立 DB session。"""
    from app.core.agent_factory import AgentFactory
    from app.core.agent_runner import AgentRunner
    from app.core.tool_dispatch import get_tool_definitions
    from app.models.database import async_session

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
                elif msg_type in ("diagram_load", "diagram_session_synced"):
                    # 直接透传到父 agent 的 send_fn，确保工作区图表事件到达前端
                    await send_fn(msg)

            ctx, chain = factory.create_subagent(
                spec=spec,
                parent_task=parent_task,
                send_fn=sub_send_fn,
                model=model,
                llm_api_key=llm_api_key,
                llm_base_url=llm_base_url,
                llm_is_reasoning_model=llm_is_reasoning_model,
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

            # 运行子 agent 主循环
            runner = AgentRunner(ctx, chain)
            await asyncio.wait_for(
                runner._run_subagent_loop(ctx, chain),
                timeout=SUBAGENT_TIMEOUT_SECONDS,
            )

            # 提取最终内容
            content = ""
            for msg in reversed(ctx.messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    raw = msg["content"]
                    # 如果是 tool_calls 消息，跳过
                    if isinstance(msg.get("tool_calls"), list):
                        continue
                    content = raw
                    break

            # J2: 若 subagent 循环结束后无文本输出（无论是否耗尽轮次），强制做一次摘要调用
            if not content and len(ctx.messages) > 2:
                logger.info(
                    f"[SubAgent] {spec.agent_type} 循环结束无文本输出"
                    f"（rounds={ctx.round_count}/{ctx.max_rounds}），尝试强制摘要"
                )
                try:
                    from app.core.llm_client import chat as llm_chat
                    forced_resp = await asyncio.wait_for(
                        llm_chat(
                            system=(
                                ctx.system_prompt
                                + "\n\n[系统强制摘要] 你已用完工具调用轮次。"
                                "请立即将截至目前收集到的所有信息整合成最终分析报告，"
                                "不能再调用任何工具，直接输出完整结论文本。"
                            ),
                            messages=ctx.messages,
                            tools=None,
                            model=model,
                            task_id=ctx.task_id,
                            api_key_override=ctx.llm_api_key,
                            base_url_override=ctx.llm_base_url,
                            is_reasoning_model=ctx.llm_is_reasoning_model,
                        ),
                        timeout=90.0,
                    )
                    if forced_resp.content:
                        content = forced_resp.content
                        logger.info(
                            f"[SubAgent] {spec.agent_type} 强制摘要成功"
                            f"，content_len={len(content)}"
                        )
                except Exception as _e:
                    logger.warning(f"[SubAgent] {spec.agent_type} 强制摘要失败: {_e}")

            duration_ms = int((time.monotonic() - t0) * 1000)
            result = SubAgentResult(
                agent_type=spec.agent_type,
                agent_id=agent_id,
                status="completed",
                content=content[:MAX_RESULT_CHARS],
                token_usage={"total": ctx.get_meta("last_total_tokens", 0)},
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
