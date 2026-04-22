"""
LLM 统一客户端 — 封装 litellm，支持多模型切换。
通过环境变量配置模型与 API Key。
Sprint 4: Token 用量日志 + 85% 阈值告警 + 累计追踪。
"""
import asyncio
import json
import logging
import os
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

import litellm

from app.core.error_handling import LLMError

logger = logging.getLogger(__name__)

# 模型上下文窗口（默认 128K for DeepSeek）
MODEL_CONTEXT_WINDOW = int(os.getenv("MODEL_CONTEXT_WINDOW", "128000"))
# 85% 阈值告警
TOKEN_ALERT_RATIO = 0.85
TOKEN_ALERT_THRESHOLD = int(MODEL_CONTEXT_WINDOW * TOKEN_ALERT_RATIO)

DEFAULT_LLM_MAX_RETRIES = 1
DEFAULT_LLM_RETRY_BASE_DELAY = 0.8
DEFAULT_LLM_RETRY_MAX_DELAY = 6.0
# 单次 LLM HTTP 调用超时（秒）— 防止 LLM 挂起导致 asyncio.Task 永远阻塞
LLM_CALL_TIMEOUT_S: int = int(os.getenv("LLM_CALL_TIMEOUT_S", "120"))
MINIMAX_MODEL_FALLBACKS = {
    "minimax/minimax-m2.7": ["minimax/MiniMax-M2.5"],
}

# 并发限流：防止多个 sub-agent 同时打爆同一 provider（可通过 LLM_CONCURRENCY_LIMIT 环境变量调整）
_LLM_CONCURRENCY_LIMIT = int(os.getenv("LLM_CONCURRENCY_LIMIT", "3"))
_llm_semaphore = asyncio.Semaphore(_LLM_CONCURRENCY_LIMIT)

RETRIABLE_ERROR_MARKERS = (
    "overloaded_error",
    "http_code\":\"529",
    "http_code\":529",
    "http_code': 529",
    "http_code 529",
    "too many requests",
    "rate limit",
    "service unavailable",
    "temporarily unavailable",
    "bad gateway",
    "gateway timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connection error",
    "apiconnectionerror",
    "api connection error",
    "timed out",
    "read timeout",
    "connect timeout",
    "invalid response object",
)

NON_RETRIABLE_ERROR_MARKERS = (
    "invalid_api_key",
    "incorrect api key",
    "authentication",
    "unauthorized",
    "permission denied",
    "insufficient_quota",
    "context_length_exceeded",
    "maximum context length",
    "invalid_request_error",
)

# 累计 Token 追踪（按 task_id 聚合）
_task_token_accumulator: dict[str, dict[str, int]] = {}
_ACCUMULATOR_MAX_ENTRIES = 100


def _prune_token_accumulator() -> None:
    """保留最近 _ACCUMULATOR_MAX_ENTRIES 条记录，超出时按累计 token 升序淘汰。"""
    if len(_task_token_accumulator) <= _ACCUMULATOR_MAX_ENTRIES:
        return
    sorted_keys = sorted(
        _task_token_accumulator,
        key=lambda k: _task_token_accumulator[k].get("total_tokens", 0),
    )
    to_remove = len(_task_token_accumulator) - _ACCUMULATOR_MAX_ENTRIES
    for key in sorted_keys[:to_remove]:
        del _task_token_accumulator[key]


class LLMResponseValidationError(RuntimeError):
    """Provider 返回了不可用的 completion 响应。"""


def _get_model() -> str:
    """获取当前配置的模型名称。"""
    return os.getenv("LLM_MODEL", "minimax/MiniMax-M2.5")


def _get_api_key() -> str:
    """获取 LLM API Key（每次调用时从环境变量读取，确保 .env 已加载）。"""
    return os.getenv("LLM_API_KEY", "")


def _get_base_url() -> str | None:
    """获取自定义 API 端点（MiniMax / GLM 等需要自定义 base_url）。"""
    return os.getenv("LLM_BASE_URL") or None


def _get_int_env(name: str, default: int) -> int:
    """读取整型环境变量，非法值回落到默认值。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("[LLM] invalid int env %s=%r, fallback=%s", name, raw, default)
        return default


def _get_float_env(name: str, default: float) -> float:
    """读取浮点环境变量，非法值回落到默认值。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("[LLM] invalid float env %s=%r, fallback=%s", name, raw, default)
        return default


