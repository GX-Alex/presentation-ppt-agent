"""
Agent 工厂 — 对标 deer-flow make_lead_agent()。

按请求动态构建 Agent，每个 Agent 携带:
  - 动态组装的工具集 (按意图过滤)
  - 绑定的 middleware 链 (不同任务类型绑定不同中间件)
  - 定制的系统提示词 (按意图裁剪 section)

使用方式:
    factory = AgentFactory()
    ctx, chain = factory.create(task=task, user_message=msg, session=session, send_fn=fn)
    runner = AgentRunner(ctx, chain)
    await runner.run()
"""
import json
import logging
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_middleware import AgentContext, AgentMiddleware, MiddlewareChain
from app.core.agent_middlewares import (
    AttachmentInjectionMiddleware,
    BriefEnrichmentMiddleware,
    CheckpointMiddleware,
    IntentDetectionMiddleware,
    LoopDetectionMiddleware,
    MemoryCaptureMiddleware,
    PPTEventMiddleware,
    SubagentOrchestrationMiddleware,
    TokenBudgetMiddleware,
    ToolErrorMiddleware,
    WebDeckContextMiddleware,
)
from app.models.tables import Task
from app.services.context_service import MODEL_CONTEXT_WINDOW

logger = logging.getLogger(__name__)

# 默认用户 ID（一阶段无鉴权）
DEFAULT_USER_ID = "default-user-00000000"

# 最大工具调用轮次
MAX_TOOL_ROUNDS = 25


# ──────────────── 意图 → 中间件配置 ────────────────

# 各意图需要的中间件类型（顺序即执行顺序）
# 基础中间件: 所有意图都需要
_BASE_MIDDLEWARES = [
    "memory_capture",
    "attachment_injection",
    "tool_error",
    "intent_detection",
    "token_budget",
    "loop_detection",
    "checkpoint",
    "subagent_orchestration",
    "brief_enrichment",   # Self-gates on intent at runtime
    "webdeck_context",    # Injects active deck project info for edit_deck_page
]

# 扩展中间件: 按意图追加
_INTENT_EXTRA_MIDDLEWARES: dict[str | None, list[str]] = {
    "ppt":       ["ppt_event"],
    "composite": ["ppt_event"],
    "research":  [],
    "code_analysis": [],
    "chat":      [],
}


