"""
Agent 运行器 — 重构后的 agent_loop, 使用 AgentContext + MiddlewareChain。

原 agent_loop() 的职责拆分为:
  1. AgentFactory.create()  → 动态构建 ctx + chain
  2. AgentRunner.run()      → 执行主循环, 将所有内联流程委托给中间件

AgentRunner 自身仅保留核心逻辑:
  - 消息持久化
  - LLM 调用
  - 工具分发
  - 上下文组装与压缩
"""
import json
import logging
import re
import uuid

try:
    from json_repair import repair_json as _repair_json
except ImportError:
    _repair_json = None
    logging.getLogger(__name__).warning(
        "[AgentRunner] json_repair 未安装，webdeck_brief JSON 自动修复不可用"
    )
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_factory import AgentFactory
from app.core.agent_middleware import AgentContext, MiddlewareChain
from app.core.agent_prompts import build_base_system_prompt, SYSTEM_PROMPT
from app.core.llm_client import chat_stream, LLMResponse
from app.core.tool_dispatch import dispatch, get_tool_definitions_for_user, filter_tools_by_intent
from app.models.tables import Task, TaskMessage
from app.services.context_service import (
    assemble_context,
    compress_context,
)
from app.services.user_settings_service import get_user_settings as _get_user_settings_for_llm

logger = logging.getLogger(__name__)

MAX_SUBAGENT_TOOL_RESULT = 4000  # 子 agent 内部工具结果截断（增大以减少信息丢失）
DIAGRAM_RUNTIME_TOOLS = {
    "display_diagram",
    "edit_diagram",
    "append_diagram",
    "get_current_diagram",
    "get_shape_library",
}

_DIAGRAM_HISTORY_VALIDATION_KEYS = {
    "valid",
    "fixed",
    "fixes",
    "warnings",
    "error",
    "review_passed",
    "review_mode",
    "retry_recommended",
    "retry_count",
    "max_retries",
    "score",
    "critical_count",
    "warning_count",
    "snapshot_source",
    "updated_at",
}
_DIAGRAM_HISTORY_SESSION_KEYS = {
    "session_id",
    "task_id",
    "version",
    "summary",
    "source",
    "created_at",
}


def _slim_diagram_validation_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    slim: dict[str, Any] = {
        key: payload[key]
        for key in _DIAGRAM_HISTORY_VALIDATION_KEYS
        if key in payload
    }
    issues = payload.get("issues")
    if isinstance(issues, list):
        slim["issues"] = issues[:8]
    suggestions = payload.get("suggestions")
    if isinstance(suggestions, list):
        slim["suggestions"] = suggestions[:5]
    return slim


def _slim_diagram_session_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    slim: dict[str, Any] = {
        key: payload[key]
        for key in _DIAGRAM_HISTORY_SESSION_KEYS
        if key in payload
    }
    validation = _slim_diagram_validation_payload(payload.get("validation"))
    if validation:
        slim["validation"] = validation
    return slim


def _slim_diagram_tool_result(tool_name: str, tool_result: Any, *, for_context: bool) -> Any:
    if not isinstance(tool_result, dict):
        return tool_result

    # get_current_diagram must remain detailed for the active round so the model
    # can inspect current XML before deciding edit operations, but history should
    # still be slim.
    if for_context and tool_name == "get_current_diagram":
        return tool_result

    slim: dict[str, Any] = {}
    for key in ("ok", "error", "has_diagram", "retry_recommended", "blocked", "timeout", "tool"):
        if key in tool_result:
            slim[key] = tool_result[key]

    if "diagram_session" in tool_result:
        slim["diagram_session"] = _slim_diagram_session_payload(tool_result.get("diagram_session"))

    if "validation" in tool_result:
        slim["validation"] = _slim_diagram_validation_payload(tool_result.get("validation"))

    apply_result = tool_result.get("apply_result")
    if isinstance(apply_result, dict):
        slim["apply_result"] = {
            key: apply_result[key]
            for key in ("success", "operations_applied", "errors", "warnings")
            if key in apply_result
        }

    if not slim:
        return tool_result
    return slim


def _build_persisted_tool_result(tool_name: str, tool_result: Any) -> Any:
    if tool_name not in DIAGRAM_RUNTIME_TOOLS:
        return tool_result
    return _slim_diagram_tool_result(tool_name, tool_result, for_context=False)