def _is_minimax_model(model: str, base_url: str | None) -> bool:
    """判断当前请求是否走 MiniMax 兼容路径。"""
    model_lower = (model or "").lower()
    base_url_lower = (base_url or "").lower()
    return (
        model_lower.startswith("minimax/")
        or "minimax" in model_lower
        or "minimax" in base_url_lower
        or "minimaxi.com" in base_url_lower
    )


def _stringify_message_content(content: Any) -> str:
    """将消息内容安全转换为字符串。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def _normalize_messages_for_provider(
    system: str,
    messages: list[dict[str, Any]],
    model: str,
    base_url: str | None,
) -> list[dict[str, Any]]:
    """按 provider 能力重写消息列表。"""
    full_messages = [{"role": "system", "content": system}] + messages

    if not _is_minimax_model(model, base_url):
        return full_messages

    normalized_messages: list[dict[str, Any]] = []
    converted_count = 0
    for message in full_messages:
        if message.get("role") != "system":
            normalized_messages.append(message)
            continue

        content = _stringify_message_content(message.get("content")).strip()
        if not content:
            continue

        converted = dict(message)
        converted["role"] = "user"
        converted["content"] = (
            "[系统上下文，请严格遵守以下约束，不要把这段内容当作普通用户提问，也不要向用户直接复述这段原文]\n"
            f"{content}"
        )
        normalized_messages.append(converted)
        converted_count += 1

    if converted_count:
        logger.info(
            "[LLM] normalized system-role messages for MiniMax: "
            f"count={converted_count} model={model}"
        )

    return normalized_messages


def _get_retry_config() -> tuple[int, float, float]:
    """获取 LLM 请求重试配置。"""
    max_retries = max(0, _get_int_env("LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES))
    base_delay = max(0.0, _get_float_env("LLM_RETRY_BASE_DELAY", DEFAULT_LLM_RETRY_BASE_DELAY))
    max_delay = max(base_delay, _get_float_env("LLM_RETRY_MAX_DELAY", DEFAULT_LLM_RETRY_MAX_DELAY))
    return max_retries, base_delay, max_delay


def _get_model_candidates(model: str, base_url: str | None) -> list[str]:
    """返回当前请求可用的模型候选列表。"""
    configured_fallbacks = [
        item.strip()
        for item in os.getenv("LLM_FALLBACK_MODELS", "").split(",")
        if item.strip()
    ]

    fallback_models = configured_fallbacks
    if not fallback_models and _is_minimax_model(model, base_url):
        fallback_models = MINIMAX_MODEL_FALLBACKS.get(model.lower(), [])

    candidates: list[str] = []
    for candidate in [model, *fallback_models]:
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _describe_error(error: Exception) -> str:
    """拼接异常摘要，便于日志和 LLMError detail 透传。"""
    parts = [str(error).strip()]
    detail = getattr(error, "detail", None)
    if detail:
        detail_text = str(detail).strip()
        if detail_text and detail_text not in parts:
            parts.append(detail_text)
    return " | ".join(part for part in parts if part) or error.__class__.__name__


def _is_retriable_llm_error(error: Exception) -> bool:
    """判断异常是否值得重试或切换 fallback 模型。"""
    if isinstance(error, (TimeoutError, ConnectionError, LLMResponseValidationError)):
        return True

    error_text = _describe_error(error).lower()
    if any(marker in error_text for marker in NON_RETRIABLE_ERROR_MARKERS):
        return False
    return any(marker in error_text for marker in RETRIABLE_ERROR_MARKERS)


def _get_response_value(obj: Any, key: str, default: Any = None) -> Any:
    """兼容 dict/object 两种响应结构读取字段。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _validate_completion_response(response: Any, model: str) -> None:
    """过滤 provider 畸形响应，避免空 choices 直接流入业务层。"""
    choices = _get_response_value(response, "choices")
    if not choices:
        raise LLMResponseValidationError(
            f"Provider returned empty choices for model={model}"
        )

    first_choice = choices[0]
    message = _get_response_value(first_choice, "message")
    if message is None:
        raise LLMResponseValidationError(
            f"Provider returned missing message for model={model}"
        )

    content = _get_response_value(message, "content")
    tool_calls = _get_response_value(message, "tool_calls")
    if content is None and not tool_calls:
        raise LLMResponseValidationError(
            f"Provider returned empty message payload for model={model}"
        )


