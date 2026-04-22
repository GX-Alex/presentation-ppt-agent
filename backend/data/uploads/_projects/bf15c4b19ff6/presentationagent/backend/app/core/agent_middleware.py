"""
Agent 中间件协议 — 借鉴 deer-flow 14 层有序中间件链设计。

核心思想:
- AgentContext: 每次请求的共享状态，贯穿整个中间件链和 Agent 主循环
- AgentMiddleware: 中间件协议，定义 before/after/on_tool_start/on_tool_end 钩子
- MiddlewareChain: 有序执行中间件链

deer-flow 中间件对标:
  DanglingToolCallMiddleware   → 内置于主循环 (tool_calls 配对)
  ToolErrorHandlingMiddleware  → ToolErrorMiddleware (新增)
  SummarizationMiddleware      → 内置于 context_service (compress_context)
  MemoryMiddleware             → MemoryCaptureMiddleware
  LoopDetectionMiddleware      → LoopDetectionMiddleware
  SubagentLimitMiddleware      → 内置于 MAX_TOOL_ROUNDS

本项目扩展中间件:
  AttachmentInjectionMiddleware — 附件自动解析注入
  IntentDetectionMiddleware    — 意图检测 + prompt/tool 动态选择
  TokenBudgetMiddleware        — Token 预算监控 + 告警
  CheckpointMiddleware         — 周期性检查点保存
  PPTEventMiddleware           — PPT 专用事件推送
  BriefEnrichmentMiddleware    — Web Deck 生成时自动补充 brief
"""
import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ──────────────── AgentContext: 每请求共享状态 ────────────────

@dataclass
class AgentContext:
    """Agent 单次请求的完整上下文，贯穿中间件链和主循环。

    对标 deer-flow 的 ThreadState，但采用 Python dataclass 而非 LangGraph reducer。
    每个字段都可被中间件读取和修改。
    """
    # ── 请求输入 ──
    task_id: str
    user_id: str
    user_message: str
    model: str | None = None

    # ── 意图 & 配置 ──
    intent: str | None = None                         # ppt/research/chat/code_analysis/composite
    active_prompt_sections: list[str] | None = None   # 动态启用的 prompt section

    # ── 上下文组装结果 ──
    system_prompt: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)

    # ── 运行时状态 ──
    round_count: int = 0
    max_rounds: int = 15
    should_stop: bool = False     # 中间件可设置此标志强制终止
    stop_reason: str = ""         # 终止原因

    # ── 数据库 & 推送 ──
    session: AsyncSession | None = None  # Always provided by AgentRunner; None only for testing
    send_fn: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    # ── 附件 ──
    attachments: list[dict[str, str]] = field(default_factory=list)

    # ── 中间件共享存储 (任意 KV) ──
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    def set_meta(self, key: str, value: Any) -> None:
        self.metadata[key] = value


# ──────────────── AgentMiddleware: 中间件协议 ────────────────

