"""
具体中间件实现 — 从 agent_loop.py 中提取的独立中间件。

每个中间件对应一个原有的内联流程:
  MemoryCaptureMiddleware     — 记忆自动捕获
  AttachmentInjectionMiddleware — 附件自动解析注入
  LoopDetectionMiddleware     — 循环检测
  IntentDetectionMiddleware   — 意图检测 + prompt/tool 动态选择
  TokenBudgetMiddleware       — Token 预算监控 + 告警
  CheckpointMiddleware        — 周期性检查点保存
  PPTEventMiddleware          — PPT 专用事件推送
  ToolErrorMiddleware         — 工具错误处理 (deer-flow 对标)
  BriefEnrichmentMiddleware   — Web Deck 生成时自动补充 brief
"""
import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_middleware import AgentContext, AgentMiddleware
from app.models.tables import Presentation, Slide, Task, TaskMessage

logger = logging.getLogger(__name__)


# ──────────────── 1. MemoryCaptureMiddleware ────────────────


class MemoryCaptureMiddleware(AgentMiddleware):
    """请求开始时检测用户消息中的记忆信号并自动捕获。

    对标 deer-flow MemoryMiddleware — 在消息处理前自动提取记忆信息。
    """

    async def on_request_start(self, ctx: AgentContext) -> None:
        try:
            from app.services.memory_service import detect_memory_signals, capture_memory
            from app.services.user_settings_service import (
                get_user_settings,
                is_auto_memory_capture_enabled,
                is_memory_enabled,
            )

            settings = await get_user_settings(ctx.session, ctx.user_id)
            if not is_memory_enabled(settings):
                return

            signals = detect_memory_signals(ctx.user_message)
            for signal in signals:
                if not is_auto_memory_capture_enabled(settings, signal["category"]):
                    continue

                result = await capture_memory(
                    session=ctx.session,
                    user_id=ctx.user_id,
                    category=signal["category"],
                    content=signal["content"],
                    source="auto_captured",
                    task_id=ctx.task_id,
                )
                if ctx.send_fn:
                    await ctx.send_fn({
                        "type": "memory_captured",
                        "task_id": ctx.task_id,
                        "category": signal["category"],
                        "action": result.get("action", "created"),
                        "content": signal["content"][:100],
                    })
                logger.info(
                    f"[MemoryCapture] 自动捕获: category={signal['category']} "
                    f"action={result.get('action')}"
                )
        except Exception as e:
            logger.warning(f"[MemoryCapture] 记忆自动捕获失败: {e}")


# ──────────────── 2. AttachmentInjectionMiddleware ────────────────

ATTACHMENT_PATTERN = re.compile(
    r"\[附件:\s*(?P<filename>.+?)\s*\(Asset ID:\s*(?P<asset_id>[^,]+),\s*URL:\s*(?P<file_url>[^)]+)\)\]"
)
LEGACY_ATTACHMENT_PATTERN = re.compile(
    r"\[附件:\s*(?P<filename>.+?)\s*\((?!Asset ID:)(?P<file_type>[^,]+),\s*(?P<file_url>[^)]+)\)\]"
)


def _extract_attachment_refs(user_message: str) -> list[dict[str, str]]:
    """从用户消息中提取附件引用，兼容新旧两种格式。"""
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for match in ATTACHMENT_PATTERN.finditer(user_message):
        filename = match.group("filename").strip()
        asset_id = match.group("asset_id").strip()
        file_url = match.group("file_url").strip()
        key = (asset_id, file_url)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"filename": filename, "asset_id": asset_id, "file_url": file_url})

    for match in LEGACY_ATTACHMENT_PATTERN.finditer(user_message):
        filename = match.group("filename").strip()
        file_url = match.group("file_url").strip()
        synthetic_asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, file_url))
        key = (synthetic_asset_id, file_url)
        if key in seen:
            continue
        seen.add(key)
        refs.append({"filename": filename, "asset_id": synthetic_asset_id, "file_url": file_url})

    return refs