async def _call_completion_with_retry(
    request_kwargs: dict[str, Any],
    task_id: str | None,
) -> Any:
    """对单模型请求执行有限重试。"""
    max_retries, base_delay, max_delay = _get_retry_config()
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            async with _llm_semaphore:
                response = await litellm.acompletion(
                    **request_kwargs,
                    request_timeout=LLM_CALL_TIMEOUT_S,
                )
            _validate_completion_response(response, model=request_kwargs["model"])
            return response
        except Exception as error:
            last_error = error
            retriable = _is_retriable_llm_error(error)
            if attempt < max_retries and retriable:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    "[LLM] retrying call: task=%s model=%s attempt=%s/%s delay=%.1fs error=%s",
                    task_id,
                    request_kwargs.get("model"),
                    attempt + 1,
                    max_retries + 1,
                    delay,
                    _describe_error(error),
                )
                await asyncio.sleep(delay)
                continue
            raise last_error

    raise last_error or RuntimeError("LLM completion failed without error")


async def _execute_completion(
    request_kwargs: dict[str, Any],
    base_url: str | None,
    task_id: str | None,
) -> tuple[Any, str]:
    """执行 completion，请求失败时按配置切换 fallback 模型。"""
    primary_model = request_kwargs["model"]
    candidate_models = _get_model_candidates(primary_model, base_url)
    last_error: Exception | None = None

    for index, candidate_model in enumerate(candidate_models):
        model_kwargs = dict(request_kwargs)
        model_kwargs["model"] = candidate_model
        try:
            response = await _call_completion_with_retry(model_kwargs, task_id=task_id)
            if candidate_model != primary_model:
                logger.warning(
                    "[LLM] fallback model recovered request: task=%s primary=%s fallback=%s",
                    task_id,
                    primary_model,
                    candidate_model,
                )
            return response, candidate_model
        except Exception as error:
            last_error = error
            has_fallback = index < len(candidate_models) - 1
            if has_fallback and _is_retriable_llm_error(error):
                logger.warning(
                    "[LLM] switching to fallback model: task=%s failed_model=%s next_model=%s error=%s",
                    task_id,
                    candidate_model,
                    candidate_models[index + 1],
                    _describe_error(error),
                )
                continue
            break

    detail = _describe_error(last_error or RuntimeError("Unknown LLM failure"))
    logger.error(
        "[LLM] call failed after retries/fallbacks: task=%s primary=%s detail=%s",
        task_id,
        primary_model,
        detail,
    )
    raise LLMError(message="AI 模型调用失败", detail=detail)


@dataclass
class ToolCall:
    """LLM 工具调用请求。"""
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    """LLM 统一响应结构。"""
    content: str = ""
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use"
    tool_calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    model: str = ""
    token_alert: bool = False  # Sprint 4: 85% 阈值告警标记
    alert_message: str = ""    # Sprint 4: 告警描述