class AgentMiddleware(ABC):
    """Agent 中间件基类。

    中间件可以实现以下钩子 (均为可选):
    - on_request_start:  请求开始前（用户消息持久化后，LLM 调用前）
    - on_before_llm:     每轮 LLM 调用前（可修改 messages/tools/system_prompt）
    - on_after_llm:      每轮 LLM 响应后（可检查/修改响应）
    - on_tool_start:     每次工具调用前（可拦截或修改参数）
    - on_tool_end:       每次工具调用后（可修改结果或推送事件）
    - on_round_end:      每轮结束后（可注入消息或设置 should_stop）
    - on_request_end:    请求完全结束后（清理资源）

    对标 deer-flow 的 AgentMiddleware 接口，但更细粒度——
    deer-flow 只有 before/after model call，我们拆分为 7 个钩子点
    以覆盖 tool 执行、轮次结束等关键时机。
    """

    @property
    def name(self) -> str:
        """中间件名称 (用于日志和调试)。"""
        return self.__class__.__name__

    async def on_request_start(self, ctx: AgentContext) -> None:
        """请求开始时调用。可用于初始化、附件注入、记忆捕获等。"""
        pass

    async def on_before_llm(self, ctx: AgentContext) -> None:
        """每轮 LLM 调用前。可修改 ctx.messages, ctx.tools, ctx.system_prompt。"""
        pass

    async def on_after_llm(self, ctx: AgentContext, response: Any) -> None:
        """每轮 LLM 响应后。response 为 LLMResponse 对象。"""
        pass

    async def on_tool_start(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """工具调用前。返回修改后的 params，返回 None 表示跳过该工具。"""
        return params

    async def on_tool_end(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """工具调用后。返回可能修改过的 result。"""
        return result

    async def on_round_end(self, ctx: AgentContext) -> None:
        """每轮结束后。可注入消息到 ctx.messages 或设置 ctx.should_stop。"""
        pass

    async def on_request_end(self, ctx: AgentContext) -> None:
        """请求完全结束后。用于清理、日志等。"""
        pass


# ──────────────── MiddlewareChain: 有序执行 ────────────────

class MiddlewareChain:
    """有序中间件链。

    对标 deer-flow 的 _assemble_from_features()，但使用显式列表而非
    @Next/@Prev 装饰器——在当前项目规模下更简单直接。

    中间件按列表顺序执行 on_request_start/on_before_llm/on_tool_start；
    反向执行 on_after_llm/on_tool_end/on_round_end/on_request_end (洋葱模型)。
    """

    def __init__(self, middlewares: list[AgentMiddleware] | None = None):
        self._middlewares: list[AgentMiddleware] = middlewares or []

    @property
    def middlewares(self) -> list[AgentMiddleware]:
        return self._middlewares

    def add(self, middleware: AgentMiddleware) -> "MiddlewareChain":
        """追加一个中间件到链尾。"""
        self._middlewares.append(middleware)
        return self

    def insert_before(self, anchor_type: type, middleware: AgentMiddleware) -> "MiddlewareChain":
        """在指定类型中间件之前插入 (对标 deer-flow @Prev)。"""
        for i, m in enumerate(self._middlewares):
            if isinstance(m, anchor_type):
                self._middlewares.insert(i, middleware)
                return self
        # 未找到锚点——追加到末尾
        self._middlewares.append(middleware)
        return self

    def insert_after(self, anchor_type: type, middleware: AgentMiddleware) -> "MiddlewareChain":
        """在指定类型中间件之后插入 (对标 deer-flow @Next)。"""
        for i, m in enumerate(self._middlewares):
            if isinstance(m, anchor_type):
                self._middlewares.insert(i + 1, middleware)
                return self
        self._middlewares.append(middleware)
        return self

    async def run_request_start(self, ctx: AgentContext) -> None:
        """正序执行所有 on_request_start。"""
        for mw in self._middlewares:
            try:
                await mw.on_request_start(ctx)
                if ctx.should_stop:
                    logger.info(f"[MiddlewareChain] {mw.name} 终止请求: {ctx.stop_reason}")
                    return
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_request_start 异常: {e}")

    async def run_before_llm(self, ctx: AgentContext) -> None:
        """正序执行所有 on_before_llm。"""
        for mw in self._middlewares:
            try:
                await mw.on_before_llm(ctx)
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_before_llm 异常: {e}")

    async def run_after_llm(self, ctx: AgentContext, response: Any) -> None:
        """反序执行所有 on_after_llm (洋葱模型)。"""
        for mw in reversed(self._middlewares):
            try:
                await mw.on_after_llm(ctx, response)
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_after_llm 异常: {e}")

    async def run_tool_start(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """正序执行所有 on_tool_start。任一返回 None 则跳过该工具。"""
        current_params = params
        for mw in self._middlewares:
            try:
                result = await mw.on_tool_start(ctx, tool_name, current_params)
                if result is None:
                    logger.info(f"[MiddlewareChain] {mw.name} 拦截工具: {tool_name}")
                    return None
                current_params = result
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_tool_start 异常: {e}")
        return current_params

    async def run_tool_end(
        self, ctx: AgentContext, tool_name: str, params: dict[str, Any], result: dict[str, Any]
    ) -> dict[str, Any]:
        """反序执行所有 on_tool_end。"""
        current_result = result
        for mw in reversed(self._middlewares):
            try:
                current_result = await mw.on_tool_end(ctx, tool_name, params, current_result)
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_tool_end 异常: {e}")
        return current_result

    async def run_round_end(self, ctx: AgentContext) -> None:
        """反序执行所有 on_round_end。"""
        for mw in reversed(self._middlewares):
            try:
                await mw.on_round_end(ctx)
                if ctx.should_stop:
                    logger.info(f"[MiddlewareChain] {mw.name} 终止循环: {ctx.stop_reason}")
                    return
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_round_end 异常: {e}")

    async def run_request_end(self, ctx: AgentContext) -> None:
        """反序执行所有 on_request_end (清理)。"""
        for mw in reversed(self._middlewares):
            try:
                await mw.on_request_end(ctx)
            except Exception as e:
                logger.warning(f"[MiddlewareChain] {mw.name}.on_request_end 异常: {e}")

    def __repr__(self) -> str:
        names = [mw.name for mw in self._middlewares]
        return f"MiddlewareChain({' → '.join(names)})"