class AttachmentInjectionMiddleware(AgentMiddleware):
    """请求开始时自动解析用户消息中的附件并注入为工具上下文。

    避免依赖模型自行发现附件——主动解析并写入数据库。
    """

    async def on_request_start(self, ctx: AgentContext) -> None:
        from app.core.tool_dispatch import dispatch

        attachments = _extract_attachment_refs(ctx.user_message)
        if not attachments:
            return

        ctx.attachments = attachments

        if ctx.send_fn:
            await ctx.send_fn({
                "type": "status",
                "text": f"正在解析附件，共 {len(attachments)} 个...",
                "task_id": ctx.task_id,
            })

        for attachment in attachments:
            params = {
                "asset_id": attachment["asset_id"],
                "file_path": attachment["file_url"],
                "max_chars": 12000,
                "index_chunks": False,
            }
            tool_call_id = f"auto_parse_{uuid.uuid4().hex}"
            tool_result = await dispatch("parse_document", params)

            # 持久化 assistant tool_calls 消息
            assistant_tc_record = TaskMessage(
                id=str(uuid.uuid4()),
                task_id=ctx.task_id,
                role="assistant",
                content=json.dumps({
                    "tool_calls": [{
                        "id": tool_call_id,
                        "name": "parse_document",
                        "input": params,
                    }],
                    "text": f"自动解析附件: {attachment['filename']}",
                }, ensure_ascii=False),
                msg_type="tool_calls",
                created_at=datetime.utcnow(),
            )
            ctx.session.add(assistant_tc_record)

            tool_msg_record = TaskMessage(
                id=str(uuid.uuid4()),
                task_id=ctx.task_id,
                role="tool",
                content=json.dumps(tool_result, ensure_ascii=False),
                msg_type="tool_result",
                tool_name="parse_document",
                tool_input={"_tool_call_id": tool_call_id, **params},
                created_at=datetime.utcnow(),
            )
            ctx.session.add(tool_msg_record)

        await ctx.session.commit()


# ──────────────── 3. LoopDetectionMiddleware ────────────────

# 配置常量
LOOP_DETECT_THRESHOLD = 3
LOOP_DETECT_WINDOW = 6

# PPT 关键词正则 — 用于 LoopDetection 豁免判断和 BriefEnrichment 分流
_PPT_KEYWORDS_RE = re.compile(
    r"ppt|演示文稿|幻灯片|deck|汇报|presentation|路演|课件|演讲稿|提案稿",
    re.IGNORECASE,
)

# 安全配对 — 研究类工具交替是正常模式
_SAFE_ALTERNATING_PAIRS = {
    frozenset({"web_search", "fetch_url"}),
    frozenset({"web_search", "parse_document"}),
}