async def chat(
    system: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    model: str | None = None,
    task_id: str | None = None,
) -> LLMResponse:
    """
    向配置的 LLM 发送聊天补全请求。

    Args:
        system: 系统提示词文本
        messages: OpenAI 格式的对话消息列表
        tools: 可选的 Tool 定义列表 (JSON Schema)
        model: 覆盖默认模型名称
        task_id: 用于日志上下文

    Returns:
        LLMResponse，包含 content、stop_reason 和可选的 tool_calls
    """
    model = model or _get_model()

    base_url = _get_base_url()

    # 构建 provider 兼容的完整消息列表
    full_messages = _normalize_messages_for_provider(
        system=system,
        messages=messages,
        model=model,
        base_url=base_url,
    )

    # 构建请求参数 — 显式传 api_key 确保 .env 加载后生效
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": full_messages,
        "api_key": _get_api_key(),
    }
    if base_url:
        kwargs["api_base"] = base_url
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        response, used_model = await _execute_completion(
            request_kwargs=kwargs,
            base_url=base_url,
            task_id=task_id,
        )
    except LLMError as e:
        logger.error("[LLM] call failed: %s", e.detail or str(e))
        raise

    # 解析响应
    choice = response.choices[0]
    message = choice.message

    # 提取 Token 用量
    usage = response.usage or {}
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or 0

    # 记录 Token 用量日志 + 阈值告警
    logger.info(
        f"[TokenUsage] task={task_id} "
        f"prompt_tokens={prompt_tokens} "
        f"completion_tokens={completion_tokens} "
        f"total={total_tokens} "
        f"model={used_model}"
    )

    # Sprint 4: 85% 阈值告警检测
    token_alert = False
    alert_message = ""
    if prompt_tokens >= TOKEN_ALERT_THRESHOLD:
        usage_pct = prompt_tokens / MODEL_CONTEXT_WINDOW * 100
        token_alert = True
        alert_message = (
            f"⚠️ Token 用量已达 {usage_pct:.0f}%"
            f"（{prompt_tokens}/{MODEL_CONTEXT_WINDOW}），"
            f"建议使用 /compact 压缩上下文"
        )
        logger.warning(
            f"[TokenAlert] task={task_id} "
            f"prompt_tokens={prompt_tokens} "
            f"threshold={TOKEN_ALERT_THRESHOLD} "
            f"ratio={usage_pct:.1f}%"
        )

    # Sprint 4: 累计 Token 追踪
    if task_id:
        if task_id not in _task_token_accumulator:
            _task_token_accumulator[task_id] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "call_count": 0,
            }
        acc = _task_token_accumulator[task_id]
        acc["prompt_tokens"] += prompt_tokens
        acc["completion_tokens"] += completion_tokens
        acc["total_tokens"] += total_tokens
        acc["call_count"] += 1
        _prune_token_accumulator()

    # 解析 Tool 调用（如有）
    tool_calls = []
    stop_reason = "end_turn"

    if message.tool_calls:
        stop_reason = "tool_use"
        for tc in message.tool_calls:
            try:
                tool_input = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, AttributeError):
                tool_input = {}
            tool_calls.append(ToolCall(
                id=tc.id,
                name=tc.function.name,
                input=tool_input,
            ))

    return LLMResponse(
        content=message.content or "",
        stop_reason=stop_reason,
        tool_calls=tool_calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model=used_model,
        token_alert=token_alert,
        alert_message=alert_message,
    )


async def _get_stream_response_with_retry(
    request_kwargs: dict[str, Any],
    base_url: str | None,
    task_id: str | None,
) -> tuple[Any, str]:
    """获取流式 LLM 响应，支持重试和 fallback 模型切换。

    镜像 _execute_completion + _call_completion_with_retry 的逻辑，专为流式调用设计。
    只有在 litellm.acompletion() 建连阶段的错误才能重试；一旦开始迭代 chunk 出现的错误
    由调用方（chat_stream）捕获并上报，不在此处重试（避免重复推送内容）。
    """
    max_retries, base_delay, max_delay = _get_retry_config()
    primary_model = request_kwargs["model"]
    candidate_models = _get_model_candidates(primary_model, base_url)
    last_error: Exception | None = None

    for index, candidate_model in enumerate(candidate_models):
        model_kwargs = dict(request_kwargs)
        model_kwargs["model"] = candidate_model

        for attempt in range(max_retries + 1):
            try:
                async with _llm_semaphore:
                    response = await litellm.acompletion(
                        **model_kwargs,
                        request_timeout=LLM_CALL_TIMEOUT_S,
                    )
                if candidate_model != primary_model:
                    logger.warning(
                        "[LLM] stream fallback recovered: task=%s primary=%s fallback=%s",
                        task_id, primary_model, candidate_model,
                    )
                return response, candidate_model
            except Exception as error:
                last_error = error
                retriable = _is_retriable_llm_error(error)
                if attempt < max_retries and retriable:
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    logger.warning(
                        "[LLM] stream retry: task=%s model=%s attempt=%s/%s delay=%.1fs error=%s",
                        task_id, candidate_model, attempt + 1, max_retries + 1,
                        delay, _describe_error(error),
                    )
                    await asyncio.sleep(delay)
                    continue
                if index < len(candidate_models) - 1 and retriable:
                    logger.warning(
                        "[LLM] stream switching to fallback: task=%s failed=%s next=%s error=%s",
                        task_id, candidate_model, candidate_models[index + 1],
                        _describe_error(error),
                    )
                    break  # 跳出 attempt 循环，进入下一个候选模型
                raise last_error

    raise last_error or RuntimeError("LLM stream failed without error")