class AgentFactory:
    """Lead Agent Factory — 按请求动态构建 Agent。

    对标 deer-flow make_lead_agent():
    - 根据任务类型/意图动态选择中间件链
    - 动态组装工具集
    - 定制系统提示词
    """

    def __init__(
        self,
        *,
        max_rounds: int = MAX_TOOL_ROUNDS,
        context_window: int = MODEL_CONTEXT_WINDOW,
        checkpoint_interval: int = 5,
        token_alert_ratio: float = 0.85,
    ) -> None:
        self._max_rounds = max_rounds
        self._context_window = context_window
        self._checkpoint_interval = checkpoint_interval
        self._token_alert_ratio = token_alert_ratio

    def create(
        self,
        *,
        task: Task,
        user_message: str,
        session: AsyncSession,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        intent_override: str | None = None,
    ) -> tuple[AgentContext, MiddlewareChain]:
        """动态构建 AgentContext 和 MiddlewareChain。

        Args:
            task: 当前任务 ORM 对象
            user_message: 用户输入
            session: 数据库会话
            send_fn: WebSocket 推送回调
            model: 可选 LLM 模型覆盖
            intent_override: 强制指定意图 (跳过自动检测)

        Returns:
            (AgentContext, MiddlewareChain) — 用于 AgentRunner.run()
        """
        user_id = task.user_id or DEFAULT_USER_ID
        intent = intent_override or task.intent

        # 1. 构建 AgentContext
        ctx = AgentContext(
            task_id=task.id,
            user_id=user_id,
            user_message=user_message,
            model=model,
            intent=intent,
            max_rounds=self._max_rounds,
            session=session,
            send_fn=send_fn,
        )

        # 2. 组装 MiddlewareChain
        chain = self._build_chain(intent)

        logger.info(
            f"[AgentFactory] 构建 Agent: task={task.id} intent={intent} "
            f"chain={chain}"
        )

        return ctx, chain

    def _build_chain(self, intent: str | None) -> MiddlewareChain:
        """根据意图组装中间件链。"""
        chain = MiddlewareChain()

        # 基础中间件
        for mw_name in _BASE_MIDDLEWARES:
            mw = self._create_middleware(mw_name)
            if mw:
                chain.add(mw)

        # 意图扩展中间件
        extras = _INTENT_EXTRA_MIDDLEWARES.get(intent, [])
        for mw_name in extras:
            mw = self._create_middleware(mw_name)
            if mw:
                chain.add(mw)

        return chain

    def _create_middleware(self, name: str) -> AgentMiddleware | None:
        """按名称创建中间件实例。"""
        factories: dict[str, Callable[[], AgentMiddleware]] = {
            "memory_capture": MemoryCaptureMiddleware,
            "attachment_injection": AttachmentInjectionMiddleware,
            "tool_error": ToolErrorMiddleware,            "intent_detection": IntentDetectionMiddleware,
            "token_budget": lambda: TokenBudgetMiddleware(
                context_window=self._context_window,
                alert_ratio=self._token_alert_ratio,
            ),
            "loop_detection": LoopDetectionMiddleware,
            "checkpoint": lambda: CheckpointMiddleware(
                interval=self._checkpoint_interval,
            ),
            "ppt_event": PPTEventMiddleware,
            "subagent_orchestration": SubagentOrchestrationMiddleware,
            "brief_enrichment": BriefEnrichmentMiddleware,
            "webdeck_context": WebDeckContextMiddleware,
        }

        factory = factories.get(name)
        if factory is None:
            logger.warning(f"[AgentFactory] 未知中间件: {name}")
            return None

        return factory()

    def create_subagent(
        self,
        *,
        spec: "SubAgentSpec",
        parent_task: Any,
        send_fn: Callable[[dict[str, Any]], Awaitable[None]],
        model: str | None = None,
        llm_api_key: str | None = None,
        llm_base_url: str | None = None,
        llm_is_reasoning_model: bool | None = None,
    ) -> tuple["AgentContext", "MiddlewareChain"]:
        """为子 agent 构建独立的 context + chain。"""
        from app.core.subagent import SUBAGENT_ROLES

        role_cfg = SUBAGENT_ROLES.get(spec.agent_type, {})
        user_id = getattr(parent_task, "user_id", None) or DEFAULT_USER_ID

        # 构建注入上下文的用户消息
        injected_context = ""
        if spec.context:
            injected_context = f"\n\n<context>\n{json.dumps(spec.context, ensure_ascii=False)[:4000]}\n</context>"

        user_message = spec.task_description + injected_context

        ctx = AgentContext(
            task_id=getattr(parent_task, "id", "subagent"),
            user_id=user_id,
            user_message=user_message,
            model=model,
            intent=spec.agent_type,
            max_rounds=spec.max_rounds or role_cfg.get("max_rounds", 8),
            session=None,  # 子 agent 自己开 session
            send_fn=send_fn,
        )
        ctx.system_prompt = role_cfg.get("system_prompt", "")
        if llm_api_key is not None:
            ctx.llm_api_key = llm_api_key
        if llm_base_url is not None:
            ctx.llm_base_url = llm_base_url
        if llm_is_reasoning_model is not None:
            ctx.llm_is_reasoning_model = llm_is_reasoning_model

        # 子 agent 用精简 chain — 只保留 tool_error 和 loop_detection
        chain = MiddlewareChain()
        for mw_name in ["tool_error", "loop_detection"]:
            mw = self._create_middleware(mw_name)
            if mw:
                chain.add(mw)
        return ctx, chain