class LoopDetectionMiddleware(AgentMiddleware):
    """循环检测中间件 — 检测 Agent 是否陷入重复工具调用。

    对标 deer-flow LoopDetectionMiddleware:
    1. 连续 N 次调用同一工具且参数相似 → 首次警告, 二次强制终止
    2. A↔B 交替模式 → 注入提示消息
    """

    def __init__(self) -> None:
        self._history: list[tuple[str, str]] = []
        self._consecutive_warn_count = 0
        self._dispatch_count = 0       # 本 session 内 dispatch_subagent 调用次数

    def _make_sig(self, params: dict[str, Any]) -> str:
        sig_parts = []
        for k in sorted(params.keys()):
            if k.startswith("_"):
                continue
            v = str(params[k])[:100]
            sig_parts.append(f"{k}={v}")
        return "|".join(sig_parts)

    async def on_tool_end(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """记录工具调用。对 dispatch_subagent 完成后注入 webdeck_brief 生成提醒。"""
        sig = self._make_sig(params)
        self._history.append((tool_name, sig))
        if len(self._history) > LOOP_DETECT_WINDOW * 2:
            self._history = self._history[-LOOP_DETECT_WINDOW * 2:]
        if tool_name == "dispatch_subagent":
            self._dispatch_count += 1
            # 研究→PPT 复合任务: subagent 完成后，注入强提醒要求立即输出 webdeck_brief
            is_composite_ppt = bool(_PPT_KEYWORDS_RE.search(ctx.user_message))
            if is_composite_ppt and "subagent_results" in result:
                result["_next_step_directive"] = (
                    "【立即执行 — 严禁再次调用 dispatch_subagent 或 writer】"
                    "所有研究已完成。你现在必须直接输出以下文本（不是工具调用），"
                    "将研究结果打包进 pre_research 字段：\n"
                    '<general-artifact type="webdeck_brief">\n'
                    '{"topic":"...","title":"...","audience":"技术研发团队",'
                    '"goal":"...","page_count":20,"tone":"professional","lang":"zh",'
                    '"must_include":[...],"notes":"","pre_research":[{"content":"(此处填入上方研究结果)",'
                    '"title":"研究报告","source_url":"","query":""}]}\n'
                    "</general-artifact>\n"
                    "严禁调用 dispatch_subagent（writer 角色也不行）、web_search、fetch_url。"
                    "严禁用 run_code 生成文件。直接输出 <general-artifact> 标签文本即可。"
                )
                logger.info(
                    "[LoopDetection] 注入 webdeck_brief 生成指令"
                    f"（研究→PPT 复合任务 dispatch #{self._dispatch_count} 完成）"
                )
        return result

    async def on_round_end(self, ctx: AgentContext) -> None:
        """每轮结束后检查循环模式。"""
        # — dispatch_subagent 重复调用检测 —
        # 主 agent 调用 2 次 dispatch_subagent 说明第一次结果未被识别为完成，正在循环
        # 【豁免】研究→PPT 复合任务允许多次派发（code_analyst + researcher）
        is_composite_ppt_task = (
            ctx.messages
            and ctx.intent in ("composite", None)
            and bool(_PPT_KEYWORDS_RE.search(ctx.messages[-1].get("content", "")))
        )

        if self._dispatch_count >= 2:
            logger.warning(
                f"[LoopDetection] dispatch_subagent 已调用 {self._dispatch_count} 次，"
                f"疑似主 agent 未识别子 agent 结果为完成: task={ctx.task_id} (composite_ppt={is_composite_ppt_task})"
            )
            # 豁免研究→PPT复合任务（允许code_analyst+researcher各派发一次）
            if is_composite_ppt_task and self._dispatch_count < 3:
                logger.info(f"[LoopDetection] 研究→PPT复合任务豁免 dispatch 循环检测 (count={self._dispatch_count})")
                self._loop_warn_count = 0  # 重置警告计数
            elif self._dispatch_count == 2:
                # 首次警告 — 注入提示要求主 agent 直接综合已有结果
                ctx.messages.append({
                    "role": "user",
                    "content": (
                        "[系统提示] 你已多次派发子任务，子 agent 的结果已全部返回在上方。"
                        "请不要再次调用 dispatch_subagent，直接基于已收到的 subagent_results 综合输出最终回复。"
                    ),
                })
                if ctx.send_fn:
                    await ctx.send_fn({
                        "type": "status",
                        "text": "检测到重复派发子任务，正在引导综合已有结果...",
                        "task_id": ctx.task_id,
                    })
            elif self._dispatch_count >= 3:
                # 第三次 — 强制终止
                if ctx.send_fn:
                    await ctx.send_fn({
                        "type": "message",
                        "role": "assistant",
                        "content": "检测到子任务被反复派发且未能收敛，已自动终止。请尝试简化你的请求或分步操作。",
                        "task_id": ctx.task_id,
                    })
                ctx.should_stop = True
                ctx.stop_reason = f"loop_detected: dispatch_subagent x{self._dispatch_count}"
                return

        loop_result = self._check()
        if not loop_result:
            return

        loop_type = loop_result["type"]
        loop_tool = loop_result["tool_name"]

        if loop_type == "consecutive":
            warn_count = loop_result.get("warn_count", 1)
            logger.warning(
                f"[LoopDetection] 循环检测(连续): task={ctx.task_id} "
                f"tool={loop_tool} count={loop_result['count']} warn={warn_count}"
            )

            if warn_count >= 2:
                # 第二次警告 → 强制终止
                if ctx.send_fn:
                    await ctx.send_fn({
                        "type": "message",
                        "role": "assistant",
                        "content": f"检测到工具 {loop_tool} 反复调用且无法取得进展，已自动终止。请换一种方式描述你的需求。",
                        "task_id": ctx.task_id,
                    })
                ctx.should_stop = True
                ctx.stop_reason = f"loop_detected: {loop_tool} consecutive x{warn_count}"
                return

            # 首次警告 → 注入提示
            ctx.messages.append({
                "role": "user",
                "content": (
                    f"[系统提示] 检测到你连续 {loop_result['count']} 次调用工具 {loop_tool} "
                    f"且参数相同，可能陷入循环。请换一种方式解决问题，或直接给出当前已有的结论。"
                ),
            })
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "status",
                    "text": f"检测到重复调用 {loop_tool}，正在调整策略...",
                    "task_id": ctx.task_id,
                })

        elif loop_type == "alternating":
            logger.warning(
                f"[LoopDetection] 循环检测(交替): task={ctx.task_id} "
                f"tools={loop_tool} count={loop_result['count']}"
            )
            ctx.messages.append({
                "role": "user",
                "content": (
                    f"[系统提示] 检测到工具 {loop_tool} 交替调用模式，"
                    f"请确认是否在有效推进任务。如果已获取足够信息，请直接汇总回复。"
                ),
            })

    def _check(self) -> dict[str, Any] | None:
        if len(self._history) < LOOP_DETECT_THRESHOLD:
            return None

        # 连续相同工具+相似参数
        recent = self._history[-LOOP_DETECT_THRESHOLD:]
        names = [h[0] for h in recent]
        sigs = [h[1] for h in recent]
        if len(set(names)) == 1 and len(set(sigs)) == 1:
            self._consecutive_warn_count += 1
            self._history.clear()
            return {
                "type": "consecutive",
                "tool_name": names[0],
                "count": LOOP_DETECT_THRESHOLD,
                "warn_count": self._consecutive_warn_count,
            }

        # A↔B 交替
        window = self._history[-LOOP_DETECT_WINDOW:]
        if len(window) >= 4:
            pattern_names = [h[0] for h in window]
            unique_names = set(pattern_names)
            if len(unique_names) == 2:
                if frozenset(unique_names) in _SAFE_ALTERNATING_PAIRS:
                    return None
                is_alternating = all(
                    pattern_names[i] != pattern_names[i + 1]
                    for i in range(len(pattern_names) - 1)
                )
                if is_alternating:
                    return {
                        "type": "alternating",
                        "tool_name": "/".join(unique_names),
                        "count": len(window),
                    }
        return None