async def chat_stream(
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    task_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Streaming version of chat(). Yields chunks as they arrive.

    Yields dicts with type:
    - {"type": "content_delta", "content": str} -- incremental text
    - {"type": "tool_use", "tool_calls": [...]} -- tool call (final)
    - {"type": "done", "response": LLMResponse} -- final summary
    - {"type": "error", "error": str} -- on failure
    """
    resolved_model = model or _get_model()
    api_key = _get_api_key()
    base_url = _get_base_url()

    all_messages = _normalize_messages_for_provider(
        system=system,
        messages=messages,
        model=resolved_model,
        base_url=base_url,
    )

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": all_messages,
        "api_key": api_key,
        "stream": True,
    }
    if base_url:
        kwargs["api_base"] = base_url
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        response, resolved_model = await _get_stream_response_with_retry(
            request_kwargs=kwargs,
            base_url=base_url,
            task_id=task_id,
        )

        collected_content = ""
        collected_tool_calls: list[dict] = []
        finish_reason = None
        usage_info = {}

        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # Content streaming
            if delta.content:
                collected_content += delta.content
                yield {"type": "content_delta", "content": delta.content}

            # Tool call accumulation
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    while len(collected_tool_calls) <= idx:
                        collected_tool_calls.append({
                            "id": "", "name": "", "arguments": ""
                        })
                    if tc_delta.id:
                        collected_tool_calls[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            collected_tool_calls[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            collected_tool_calls[idx]["arguments"] += tc_delta.function.arguments

            # Finish reason
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            # Usage info (usually in the last chunk)
            if hasattr(chunk, "usage") and chunk.usage:
                usage_info = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(chunk.usage, "total_tokens", 0) or 0,
                }

        # Parse tool calls
        parsed_tool_calls: list[ToolCall] = []
        if collected_tool_calls:
            for tc in collected_tool_calls:
                if tc["name"]:
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    parsed_tool_calls.append(ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        input=args,
                    ))

        # Determine stop reason
        stop_reason = "end_turn"
        if parsed_tool_calls:
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"

        prompt_tokens = usage_info.get("prompt_tokens", 0)
        completion_tokens = usage_info.get("completion_tokens", 0)
        total_tokens = usage_info.get("total_tokens", 0)

        # Accumulate tokens
        if task_id:
            acc = _task_token_accumulator.setdefault(task_id, {
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "call_count": 0,
            })
            acc["prompt_tokens"] += prompt_tokens
            acc["completion_tokens"] += completion_tokens
            acc["total_tokens"] += total_tokens
            acc["call_count"] += 1

        final_response = LLMResponse(
            content=collected_content or "",
            stop_reason=stop_reason,
            tool_calls=parsed_tool_calls or [],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=resolved_model,
            token_alert=prompt_tokens > MODEL_CONTEXT_WINDOW * TOKEN_ALERT_RATIO if prompt_tokens else False,
            alert_message=(
                f"⚠️ Token 使用率已达 {prompt_tokens / MODEL_CONTEXT_WINDOW * 100:.0f}%"
                if prompt_tokens and prompt_tokens > MODEL_CONTEXT_WINDOW * TOKEN_ALERT_RATIO
                else ""
            ),
        )

        if parsed_tool_calls:
            yield {"type": "tool_use", "tool_calls": parsed_tool_calls}

        yield {"type": "done", "response": final_response}

    except Exception as e:
        logger.error(f"[LLM] Streaming error: {e}")
        yield {"type": "error", "error": str(e)}


def get_task_token_stats(task_id: str) -> dict[str, int]:
    """获取任务累计 Token 使用统计。"""
    return _task_token_accumulator.get(task_id, {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "call_count": 0,
    })