def _build_context_tool_result(tool_name: str, tool_result: Any) -> Any:
    if tool_name not in DIAGRAM_RUNTIME_TOOLS:
        return tool_result
    return _slim_diagram_tool_result(tool_name, tool_result, for_context=True)


def _classify_llm_error(e: Exception) -> tuple[str, bool]:
    """将 LLM 异常分类为用户友好消息，保留诊断信息。返回 (message, recoverable)。"""
    s = str(e).lower()
    if any(k in s for k in ("context_length", "context length", "maximum context", "too long", "token limit", "tokens exceed", "input too long")):
        return "对话历史过长，正在自动压缩… 请稍后重发消息，或使用 /compact 手动清理上下文", True
    if any(k in s for k in ("overload", "529", "rate limit", "too many request", "service unavailable")):
        return "AI 模型当前负载过高，请等待 30 秒后重试", True
    if any(k in s for k in ("authentication", "invalid_api_key", "401", "forbidden")):
        return "AI 模型认证失败，请检查 API 密钥配置", False
    if any(k in s for k in ("timeout", "timed out", "connection")):
        return "AI 模型连接超时，请检查网络并重试", True
    return "AI 模型暂时不可用，请稍后重试", True


# ──────────── 安全网: 自动检测并包裹 artifact 产物 ────────────

# 已有 <general-artifact> 标签的内容不需要再处理
_ARTIFACT_TAG_RE = re.compile(r"<general-artifact\s+type=\"[^\"]+\">", re.IGNORECASE)

# draw.io XML 检测 (含 <mxfile> 或 <mxGraphModel>)
_DRAWIO_RE = re.compile(r"<mxfile[\s>]|<mxGraphModel[\s>]", re.IGNORECASE)

# 完整 HTML 页面检测 (含 <!DOCTYPE html> 或 <html> + </html>)
_HTML_RE = re.compile(r"(?:<!DOCTYPE\s+html|<html[\s>])[\s\S]{200,}</html>", re.IGNORECASE)


def _auto_wrap_artifact(content: str) -> str:
    """如果 LLM 忘记使用 <general-artifact>，自动检测并包裹可识别的产物内容。

    检测优先级: drawio XML > 完整 HTML 页面
    只在确定识别到完整产物时才包裹，避免误判。
    """
    # 已有标签，不处理
    if _ARTIFACT_TAG_RE.search(content):
        return content

    # 检测 draw.io XML（整段独立的 drawio 内容）
    drawio_match = _DRAWIO_RE.search(content)
    if drawio_match:
        # 尝试提取完整的 XML 块
        xml_start = content.find("<?xml", max(0, drawio_match.start() - 200))
        if xml_start == -1:
            xml_start = content.find("<mxfile", drawio_match.start())
        if xml_start == -1:
            xml_start = content.find("<mxGraphModel", drawio_match.start())
        if xml_start >= 0:
            # 从代码块中提取（如果在 ```xml ... ``` 中）
            code_block_match = re.search(
                r"```(?:xml|drawio)?\s*\n([\s\S]*?)\n```",
                content[max(0, xml_start - 20):],
            )
            if code_block_match:
                xml_content = code_block_match.group(1).strip()
                before = content[:max(0, xml_start - 20) + code_block_match.start()]
                after = content[max(0, xml_start - 20) + code_block_match.end():]
                wrapped = f'<general-artifact type="drawio">\n{xml_content}\n</general-artifact>'
                return f"{before.strip()}\n\n{wrapped}\n\n{after.strip()}".strip()
            # 不在代码块中，尝试找到 </mxfile> 或 </mxGraphModel> 结尾
            for end_tag in ["</mxfile>", "</mxGraphModel>"]:
                end_pos = content.find(end_tag, xml_start)
                if end_pos >= 0:
                    xml_content = content[xml_start:end_pos + len(end_tag)]
                    before = content[:xml_start]
                    after = content[end_pos + len(end_tag):]
                    wrapped = f'<general-artifact type="drawio">\n{xml_content}\n</general-artifact>'
                    return f"{before.strip()}\n\n{wrapped}\n\n{after.strip()}".strip()

    # 检测完整 HTML 页面
    html_match = _HTML_RE.search(content)
    if html_match:
        # 从代码块中提取（如果在 ```html ... ``` 中）
        code_block_match = re.search(
            r"```html\s*\n([\s\S]*?)\n```",
            content,
        )
        if code_block_match:
            html_content = code_block_match.group(1).strip()
            if len(html_content) > 200:  # 确保是实质性 HTML
                before = content[:code_block_match.start()]
                after = content[code_block_match.end():]
                wrapped = f'<general-artifact type="webpage">\n{html_content}\n</general-artifact>'
                return f"{before.strip()}\n\n{wrapped}\n\n{after.strip()}".strip()
        else:
            # HTML 直接在内容中（非代码块包裹）
            html_start = content.find("<!DOCTYPE", html_match.start())
            if html_start == -1:
                html_start = content.find("<html", html_match.start())
            end_pos = content.find("</html>", html_start)
            if html_start >= 0 and end_pos >= 0:
                html_content = content[html_start:end_pos + 7]
                before = content[:html_start]
                after = content[end_pos + 7:]
                wrapped = f'<general-artifact type="webpage">\n{html_content}\n</general-artifact>'
                return f"{before.strip()}\n\n{wrapped}\n\n{after.strip()}".strip()

    return content