# ──────────────── 4. IntentDetectionMiddleware ────────────────


class IntentDetectionMiddleware(AgentMiddleware):
    """从 LLM 回复中提取意图标记 [INTENT:xxx] 并更新任务状态。"""

    async def on_after_llm(self, ctx: AgentContext, response: Any) -> None:
        if not hasattr(response, "content") or not response.content:
            return
        if hasattr(response, "stop_reason") and response.stop_reason != "end_turn":
            return  # 仅在 end_turn 时检测意图

        intent = self._extract_intent(response.content)
        if intent and ctx.intent is None:
            ctx.intent = intent
            ctx.set_meta("detected_intent", intent)
            logger.info(f"[IntentDetection] 检测到意图: {intent} task={ctx.task_id}")

    @staticmethod
    def _extract_intent(content: str) -> str | None:
        match = re.search(r"\[INTENT:(\w+)\]", content)
        return match.group(1) if match else None


# ──────────────── 5. TokenBudgetMiddleware ────────────────


class TokenBudgetMiddleware(AgentMiddleware):
    """Token 预算监控 — 每轮 LLM 调用后推送用量信息，85% 阈值告警。

    对标 deer-flow 的上下文窗口感知 (但 deer-flow 无独立中间件，内置于框架)。
    """

    def __init__(self, context_window: int = 128000, alert_ratio: float = 0.85) -> None:
        self._context_window = context_window
        self._alert_threshold = int(context_window * alert_ratio)

    async def on_after_llm(self, ctx: AgentContext, response: Any) -> None:
        if not hasattr(response, "prompt_tokens"):
            return

        usage_info: dict[str, Any] = {
            "type": "token_usage",
            "task_id": ctx.task_id,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
            "total_tokens": response.total_tokens,
            "context_window": self._context_window,
            "usage_ratio": round(response.prompt_tokens / self._context_window, 4)
            if self._context_window > 0 else 0,
        }

        if response.prompt_tokens >= self._alert_threshold:
            usage_info["alert"] = True
            usage_info["alert_message"] = (
                f"⚠️ Token 用量已达 {usage_info['usage_ratio']:.0%}，"
                f"建议使用 /compact 压缩上下文"
            )
            logger.warning(
                f"[TokenBudget] task={ctx.task_id} "
                f"prompt_tokens={response.prompt_tokens} "
                f"threshold={self._alert_threshold}"
            )
            if ctx.send_fn:
                await ctx.send_fn({
                    "type": "token_alert",
                    "task_id": ctx.task_id,
                    "message": usage_info["alert_message"],
                    "usage_ratio": usage_info["usage_ratio"],
                })

        if ctx.send_fn:
            await ctx.send_fn(usage_info)


# ──────────────── 6. CheckpointMiddleware ────────────────


class CheckpointMiddleware(AgentMiddleware):
    """周期性检查点保存 — 每 N 轮保存任务状态快照。"""

    def __init__(self, interval: int = 5) -> None:
        self._interval = interval

    async def on_round_end(self, ctx: AgentContext) -> None:
        if ctx.round_count % self._interval != 0:
            return
        await self._save_checkpoint(ctx)

    async def _save_checkpoint(self, ctx: AgentContext) -> None:
        try:
            from app.services.memory_service import save_checkpoint

            msg_result = await ctx.session.execute(
                select(TaskMessage)
                .where(TaskMessage.task_id == ctx.task_id)
                .order_by(TaskMessage.created_at.asc())
            )
            task_messages = msg_result.scalars().all()

            pres_result = await ctx.session.execute(
                select(Presentation)
                .where(Presentation.task_id == ctx.task_id)
                .order_by(Presentation.created_at.asc())
            )
            presentations = pres_result.scalars().all()
            active_presentation = presentations[-1] if presentations else None

            active_presentation_state = None
            if active_presentation:
                slide_result = await ctx.session.execute(
                    select(Slide)
                    .where(Slide.presentation_id == active_presentation.id)
                    .order_by(Slide.index.asc())
                )
                slides = slide_result.scalars().all()
                active_presentation_state = {
                    "presentation_id": active_presentation.id,
                    "title": active_presentation.title,
                    "theme": active_presentation.theme,
                    "outline": active_presentation.outline,
                    "slides": [
                        {
                            "id": slide.id,
                            "index": slide.index,
                            "type": slide.type,
                            "version": slide.version,
                            "speaker_notes": slide.speaker_notes,
                        }
                        for slide in slides
                    ],
                }

            # Get total_tokens from metadata (set by AgentRunner after LLM call)
            total_tokens = ctx.get_meta("last_total_tokens", 0)

            state = {
                "round": ctx.round_count,
                "message_count": len(task_messages),
                "total_tokens": total_tokens,
                "task_message_ids": [msg.id for msg in task_messages],
                "compressed_flags": {
                    msg.id: bool(msg.is_compressed) for msg in task_messages
                },
                "task_intent": ctx.intent,
                "presentation_ids": [p.id for p in presentations],
                "active_presentation": active_presentation_state,
            }
            summary = (
                f"Round {ctx.round_count}: {len(task_messages)} msgs, "
                f"{total_tokens} tokens"
            )
            await save_checkpoint(ctx.session, ctx.task_id, ctx.round_count, state, summary)
        except Exception as e:
            logger.warning(f"[Checkpoint] 检查点保存失败: {e}")
            # 回滚失败的 flush，防止 session 进入不可用状态
            try:
                await ctx.session.rollback()
            except Exception:
                pass


