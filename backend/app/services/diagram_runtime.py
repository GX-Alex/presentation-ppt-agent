from __future__ import annotations

import contextvars
from collections.abc import Awaitable, Callable
from typing import Any


_send_fn_var: contextvars.ContextVar[Callable[[dict[str, Any]], Awaitable[None]] | None] = contextvars.ContextVar(
    "diagram_send_fn",
    default=None,
)
_task_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("diagram_task_id", default=None)
_user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("diagram_user_id", default=None)


def set_runtime_context(
    send_fn: Callable[[dict[str, Any]], Awaitable[None]] | None,
    task_id: str | None,
    user_id: str | None,
) -> None:
    _send_fn_var.set(send_fn)
    _task_id_var.set(task_id)
    _user_id_var.set(user_id)


def get_runtime_task_id() -> str | None:
    return _task_id_var.get(None)


def get_runtime_user_id() -> str | None:
    return _user_id_var.get(None)


async def emit_runtime_event(payload: dict[str, Any]) -> None:
    send_fn = _send_fn_var.get(None)
    if send_fn is None:
        return
    message = dict(payload)
    task_id = _task_id_var.get(None)
    if task_id and not message.get("task_id"):
        message["task_id"] = task_id
    await send_fn(message)