# 防止同一 task 并发触发多个 DeckDirector（auto-trigger 与前端 webdeck_generate 竞争）
_deck_trigger_in_flight: set[str] = set()


class AgentRunner:
    """Agent 主循环运行器 — 使用中间件链驱动。

    替代原 agent_loop() 函数, 将所有横切关注点委托给 MiddlewareChain。
    """

    def __init__(self, ctx: AgentContext, chain: MiddlewareChain) -> None:
        self._ctx = ctx
        self._chain = chain

    async def run(self, task: Task) -> None:
        """执行 Agent 主循环。

        Args:
            task: 当前任务 ORM 对象 (需要用于设置标题、更新意图等)
        """
        ctx = self._ctx
        chain = self._chain

        # ── 0. 持久化用户消息 ──
        user_msg_record = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=ctx.task_id,
            role="user",
            content=ctx.user_message,
            msg_type="text",
            created_at=datetime.utcnow(),
        )
        ctx.session.add(user_msg_record)

        if not task.title:
            # 清除附件标记后再截取标题，避免侧边栏显示原始 [附件: ...] 文本
            clean_title = re.sub(r"\[附件: .+?\]", "", ctx.user_message).strip()
            clean_title = clean_title or "未命名任务"
            task.title = clean_title[:50] + ("..." if len(clean_title) > 50 else "")
            task.updated_at = datetime.utcnow()

        await ctx.session.commit()

        # ── 加载用户 LLM 配置（覆盖环境变量）──
        _user_settings = await _get_user_settings_for_llm(ctx.session, ctx.user_id)
        _llm_cfg = _user_settings.get("llm", {})
        if _llm_cfg.get("api_key"):
            ctx.llm_api_key = _llm_cfg["api_key"]
        if _llm_cfg.get("base_url"):
            ctx.llm_base_url = _llm_cfg["base_url"]
        if _llm_cfg.get("is_reasoning_model") is not None:
            ctx.llm_is_reasoning_model = bool(_llm_cfg["is_reasoning_model"])
        if _llm_cfg.get("model") and not ctx.model:
            _model = _llm_cfg["model"]
            _provider = _llm_cfg.get("provider", "")
            if _provider and "/" not in _model:
                ctx.model = f"{_provider}/{_model}"
            else:
                ctx.model = _model

        # ── 1. on_request_start: 记忆捕获、附件注入、brief 补充 ──
        await chain.run_request_start(ctx)
        if ctx.should_stop:
            logger.info(f"[AgentRunner] 请求被中间件终止: {ctx.stop_reason}")
            await chain.run_request_end(ctx)
            return

        # ── 2. 推送 agent_start + "正在思考" 状态 ──
        # agent_start 无条件发送，确保前端立即进入 running 状态、显示终止按钮。
        # 原 stream_start 仅在首个文字 chunk 时发送，直接调工具时前端永远收不到。
        if ctx.send_fn:
            await ctx.send_fn({
                "type": "stream_start",
                "task_id": ctx.task_id,
            })
        if ctx.send_fn:
            await ctx.send_fn({
                "type": "status",
                "text": "正在思考...",
                "task_id": ctx.task_id,
            })

        # ── 3. 组装上下文 ──
        base_prompt = build_base_system_prompt(intent=ctx.intent) if ctx.intent else SYSTEM_PROMPT
        system_prompt, messages, needs_compress = await assemble_context(
            session=ctx.session,
            task_id=ctx.task_id,
            user_id=ctx.user_id,
            base_prompt=base_prompt,
        )

        if needs_compress:
            logger.info(f"[AgentRunner] task={ctx.task_id} 触发自动上下文压缩")
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "status",
                    "text": "上下文较长，正在压缩...",
                    "task_id": ctx.task_id,
                })
            await compress_context(ctx.session, ctx.task_id, ctx.user_id, ctx.send_fn)
            system_prompt, messages, _ = await assemble_context(
                session=ctx.session,
                task_id=ctx.task_id,
                user_id=ctx.user_id,
                base_prompt=base_prompt,
            )

        ctx.system_prompt = system_prompt
        ctx.messages = messages

        # ── 4. 主循环 ──
        try:
            await self._main_loop(ctx, chain, task)
        finally:
            # ── 5. on_request_end: 清理 ──
            await chain.run_request_end(ctx)

    async def _main_loop(
        self,
        ctx: AgentContext,
        chain: MiddlewareChain,
        task: Task,
    ) -> None:
        """核心主循环 — LLM (streaming) → 检查 stop_reason → dispatch_tool → 再次 LLM。"""
        while ctx.round_count < ctx.max_rounds:
            ctx.round_count += 1
            logger.info(f"[AgentRunner] task={ctx.task_id} round={ctx.round_count}")

            # ── on_before_llm: 可修改 messages/tools/system_prompt ──
            await chain.run_before_llm(ctx)
            if ctx.should_stop:
                return

            # ── 工具组装 (按意图动态过滤) ──
            tools = await get_tool_definitions_for_user(ctx.session, ctx.user_id)
            tools = filter_tools_by_intent(tools, ctx.intent)
            ctx.tools = tools

            # ── LLM 流式调用 ──
            response = await self._call_llm_streaming(ctx, chain, task, tools)
            if response is None:
                # 错误已在 _call_llm_streaming 中处理
                return

            # ── 处理 stop_reason ──
            if response.stop_reason == "end_turn":
                # 流式内容已在 _call_llm_streaming 中逐 chunk 推送
                await self._finalize_stream(ctx, chain, task, response)
                return

            elif response.stop_reason == "tool_use":
                await self._handle_tool_use(ctx, chain, task, response)

                # ── on_round_end: 循环检测、检查点 ──
                await chain.run_round_end(ctx)
                if ctx.should_stop:
                    return
                # 继续循环

            else:
                logger.warning(f"[AgentRunner] 未知 stop_reason: {response.stop_reason}")
                if response.content and ctx.send_fn:
                    await ctx.send_fn({
                        "type": "message",
                        "role": "assistant",
                        "content": response.content,
                        "task_id": ctx.task_id,
                    })
                return

        # 超过最大轮次
        logger.warning(f"[AgentRunner] task={ctx.task_id} 达到最大工具调用轮次 {ctx.max_rounds}")
        if ctx.send_fn:
            await ctx.send_fn({
                "type": "message",
                "role": "assistant",
                "content": "抱歉，处理过程过于复杂，已达到最大工具调用轮次。请尝试简化你的请求。",
                "task_id": ctx.task_id,
            })

    async def _call_llm_streaming(
        self,
        ctx: AgentContext,
        chain: MiddlewareChain,
        task: Task,
        tools: list[dict],
    ) -> LLMResponse | None:
        """流式调用 LLM，逐 chunk 推送 content_delta，返回最终 LLMResponse。

        对于 end_turn: 先发 stream_start → N 个 content_delta → 由调用方 finalize
        对于 tool_use: 静默收集，不发流式消息
        返回 None 表示出错（已向客户端推送错误消息）。
        """
        stream_started = False
        try:
            async for chunk in chat_stream(
                system=ctx.system_prompt,
                messages=ctx.messages,
                tools=tools if tools else None,
                model=ctx.model,
                task_id=ctx.task_id,
                api_key_override=ctx.llm_api_key,
                base_url_override=ctx.llm_base_url,
                is_reasoning_model=ctx.llm_is_reasoning_model,
            ):
                chunk_type = chunk.get("type")

                if chunk_type == "content_delta":
                    if not stream_started:
                        stream_started = True
                    # 逐 chunk 推送给前端
                    if ctx.send_fn:
                        await ctx.send_fn({
                            "type": "content_delta",
                            "content": chunk["content"],
                            "task_id": ctx.task_id,
                        })

                elif chunk_type == "tool_use":
                    # tool_use 不需要流式推送，chat_stream 内部已收集
                    pass

                elif chunk_type == "done":
                    response: LLMResponse = chunk["response"]
                    # on_after_llm 中间件
                    ctx.set_meta("last_total_tokens", response.total_tokens)
                    await chain.run_after_llm(ctx, response)
                    return response

                elif chunk_type == "error":
                    raise Exception(chunk.get("error", "Unknown streaming error"))

        except Exception as e:
            logger.exception(f"[AgentRunner] LLM 流式调用失败: {e}")
            # run() 已无条件发送 stream_start，此处无论是否有 content_delta 都需对称发送 stream_end
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "stream_end",
                    "task_id": ctx.task_id,
                    "error": True,
                })
            if ctx.send_fn:
                user_msg, recoverable = _classify_llm_error(e)
                await ctx.send_fn({
                    "type": "error",
                    "message": user_msg,
                    "recoverable": recoverable,
                })
            return None

        # 理论上不会到这里（chat_stream 总会 yield done 或 error）
        logger.warning("[AgentRunner] chat_stream 未正常结束")
        return None

    async def _finalize_stream(
        self,
        ctx: AgentContext,
        chain: MiddlewareChain,
        task: Task,
        response: LLMResponse,
    ) -> None:
        """Finalize streaming end_turn — persist, send stream_end, run middleware."""
        content = response.content

        # 意图检测 (中间件已在 on_after_llm 中处理, 这里同步到 task)
        detected_intent = ctx.get_meta("detected_intent")
        if detected_intent and task.intent is None:
            task.intent = detected_intent
            ctx.intent = detected_intent
            await ctx.session.commit()
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "intent_detected",
                    "intent": detected_intent,
                    "task_id": ctx.task_id,
                })

        # 清除意图标记
        content = re.sub(r"\[INTENT:\w+\]\s*", "", content).strip()
        # 清除 LLM 思考标签（<think>...</think>），避免泄漏到前端
        content = re.sub(r"<think>[\s\S]*?</think>\s*", "", content).strip()

        # 安全网: 如果 LLM 未使用 <general-artifact> 标签但生成了可识别的产物内容，自动包裹
        content = _auto_wrap_artifact(content)

        # 持久化
        assistant_msg = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=ctx.task_id,
            role="assistant",
            content=content,
            msg_type="text",
            token_count=response.total_tokens,
            reasoning_content=response.reasoning_content or None,
            created_at=datetime.utcnow(),
        )
        ctx.session.add(assistant_msg)
        await ctx.session.commit()

        # on_round_end (检查点保存等)
        await chain.run_round_end(ctx)

        # 发送 stream_end，告知前端流式完成
        if ctx.send_fn:
            await ctx.send_fn({
                "type": "stream_end",
                "task_id": ctx.task_id,
                "message_id": assistant_msg.id,
                "content": content,
                "token_usage": {
                    "prompt": response.prompt_tokens,
                    "completion": response.completion_tokens,
                    "total": response.total_tokens,
                },
            })

        # ── 服务端自动检测 webdeck_brief 产物并触发 Deck 生成 ──
        # 前端可能因网络/解析问题未能发送 webdeck_generate，
        # 服务端作为安全网主动检测并启动 DeckDirector。
        await self._auto_trigger_webdeck_if_brief(ctx, content)

    async def _auto_trigger_webdeck_if_brief(
        self, ctx: AgentContext, content: str
    ) -> None:
        """检测 LLM 输出中的 webdeck_brief 产物，自动触发 DeckDirector。

        解决: 前端可能未检测到 webdeck_brief 或未发送 webdeck_generate，
        导致用户看到 brief 但 Deck 从未开始生成。
        """
        if 'type="webdeck_brief"' not in content:
            return

        # 提取 JSON
        brief_match = re.search(
            r'<general-artifact\s+type="webdeck_brief">\s*([\s\S]*?)\s*</general-artifact>',
            content,
        )
        if not brief_match:
            return

        raw_json = brief_match.group(1)
        try:
            brief = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            # LLM 常将 pre_research.content 中的原始研究文本直接嵌入 JSON，
            # 导致未转义的双引号/换行符破坏语法，使用 json_repair 自动修复。
            if _repair_json is None:
                logger.warning("[AgentRunner] json_repair 不可用，跳过自动触发")
                return
            try:
                brief = _repair_json(raw_json, return_objects=True)
                logger.info("[AgentRunner] webdeck_brief JSON 已通过 json_repair 修复")
            except Exception as e:
                logger.warning(
                    "[AgentRunner] webdeck_brief JSON 修复失败，跳过自动触发: %s: %s",
                    type(e).__name__, e,
                )
                return

        topic = str(brief.get("topic") or "").strip()
        if not topic:
            logger.warning("[AgentRunner] webdeck_brief 缺少 topic，跳过自动触发")
            return

        # 检查是否已有 deck 项目（避免重复触发）
        if ctx.task_id in _deck_trigger_in_flight:
            logger.info(f"[AgentRunner] task={ctx.task_id} deck 生成已在进行中，跳过自动触发")
            return
        # 在第一个 await 前占位：asyncio 单线程保证此处 add 是原子的，防止并发重入
        _deck_trigger_in_flight.add(ctx.task_id)
        try:
            from app.services.webdeck_runtime.state_store import deck_state_store
            existing = await deck_state_store.get_project_by_task(ctx.session, ctx.task_id)
            if existing:
                logger.info(
                    f"[AgentRunner] task={ctx.task_id} 已有 deck 项目 {existing.id}，跳过自动触发"
                )
                _deck_trigger_in_flight.discard(ctx.task_id)
                return
        except Exception:
            pass  # 如果查询失败，仍然尝试触发

        logger.info(
            f"[AgentRunner] 检测到 webdeck_brief (topic={topic})，自动触发 Deck 生成: "
            f"task={ctx.task_id}"
        )

        # 异步启动 DeckDirector（不阻塞当前 agent 循环）
        try:
            import asyncio
            from app.services.webdeck_runtime.director import DeckDirector

            director = DeckDirector(send_fn=ctx.send_fn, model=ctx.model)

            async def _run_director():
                try:
                    await director.run(brief=brief, task_id=ctx.task_id, user_id=ctx.user_id)
                except Exception as e:
                    logger.warning(f"[AgentRunner] 自动触发 Deck 生成失败: {e}")
                    if ctx.send_fn:
                        await ctx.send_fn({
                            "type": "error",
                            "message": f"Web Deck 规划出错: {str(e)}",
                            "task_id": ctx.task_id,
                            "recoverable": True,
                        })
                finally:
                    _deck_trigger_in_flight.discard(ctx.task_id)

            asyncio.create_task(_run_director())
        except Exception as e:
            logger.warning(f"[AgentRunner] 无法启动 DeckDirector: {e}")
            _deck_trigger_in_flight.discard(ctx.task_id)

    async def _handle_tool_use(
        self,
        ctx: AgentContext,
        chain: MiddlewareChain,
        task: Task,
        response: LLMResponse,
    ) -> None:
        """处理 tool_use — LLM 要求调用工具。"""
        # ── 拦截 general-artifact 误调用 ──
        # LLM 有时将 <general-artifact> 文本格式标签误解为工具调用，需在分发前重定向为文本输出
        real_tool_calls = [tc for tc in response.tool_calls if tc.name != "general-artifact"]
        artifact_tool_calls = [tc for tc in response.tool_calls if tc.name == "general-artifact"]
        if artifact_tool_calls:
            logger.warning(
                "[AgentRunner] 拦截 %d 个 general-artifact tool_use 调用，重定向为文本输出",
                len(artifact_tool_calls),
            )
            parts = [response.content] if response.content else []
            for tc in artifact_tool_calls:
                artifact_type = tc.input.get("type", "document")
                if "content" in tc.input:
                    artifact_content = str(tc.input["content"])
                else:
                    # webdeck_brief: 整个 input 去掉 type 字段就是 JSON brief
                    brief_data = {k: v for k, v in tc.input.items() if k != "type"}
                    artifact_content = json.dumps(brief_data, ensure_ascii=False, indent=2)
                parts.append(
                    f'<general-artifact type="{artifact_type}">\n{artifact_content}\n</general-artifact>'
                )
            reconstructed_content = "\n\n".join(filter(None, parts))
            if not real_tool_calls:
                # 无其他真实工具调用 — 直接作为 end_turn 处理
                fake_response = replace(
                    response,
                    content=reconstructed_content,
                    stop_reason="end_turn",
                    tool_calls=[],
                )
                await self._finalize_stream(ctx, chain, task, fake_response)
                return
            # 混合情况 — 注入重建文本，继续处理真实工具
            response = replace(response, content=reconstructed_content, tool_calls=real_tool_calls)

        # 推送中间文本
        if response.content and ctx.send_fn:
            await ctx.send_fn({
                "type": "thinking",
                "content": response.content,
                "task_id": ctx.task_id,
            })

        # 构建 assistant 消息 (含 tool_calls)
        assistant_tool_msg: dict[str, Any] = {
            "role": "assistant",
            "content": response.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input, ensure_ascii=False),
                    },
                }
                for tc in response.tool_calls
            ],
        }
        # DeepSeek reasoning models: reasoning_content must be echoed back in subsequent requests
        if response.reasoning_content:
            assistant_tool_msg["reasoning_content"] = response.reasoning_content
        ctx.messages.append(assistant_tool_msg)

        # 持久化 assistant tool_calls
        tool_calls_data = [
            {"id": tc.id, "name": tc.name, "input": tc.input}
            for tc in response.tool_calls
        ]
        assistant_tc_record = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=ctx.task_id,
            role="assistant",
            content=json.dumps(
                {"tool_calls": tool_calls_data, "text": response.content or ""},
                ensure_ascii=False,
            ),
            msg_type="tool_calls",
            reasoning_content=response.reasoning_content or None,
            created_at=datetime.utcnow(),
        )
        ctx.session.add(assistant_tc_record)

        # 逐个执行 Tool
        for tc in response.tool_calls:
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "status",
                    "text": f"正在执行工具: {tc.name}...",
                    "task_id": ctx.task_id,
                })

            # on_tool_start — 中间件可拦截或修改参数
            params = await chain.run_tool_start(ctx, tc.name, tc.input)
            if params is None:
                # 中间件拦截了该工具
                tool_result = {"blocked": True, "tool": tc.name, "reason": "blocked by middleware"}
            else:
                # 为 dispatch_subagent 注入运行时上下文
                if tc.name == "dispatch_subagent":
                    from app.tools.dispatch_subagent import set_runtime_context
                    set_runtime_context(ctx.send_fn, task, ctx.model, ctx.llm_api_key, ctx.llm_base_url, ctx.llm_is_reasoning_model)
                    # 若本次请求已解压了项目压缩包，自动注入 extract_dir 到 code_analyst
                    _extract_dir = ctx.metadata.get("project_extract_dir")
                    if _extract_dir and isinstance(params, dict):
                        # 收集主 Agent 已读取的文件，避免 code_analyst 重复读
                        _covered_files: list[str] = []
                        for _msg in ctx.messages:
                            if _msg.get("role") == "assistant" and isinstance(_msg.get("tool_calls"), list):
                                for _tc in _msg["tool_calls"]:
                                    if isinstance(_tc.get("function"), dict):
                                        if _tc["function"].get("name") == "read_project_file":
                                            try:
                                                _args = json.loads(_tc["function"].get("arguments", "{}"))
                                                _fp = _args.get("file_path", "")
                                                if _fp and _fp != ".":
                                                    _covered_files.append(_fp)
                                            except (json.JSONDecodeError, ValueError):
                                                pass
                        for _agent in params.get("agents", []):
                            if _agent.get("agent_type") == "code_analyst":
                                if not isinstance(_agent.get("context"), dict):
                                    _agent["context"] = {}
                                _agent["context"].setdefault("extract_dir", _extract_dir)
                                if _covered_files:
                                    _agent["context"].setdefault("covered_files", _covered_files)
                elif tc.name in DIAGRAM_RUNTIME_TOOLS:
                    from app.services.diagram_runtime import set_runtime_context as set_diagram_runtime_context
                    set_diagram_runtime_context(ctx.send_fn, ctx.task_id, ctx.user_id)
                elif tc.name == "regenerate_deck_page":
                    from app.tools.regenerate_deck_page import set_runtime_context as set_regen_context
                    set_regen_context(ctx.send_fn)

                tool_result = await dispatch(
                    tc.name,
                    params,
                    session=ctx.session,
                    user_id=ctx.user_id,
                )

            # on_tool_end — 中间件可修改结果 (PPT事件推送、循环记录、错误处理)
            tool_result = await chain.run_tool_end(ctx, tc.name, params or tc.input, tool_result)

            persisted_tool_result = _build_persisted_tool_result(tc.name, tool_result)
            context_tool_result = _build_context_tool_result(tc.name, tool_result)

            # 持久化 Tool 记录
            tool_msg_record = TaskMessage(
                id=str(uuid.uuid4()),
                task_id=ctx.task_id,
                role="tool",
                content=json.dumps(persisted_tool_result, ensure_ascii=False),
                msg_type="tool_result",
                tool_name=tc.name,
                tool_input={"_tool_call_id": tc.id, **(params or tc.input)},
                created_at=datetime.utcnow(),
            )
            ctx.session.add(tool_msg_record)

            # 加入消息列表
            ctx.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(context_tool_result, ensure_ascii=False),
            })

        await ctx.session.commit()

    async def _run_subagent_loop(self, ctx: AgentContext, chain: MiddlewareChain) -> None:
        """子 agent 精简主循环 — 不持久化消息到 DB，不做 context 压缩。"""
        from app.core.tool_dispatch import dispatch as tool_dispatch

        await chain.run_request_start(ctx)
        if ctx.should_stop:
            return

        while ctx.round_count < ctx.max_rounds:
            ctx.round_count += 1

            await chain.run_before_llm(ctx)
            if ctx.should_stop:
                return

            # LLM 调用（复用流式方法）
            response = await self._call_llm_streaming(ctx, chain, None, ctx.tools)
            if response is None:
                return

            if response.stop_reason == "end_turn":
                # 追加最终内容到 messages
                if response.content:
                    assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content}
                    # DeepSeek: 如果有 reasoning_content 也需要回传（非工具调用时可选，但保持一致性）
                    if response.reasoning_content:
                        assistant_msg["reasoning_content"] = response.reasoning_content
                    ctx.messages.append(assistant_msg)
                await chain.run_round_end(ctx)
                return

            if response.stop_reason == "tool_use":
                # 处理工具调用（不持久化到 DB）
                # DeepSeek reasoning models: include reasoning_content for multi-turn continuity
                tool_calls_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.input, ensure_ascii=False)}}
                        for tc in response.tool_calls
                    ],
                }
                # DeepSeek: 必须回传 reasoning_content 给 API
                if response.reasoning_content:
                    tool_calls_msg["reasoning_content"] = response.reasoning_content
                ctx.messages.append(tool_calls_msg)

                for tc in response.tool_calls:
                    params = tc.input

                    # 拦截 general-artifact 误调用（子 agent 中重建为文本 tool result）
                    if tc.name == "general-artifact":
                        artifact_type = params.get("type", "document")
                        if "content" in params:
                            artifact_content = str(params["content"])
                        else:
                            brief_data = {k: v for k, v in params.items() if k != "type"}
                            artifact_content = json.dumps(brief_data, ensure_ascii=False, indent=2)
                        rebuilt = f'<general-artifact type="{artifact_type}">\n{artifact_content}\n</general-artifact>'
                        ctx.messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({"content": rebuilt}, ensure_ascii=False),
                        })
                        continue

                    intercepted = await chain.run_tool_start(ctx, tc.name, params)
                    if intercepted is None:
                        tool_result = {"error": "blocked by middleware"}
                    else:
                        params = intercepted
                        try:
                            if tc.name == "regenerate_deck_page":
                                from app.tools.regenerate_deck_page import set_runtime_context as set_regen_context
                                set_regen_context(ctx.send_fn)
                            elif tc.name in DIAGRAM_RUNTIME_TOOLS:
                                from app.services.diagram_runtime import set_runtime_context as set_diagram_runtime_context
                                if ctx.task_id == "subagent":
                                    logger.warning(
                                        "[SubAgent] diagram 工具注入时 task_id='subagent'，WS 事件可能无法到达前端"
                                    )
                                set_diagram_runtime_context(ctx.send_fn, ctx.task_id, ctx.user_id)
                            tool_result = await tool_dispatch(tc.name, params, session=ctx.session, user_id=ctx.user_id)
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


# ──────────────── 兼容入口 ────────────────

# 全局工厂实例 (默认配置)
_default_factory = AgentFactory()


async def agent_loop_v2(
    task: Task,
    user_message: str,
    session: AsyncSession,
    send_fn: Callable[[dict[str, Any]], Awaitable[None]],
    model: str | None = None,
) -> None:
    """重构后的 Agent 主循环入口 — 使用 Factory + Runner + Middleware。

    签名与原 agent_loop() 完全兼容，可直接替换调用。
    """
    ctx, chain = _default_factory.create(
        task=task,
        user_message=user_message,
        session=session,
        send_fn=send_fn,
        model=model,
    )

    runner = AgentRunner(ctx, chain)
    await runner.run(task)