class PPTEventMiddleware(AgentMiddleware):
    """PPT 专用事件推送 — 工具执行后推送 PPT 相关事件到前端。"""

    # 需要特殊处理的 PPT 工具名
    _PPT_TOOLS = {"edit_deck_page"}

    async def on_tool_start(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """edit_deck_page 调用前，从数据库注入当前页面 HTML。"""
        if tool_name == "edit_deck_page":
            return await self._inject_deck_page_html(ctx, params)
        return params

    async def on_tool_end(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        if tool_name not in self._PPT_TOOLS:
            return result
        if "error" in result or result.get("blocked"):
            return result

        if tool_name == "edit_deck_page":
            await self._handle_edit_deck_page(ctx, result)

        return result

    async def _inject_deck_page_html(
        self, ctx: AgentContext, params: dict[str, Any]
    ) -> dict[str, Any]:
        """从 DeckPage 表读取当前 HTML 并注入到 params，供 edit_deck_page 工具使用。"""
        project_id = params.get("project_id", "")
        page_id = params.get("page_id", "")
        if not project_id or not page_id or not ctx.session:
            return params
        try:
            from sqlalchemy import select
            from app.models.tables import DeckPage
            result = await ctx.session.execute(
                select(DeckPage)
                .where(DeckPage.project_id == project_id)
                .where(DeckPage.page_id == page_id)
            )
            deck_page = result.scalar_one_or_none()
            if deck_page and deck_page.html:
                params = dict(params)
                params["current_html"] = deck_page.html
                params["_page_db_id"] = deck_page.id
                params["_page_index"] = deck_page.page_index
                params["_page_title"] = deck_page.title or ""
            else:
                logger.warning(
                    f"[PPTEventMiddleware] DeckPage 未找到或无 HTML: "
                    f"project={project_id}, page={page_id}"
                )
        except Exception as e:
            logger.warning(f"[PPTEventMiddleware] 无法注入 DeckPage HTML: {e}")
        return params

    async def _handle_edit_deck_page(
        self, ctx: AgentContext, tool_result: dict[str, Any]
    ) -> None:
        """edit_deck_page 完成后保存 HTML 到 DeckPage 表并推送 webdeck_page_ready 事件。"""
        from app.services.webdeck_runtime.state_store import deck_state_store
        from app.services.webdeck_runtime.contracts import PageStatus

        project_id = tool_result.get("project_id", "")
        page_id = tool_result.get("page_id", "")
        new_html = tool_result.get("html", "")
        changes_summary = tool_result.get("changes_summary", "")

        if not new_html or not project_id or not page_id or not ctx.session:
            return

        try:
            from sqlalchemy import select
            from app.models.tables import DeckPage
            result = await ctx.session.execute(
                select(DeckPage)
                .where(DeckPage.project_id == project_id)
                .where(DeckPage.page_id == page_id)
            )
            deck_page = result.scalar_one_or_none()
            if deck_page:
                await deck_state_store.save_page_html(
                    ctx.session,
                    deck_page.id,
                    new_html,
                    None,
                    status=PageStatus.COMPLETED.value,
                )
                if ctx.send_fn:
                    await ctx.send_fn({
                        "type": "webdeck_page_ready",
                        "project_id": project_id,
                        "page_id": page_id,
                        "page_index": deck_page.page_index,
                        "title": deck_page.title or "",
                        "html": new_html,
                        "status": "completed",
                        "changes_summary": changes_summary,
                    })
            else:
                logger.warning(
                    f"[PPTEventMiddleware] edit_deck_page: DeckPage 未找到: "
                    f"project={project_id}, page={page_id}"
                )
        except Exception as e:
            logger.warning(f"[PPTEventMiddleware] _handle_edit_deck_page 失败: {e}")


# ──────────────── 8. ToolErrorMiddleware ────────────────


class ToolErrorMiddleware(AgentMiddleware):
    """工具错误处理中间件 — 对标 deer-flow ToolErrorHandlingMiddleware。

    统一处理工具执行异常，将错误转化为 LLM 可理解的提示。
    """

    def __init__(self) -> None:
        self._error_counts: dict[str, int] = {}

    async def on_tool_end(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        if "error" not in result:
            # 成功 → 重置该工具错误计数
            self._error_counts.pop(tool_name, None)
            return result

        error_msg = result.get("error", "unknown error")
        count = self._error_counts.get(tool_name, 0) + 1
        self._error_counts[tool_name] = count

        logger.warning(
            f"[ToolError] {tool_name} 执行失败 ({count}次): {error_msg}"
        )

        if result.get("timeout"):
            result["_error_hint"] = (
                f"工具 {tool_name} 执行超时。建议: "
                f"1) 减少输入数据量  2) 换用替代方案  3) 跳过该步骤"
            )
        elif result.get("blocked"):
            result["_error_hint"] = (
                f"工具 {tool_name} 被拦截: {error_msg}。请使用推荐的替代工具。"
            )
        else:
            result["_error_hint"] = (
                f"工具 {tool_name} 执行出错: {error_msg}。请尝试调整参数或换用其他方法。"
            )

        return result


# ──────────────── 9. BriefEnrichmentMiddleware ────────────────


class BriefEnrichmentMiddleware(AgentMiddleware):
    """Web Deck 生成时自动补充 brief — 从对话历史提取洞察注入规划阶段。

    当检测到 Web Deck 生成意图时，自动从对话上下文中提取:
    - 用户之前讨论的关键分析结论
    - 上传附件的解析结果
    - 对话中提到的数据/事实
    """

    async def on_request_start(self, ctx: AgentContext) -> None:
        # 仅在 PPT/Web Deck 意图时触发；若 intent 尚未设置（首次请求），也从消息文本预判
        is_ppt_intent = ctx.intent in ("ppt", "composite")
        if not is_ppt_intent:
            has_ppt_keywords = bool(re.search(
                r"ppt|演示文稿|幻灯片|deck|汇报|presentation|路演|课件|演讲稿|提案稿",
                ctx.user_message,
                re.IGNORECASE,
            ))
            if not has_ppt_keywords:
                return

        try:
            await self._enrich_brief(ctx)
        except Exception as e:
            logger.warning(f"[BriefEnrichment] brief 补充失败: {e}")

    async def _enrich_brief(self, ctx: AgentContext) -> None:
        """从对话历史中提取洞察补充到 brief。"""
        # 查询最近的对话消息
        stmt = (
            select(TaskMessage)
            .where(TaskMessage.task_id == ctx.task_id)
            .where(TaskMessage.is_compressed == False)  # noqa: E712
            .order_by(TaskMessage.created_at.desc())
            .limit(32)
        )
        result = await ctx.session.execute(stmt)
        messages = list(reversed(result.scalars().all()))

        if not messages:
            return

        # 提取关键洞察
        insights: list[str] = []
        attachment_contents: list[str] = []

        for msg in messages:
            if msg.role == "assistant" and msg.msg_type == "text":
                content = msg.content or ""
                # 提取包含数据/分析的段落
                if any(kw in content for kw in ["分析", "发现", "结论", "建议", "数据显示", "结果表明"]):
                    insights.append(content[:500])

            elif msg.role == "tool" and msg.tool_name == "parse_document":
                content = msg.content or ""
                if len(content) > 100:
                    attachment_contents.append(content[:1500])

        if not insights and not attachment_contents:
            return

        # 将洞察存入 metadata 供后续 briefing service 使用
        enrichment = {}
        if insights:
            enrichment["conversation_insights"] = insights[:5]
        if attachment_contents:
            enrichment["attachment_excerpts"] = attachment_contents[:3]

        ctx.set_meta("brief_enrichment", enrichment)
        logger.info(
            f"[BriefEnrichment] task={ctx.task_id} "
            f"insights={len(insights)} attachments={len(attachment_contents)}"
        )


# ──────────────── 10. SubagentOrchestrationMiddleware ────────────────


class SubagentOrchestrationMiddleware(AgentMiddleware):
    """对 composite/research intent 自动规划子 agent 方案，注入 system prompt。

    根据任务复杂度分级注入:
    - 复合任务 (多个明确步骤): 强制要求使用 dispatch_subagent
    - 单一研究任务: 提示可用 dispatch_subagent, 但不强制
    """

    # 强制模板 — 用于包含多个明确步骤的复合任务
    _COMPOSITE_MANDATORY_TEMPLATE = (
        "\n<subagent_directive>\n"
        "【重要】当前用户请求包含多个独立子任务，你**必须**使用 dispatch_subagent 工具来并发执行。\n"
        "**不要**自己逐步串行执行这些子任务，而是立即调用 dispatch_subagent 一次性派发。\n\n"
        "可用子 Agent 角色:\n"
        "- code_analyst: 代码架构深度分析（需要项目附件时使用）\n"
        "- researcher: 多角度网络搜索与深度研究\n"
        "- diagram: 基于分析报告生成 draw.io 架构图\n"
        "- writer: 综合多份子报告产出最终文档\n\n"
        "执行策略:\n"
        "1. 分析用户需求，拆分为独立子任务\n"
        "2. 立即调用 dispatch_subagent，在 agents 数组中列出所有子任务\n"
        "3. 等待所有子 agent 完成后，综合结果给出最终回复\n\n"
        "示例:\n"
        "用户: \"研究 AI 趋势，然后写一份分析报告\"\n"
        "→ dispatch_subagent({\"agents\": [\n"
        "    {\"agent_type\": \"researcher\", \"task\": \"深入研究 AI 最新发展趋势...\"},\n"
        "    {\"agent_type\": \"writer\", \"task\": \"基于研究结果撰写分析报告...\", "
        "\"context\": {\"依赖\": \"researcher 的输出\"}}\n"
        "  ]})\n"
        "</subagent_directive>"
    )

    # 提示模板 — 用于可能受益于子 agent 的单一任务
    _RESEARCH_HINT_TEMPLATE = (
        "\n<subagent_capability>\n"
        "你可以使用 dispatch_subagent 工具将复杂研究任务分配给专职子 Agent 并发执行。\n"
        "可用角色: researcher(深度研究), writer(综合写作), code_analyst(代码分析), diagram(架构图)。\n"
        "对于需要多角度深度研究的复杂任务，建议使用 dispatch_subagent 而非自己逐步搜索。\n"
        "</subagent_capability>"
    )

    # 研究→PPT 模板 — 用于「先研究/分析，再生成PPT」的复合流程
    _COMPOSITE_RESEARCH_PPT_TEMPLATE = (
        "\n<research_to_ppt_directive>\n"
        "【重要】当前任务是「先研究/分析，再生成PPT」的复合流程。请严格按以下步骤执行：\n\n"
        "第一步 — 调用 dispatch_subagent 派发研究子任务：\n"
        "  - 需要分析 GitHub 代码仓库时，使用 code_analyst（含 fetch_url 能力）\n"
        "  - 需要网络搜索最新信息时，使用 researcher\n"
        "  - 可同时派发多个子 agent 并发研究\n\n"
        "第二步 — 收到所有子 agent 研究结果后，生成 webdeck_brief：\n"
        "  - 将子 agent 的研究结果打包到 pre_research 字段中\n"
        "  - notes 字段：仅当用户明确提出视觉风格/配色/字体/排版要求时才填写；否则必须设为空字符串（系统会自动应用默认麦肯锡专业风格），严禁自行编造或推断风格\n"
        "  - 输出 <general-artifact type=\"webdeck_brief\"> 触发 Web Deck 生成\n\n"
        "webdeck_brief 完整示例（严格按此格式输出，所有字段均需填写）：\n"
        "<general-artifact type=\"webdeck_brief\">\n"
        "{\n"
        "  \"topic\": \"Hermes Agent 技术分享\",\n"
        "  \"title\": \"Hermes Agent：下一代自主智能体框架\",\n"
        "  \"audience\": \"技术研发团队\",\n"
        "  \"goal\": \"介绍 Hermes Agent 的核心架构与应用价值\",\n"
        "  \"page_count\": 20,\n"
        "  \"tone\": \"professional\",\n"
        "  \"lang\": \"zh\",\n"
        "  \"must_include\": [\"核心架构\", \"关键特性\", \"代码示例\", \"性能对比\", \"应用场景\"],\n"
        "  \"notes\": \"\",\n"
        "  \"pre_research\": [\n"
        "    {\n"
        "      \"content\": \"（此处填入 code_analyst/researcher 返回的完整研究内容文本）\",\n"
        "      \"title\": \"Hermes Agent 代码分析报告\",\n"
        "      \"source_url\": \"https://github.com/...\",\n"
        "      \"query\": \"hermes agent 核心架构分析\"\n"
        "    }\n"
        "  ]\n"
        "}\n"
        "</general-artifact>\n\n"
        "⚠️ 严禁直接用 run_code 生成 .pptx 文件 — 必须通过 webdeck_brief 产物标签触发专属流程。\n"
        "⚠️ 严禁用 run_code 生成中间 Markdown 报告或 JSON（浪费时间，用户无法访问）— 研究结果直接打包进 pre_research。\n"
        "⚠️ 研究结果必须通过 pre_research 字段注入，确保内容出现在生成的幻灯片中。\n"
        "⚠️ topic 字段不能为空 — 必须准确填写演示主题，否则无法创建 deck 项目。\n"
        "</research_to_ppt_directive>"
    )

    # 复合任务标志: 包含多个动作动词 / 连接词 (然后/并且/同时/最后)
    _COMPOSITE_CONNECTORS = ["然后", "并且", "同时", "最后", "接着", "之后", "再"]
    _COMPOSITE_ACTION_PAIRS = [
        ("分析", "报告"), ("分析", "图"), ("研究", "报告"), ("研究", "演示"),
        ("搜索", "报告"), ("搜索", "分析"), ("分析", "ppt"), ("分析", "演示"),
        ("研究", "ppt"), ("代码", "图"), ("代码", "报告"), ("代码", "ppt"),
    ]

    def _is_composite_task(self, msg: str) -> bool:
        """检测是否为多步复合任务。"""
        msg_lower = msg.lower()
        # 检查连接词 (表示多步骤)
        has_connector = any(c in msg_lower for c in self._COMPOSITE_CONNECTORS)
        # 检查动作对 (表示多个不同类型的子任务)
        has_action_pair = any(
            a in msg_lower and b in msg_lower
            for a, b in self._COMPOSITE_ACTION_PAIRS
        )
        return has_connector and has_action_pair

    def _is_research_task(self, msg: str) -> bool:
        """检测是否为研究型任务。"""
        msg_lower = msg.lower()
        research_keywords = ["研究", "搜索", "调研", "分析趋势", "深入分析", "综合分析"]
        return any(kw in msg_lower for kw in research_keywords)

    # PPT 关键词正则 — 包含这些词时走专属 webdeck_brief 流程，不注入 dispatch 指令

    async def on_before_llm(self, ctx: AgentContext) -> None:
        # PPT 意图已确认: 走 webdeck_brief 专属流程，不注入 dispatch 指令
        if ctx.intent == "ppt":
            return
        if ctx.intent not in ("composite", "research", None):
            return
        # 仅首轮注入
        if ctx.round_count > 1:
            return

        msg = ctx.user_message
        has_ppt_keywords = bool(_PPT_KEYWORDS_RE.search(msg))
        is_composite = self._is_composite_task(msg)

        if is_composite and has_ppt_keywords:
            # Composite research-then-PPT task: inject research-to-PPT guidance
            ctx.system_prompt += self._COMPOSITE_RESEARCH_PPT_TEMPLATE
            logger.info("[SubagentOrchestration] 检测到「研究+PPT」复合任务，注入研究→WebDeck 指令")
        elif has_ppt_keywords:
            # Pure PPT request (no prior research step): skip dispatch, let webdeck_brief handle it
            logger.info("[SubagentOrchestration] 消息含 PPT 关键词但非复合任务，跳过 dispatch 注入")
            return
        elif is_composite:
            ctx.system_prompt += self._COMPOSITE_MANDATORY_TEMPLATE
            logger.info("[SubagentOrchestration] 检测到复合任务，注入强制 dispatch 指令")
        elif self._is_research_task(msg):
            ctx.system_prompt += self._RESEARCH_HINT_TEMPLATE
            logger.info("[SubagentOrchestration] 检测到研究任务，注入 dispatch 提示")


# ──────────────── 11. WebDeckContextMiddleware ────────────────


class WebDeckContextMiddleware(AgentMiddleware):
    """Web Deck 上下文注入 — 在 LLM 调用前注入当前任务关联的 Deck 项目信息。

    当用户在生成 Web Deck 后发起对话（如"修改第3页标题"），LLM 需要知道
    project_id 和每页的 page_id 才能正确调用 edit_deck_page 工具。
    本中间件在 on_before_llm 时自动查询并注入此上下文。
    """

    async def on_before_llm(self, ctx: AgentContext) -> None:
        # 仅首轮注入，避免重复污染
        if ctx.round_count > 1:
            return
        # 无会话时跳过
        if not ctx.session:
            return
        try:
            await self._inject_deck_context(ctx)
        except Exception as e:
            logger.debug(f"[WebDeckContext] 注入失败（非致命）: {e}")

    async def _inject_deck_context(self, ctx: AgentContext) -> None:
        from sqlalchemy import select
        from app.models.tables import DeckPage
        from app.services.webdeck_runtime.state_store import deck_state_store

        project = await deck_state_store.get_project_by_task(ctx.session, ctx.task_id)
        if not project:
            return

        pages_result = await ctx.session.execute(
            select(DeckPage)
            .where(DeckPage.project_id == project.id)
            .order_by(DeckPage.page_index)
        )
        pages = list(pages_result.scalars().all())
        if not pages:
            return

        page_lines = "\n".join(
            f"  - 第{p.page_index + 1}页 (page_id: {p.page_id}): {p.title or '未命名'}"
            for p in pages
        )
        deck_ctx_block = (
            f"\n<webdeck_context>\n"
            f"当前任务关联的 Web Deck 项目:\n"
            f"- project_id: {project.id}\n"
            f"- 标题: {project.title or '未命名'}\n"
            f"- 共 {len(pages)} 页:\n{page_lines}\n"
            f"如需修改某页，请使用 edit_deck_page 工具，传入上述 project_id 和对应 page_id。\n"
            f"</webdeck_context>"
        )
        ctx.system_prompt += deck_ctx_block
        logger.info(
            f"[WebDeckContext] 注入 deck 上下文: project={project.id}, pages={len(pages)}"
        )
