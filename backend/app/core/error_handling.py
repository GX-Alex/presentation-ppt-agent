"""
全局错误处理中间件 — Sprint 7。
职责: 统一异常捕获、超时控制、请求重试逻辑、错误日志记录。
"""
import asyncio
import logging
import time
import traceback
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

# ──────────────── 自定义异常 ────────────────


class AppError(Exception):
    """应用层业务异常基类。"""
    def __init__(self, message: str, status_code: int = 400, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class TimeoutError(AppError):
    """请求超时异常。"""
    def __init__(self, message: str = "请求处理超时", timeout: float = 0):
        super().__init__(message, status_code=504)
        self.timeout = timeout


class RateLimitError(AppError):
    """速率限制异常。"""
    def __init__(self, message: str = "请求过于频繁，请稍后再试"):
        super().__init__(message, status_code=429)


class LLMError(AppError):
    """LLM 调用异常。"""
    def __init__(self, message: str = "AI 模型调用失败", detail: str | None = None):
        super().__init__(message, status_code=502, detail=detail)


# ──────────────── 请求超时中间件 ────────────────

# 默认请求超时（秒）— 长请求如 PPT 生成可能需要较长时间
DEFAULT_REQUEST_TIMEOUT = 300  # 5 分钟
# 慢请求日志阈值（秒）
SLOW_REQUEST_THRESHOLD = 10


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """
    请求超时中间件 — 对非 WebSocket 请求添加超时控制。
    超时后返回 504 Gateway Timeout。
    """

    def __init__(self, app, timeout: float = DEFAULT_REQUEST_TIMEOUT):
        super().__init__(app)
        self.timeout = timeout

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # WebSocket 不加超时
        if request.scope.get("type") == "websocket":
            return await call_next(request)

        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                call_next(request),
                timeout=self.timeout,
            )
            # 慢请求日志
            elapsed = time.monotonic() - start
            if elapsed > SLOW_REQUEST_THRESHOLD:
                logger.warning(
                    f"[慢请求] {request.method} {request.url.path} "
                    f"耗时 {elapsed:.2f}s"
                )
            return response
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            logger.error(
                f"[超时] {request.method} {request.url.path} "
                f"超过 {self.timeout}s 超时限制"
            )
            return JSONResponse(
                status_code=504,
                content={
                    "error": "请求处理超时",
                    "detail": f"请求在 {self.timeout} 秒内未完成",
                    "path": request.url.path,
                    "suggestion": "请稍后重试，如果问题持续存在请联系管理员",
                },
            )


# ──────────────── 全局异常处理中间件 ────────────────


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    全局异常处理中间件 — 捕获所有未处理异常，返回标准化错误响应。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except AppError as e:
            # 业务异常 — 返回对应状态码
            logger.warning(
                f"[业务异常] {request.method} {request.url.path}: "
                f"{e.message} (status={e.status_code})"
            )
            return JSONResponse(
                status_code=e.status_code,
                content={
                    "error": e.message,
                    "detail": e.detail,
                    "path": request.url.path,
                    "suggestion": _get_error_suggestion(e.status_code, e.message),
                },
            )
        except Exception as e:
            # 未预期异常 — 500 + 详细日志
            logger.exception(
                f"[未预期异常] {request.method} {request.url.path}: {e}"
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "服务器内部错误",
                    "detail": str(e) if logger.isEnabledFor(logging.DEBUG) else None,
                    "path": request.url.path,
                    "suggestion": "请稍后重试，如果问题持续存在请联系管理员",
                },
            )


def _get_error_suggestion(status_code: int, _message: str = "") -> str | None:
    """根据错误状态码返回用户友好的建议"""
    suggestions = {
        400: "请检查输入是否正确",
        401: "请重新登录",
        403: "您没有权限执行此操作",
        404: "请求的资源不存在",
        429: "请求过于频繁，请稍后再试",
        500: "服务器内部错误，请稍后重试",
        502: "AI 服务暂时不可用，请稍后重试",
        503: "服务暂时不可用，请稍后重试",
        504: "请求处理超时，请稍后重试",
    }
    return suggestions.get(status_code)


# ──────────────── LLM 重试装饰器 ────────────────

async def retry_llm_call(
    func: Callable,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    **kwargs,
):
    """
    LLM 调用重试逻辑 — 指数退避重试。

    Args:
        func: 要重试的异步函数
        max_retries: 最大重试次数
        base_delay: 初始重试间隔（秒）
        max_delay: 最大重试间隔（秒）

    Returns:
        函数返回值

    Raises:
        LLMError: 重试耗尽后抛出
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"[LLM 重试] 第 {attempt + 1} 次失败: {e}, "
                    f"{delay:.1f}s 后重试..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[LLM 重试] 全部 {max_retries + 1} 次尝试失败: {e}"
                )

    raise LLMError(
        message="AI 模型调用多次重试后仍然失败",
        detail=str(last_error),
    )


# ──────────────── WebSocket 错误推送工具 ────────────────

async def ws_error_push(
    send_fn: Callable,
    error: Exception,
    recoverable: bool = True,
    context: str = "",
) -> None:
    """
    向 WebSocket 客户端推送结构化错误消息。

    Args:
        send_fn: WebSocket 消息发送回调
        error: 异常对象
        recoverable: 是否可恢复（客户端据此决定是否重试）
        context: 错误上下文描述
    """
    error_type = type(error).__name__
    message = str(error)

    # 根据异常类型决定用户友好的提示
    if isinstance(error, LLMError):
        user_message = f"AI 模型暂时不可用: {error.message}"
    elif isinstance(error, TimeoutError):
        user_message = f"处理超时: {error.message}"
    elif isinstance(error, RateLimitError):
        user_message = error.message
    else:
        user_message = f"处理出错: {message}" if recoverable else "服务暂时不可用，请稍后再试"

    try:
        await send_fn({
            "type": "error",
            "message": user_message,
            "error_type": error_type,
            "recoverable": recoverable,
            "context": context,
        })
    except Exception as e:
        logger.warning(f"[WS] 发送错误消息失败: {e}")
