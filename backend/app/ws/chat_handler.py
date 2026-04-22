"""
WebSocket 聊天处理器 — 主实时通信通道。
协议对齐需求文档 V3.1 §9。
负责:
  - 接收 ClientMessage
  - 创建 / 恢复 Task
  - 启动 agent_loop（作为独立 asyncio.Task 运行，使主循环始终可接收消息）
  - 流式推送 ServerMessage
  - 支持 abort 消息取消正在运行的 agent 任务
"""
import asyncio
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from collections import deque
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from starlette.websockets import WebSocketState
from typing import Any

from app.models.database import async_session
from app.models.tables import Task, TaskMessage, User
from app.core.agent_runner import agent_loop_v2 as agent_loop
from app.services.context_service import handle_compact_command
from app.services.webdeck_runtime.director import DeckDirector
from app.services.presentation_briefing_service import collect_task_attachments
from app.services.webdeck_runtime.state_store import deck_state_store

logger = logging.getLogger(__name__)

router = APIRouter()

# 默认用户 ID（一阶段不实现鉴权，使用固定用户）
DEFAULT_USER_ID = "default-user-00000000"

WS_SEND_TIMEOUT_SECONDS = 5.0
WS_RATE_LIMIT_MESSAGES = 5
WS_RATE_LIMIT_WINDOW_SECONDS = 10.0
WS_MAX_MESSAGE_LENGTH = 50000


class _RateLimiter:
    """Per-connection sliding-window rate limiter."""

    def __init__(self, max_messages: int = WS_RATE_LIMIT_MESSAGES, window_seconds: float = WS_RATE_LIMIT_WINDOW_SECONDS):
        self._max = max_messages
        self._window = window_seconds
        self._timestamps: deque[float] = deque()

    def check(self) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        # Evict expired timestamps
        while self._timestamps and now - self._timestamps[0] > self._window:
            self._timestamps.popleft()
        if len(self._timestamps) >= self._max:
            return False
        self._timestamps.append(now)
        return True


class _WebSocketSafeSender:
    """为长任务提供不会反向阻塞业务协程的 websocket 发送包装。"""

    _MAX_CONSECUTIVE_TIMEOUTS = 3

    def __init__(self, websocket: WebSocket, send_timeout_seconds: float = WS_SEND_TIMEOUT_SECONDS):
        self._websocket = websocket
        self._send_timeout_seconds = max(0.1, send_timeout_seconds)
        self._disabled = False
        self._consecutive_timeouts = 0

    async def send(self, msg: dict[str, Any]) -> None:
        if self._disabled:
            return
        if self._websocket.client_state != WebSocketState.CONNECTED:
            self._disabled = True
            return

        try:
            await asyncio.wait_for(
                self._websocket.send_json(msg),
                timeout=self._send_timeout_seconds,
            )
            # 成功发送 — 重置超时计数器
            self._consecutive_timeouts = 0
        except asyncio.TimeoutError:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= self._MAX_CONSECUTIVE_TIMEOUTS:
                self._disabled = True
                logger.warning(
                    "[WS] 连续 %d 次发送超时，后续实时消息将被丢弃: type=%s",
                    self._consecutive_timeouts,
                    msg.get("type"),
                )
            else:
                logger.warning(
                    "[WS] 发送消息超时 (%d/%d)，继续尝试: type=%s",
                    self._consecutive_timeouts,
                    self._MAX_CONSECUTIVE_TIMEOUTS,
                    msg.get("type"),
                )
        except Exception as e:
            self._disabled = True
            logger.warning(f"[WS] 发送消息失败，后续实时消息将被丢弃: {e}")

    def close(self) -> None:
        self._disabled = True


async def _ensure_default_user(session) -> str:
    """确保默认用户存在，返回 user_id。"""
    result = await session.execute(
        select(User).where(User.id == DEFAULT_USER_ID)
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            id=DEFAULT_USER_ID,
            name="默认用户",
            email="default@agent.local",
        )
        session.add(user)
        await session.commit()
        logger.info("[WS] 创建默认用户")
    return DEFAULT_USER_ID


async def _get_or_create_task(session, task_id: str | None, user_id: str) -> Task:
    """获取已有 Task 或创建新 Task。"""
    if task_id and task_id != "new":
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()
        if task:
            return task

    # 创建新任务
    new_task = Task(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="active",
        created_at=datetime.utcnow(),
    )
    session.add(new_task)
    await session.commit()
    logger.info(f"[WS] 创建新任务: {new_task.id}")
    return new_task


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    主 WebSocket 端点。

    客户端消息格式 (ClientMessage):
      {"type": "chat", "content": "...", "task_id": "..." | "new"}
      {"type": "abort"}                            — 取消当前运行中的 agent 任务
      {"type": "mode", "value": "direct" | "discuss"}
      {"type": "ping"}

    服务端消息格式 (ServerMessage):
      {"type": "message" | "thinking" | "status" | "error" | "processing_done" | ..., ...}

    架构: agent_loop 以 asyncio.Task 形式在后台运行，主循环始终可接收新消息
    （ping / abort / 新 chat 均能即时响应，不被 agent_loop 阻塞）。
    """
    await websocket.accept()
    logger.info("[WS] 连接已建立")

    active_runtime_tasks: dict[str, tuple[asyncio.Task, asyncio.Event]] = {}
    sender = _WebSocketSafeSender(websocket)
    rate_limiter = _RateLimiter()

    async def safe_send(msg: dict) -> None:
        """发送 JSON 消息，仅在连接存活时执行，异常仅记录日志。"""
        await sender.send(msg)

    def _runtime_key(task_id: str) -> str:
        return f"task:{task_id}"

    def _build_scoped_send(
        *,
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> Callable[[dict[str, Any]], Awaitable[None]]:
        async def _scoped_send(msg: dict[str, Any]) -> None:
            payload = dict(msg)
            if task_id and not payload.get("task_id"):
                payload["task_id"] = task_id
            if project_id and not payload.get("project_id"):
                payload["project_id"] = project_id
            await safe_send(payload)

        return _scoped_send

    async def _resolve_task_scope(requested_task_id: str | None) -> tuple[str, str, str | None, str]:
        async with async_session() as session:
            user_id = await _ensure_default_user(session)
            task = await _get_or_create_task(session, requested_task_id, user_id)
            return task.id, user_id, task.title, task.status

    async def _resolve_project_scope(project_id: str) -> tuple[str, str]:
        async with async_session() as session:
            project = await deck_state_store.get_project(session, project_id)
            if project is None or not project.task_id:
                raise ValueError("project_id 不存在或未绑定 task_id")
            return project.task_id, project.id

    # J3: 「开始生成」触发词检测 — 匹配用户想启动已规划 deck 的意图
    _PLAN_APPROVE_RE = re.compile(
        r"(开始生成|继续生成|生成ppt|生成幻灯片|生成deck|开始制作|开始吧|开始啊)",
        re.IGNORECASE,
    )
    # 仅对 ≤5 字的极短消息才检测单词触发（避免"帮我研究然后开始分析"等误匹配）
    _PLAN_APPROVE_SHORT = {"开始", "生成", "继续", "确认", "好的", "可以", "ok", "go", "start"}

    async def _try_trigger_plan_execution(
        task_id: str,
        user_message: str,
        send_fn: Callable[[dict], Awaitable[None]],
        model: str | None,
    ) -> bool:
        """
        J3: 若任务存在 plan_ready 或 failed(有 manifest) 状态的 deck
        且消息匹配「开始/继续生成」触发词，直接触发 execute_generation 而非路由给 agent。
        """
        msg = user_message.strip()

        # 触发词检测：明确关键词 OR 极短消息（≤5字）含启动词
        is_trigger = bool(_PLAN_APPROVE_RE.search(msg))
        if not is_trigger and len(msg) <= 5:
            is_trigger = any(t in msg.lower() for t in _PLAN_APPROVE_SHORT)
        if not is_trigger:
            return False

        # 查找当前任务可恢复的 deck 项目
        try:
            async with async_session() as session:
                project = await deck_state_store.get_project_by_task(session, task_id)
                if project is None:
                    return False

                project_id = project.id

                if project.status == "plan_ready":
                    # 原有逻辑：已规划等待确认
                    pass
                elif project.status == "failed" and project.manifest:
                    # 项目失败但有 manifest —— 重置非完成页面并重新执行
                    logger.info(
                        "[J3] 检测到 failed 项目(有 manifest)，重置页面状态准备重新执行: "
                        "task=%s project=%s",
                        task_id, project_id,
                    )
                    pages = await deck_state_store.get_pages(session, project_id)
                    for page in pages:
                        if page.status not in ("completed",):
                            await deck_state_store.update_page_status(
                                session, page.id, "pending"
                            )
                elif project.status == "generating":
                    # 正在生成中 —— 提示用户
                    await send_fn({
                        "type": "status",
                        "text": "⏳ 正在生成中，请稍候...",
                        "task_id": task_id,
                    })
                    return True
                else:
                    return False
        except Exception as _e:
            logger.warning(f"[J3] 查找可恢复项目失败: {_e}")
            return False

        logger.info(
            f"[J3] 检测到「开始/继续生成」触发词 + 可恢复 deck，自动触发执行:"
            f" task={task_id} project={project_id}"
        )
        await send_fn({
            "type": "status",
            "text": "收到确认，开始生成幻灯片页面...",
            "task_id": task_id,
        })
        await _cancel_runtime_task(task_id)
        abort_event = asyncio.Event()
        _track_runtime_task(
            task_id,
            _run_webdeck_generation_execution_task(
                task_id=task_id,
                project_id=project_id,
                model=model,
            ),
            abort_event,
        )
        return True

    def _track_runtime_task(
        task_id: str,
        coroutine: Awaitable[None],
        abort_signal: asyncio.Event,
    ) -> None:
        runtime_key = _runtime_key(task_id)
        running_task = asyncio.create_task(coroutine)
        active_runtime_tasks[runtime_key] = (running_task, abort_signal)

        def _cleanup(done_task: asyncio.Task) -> None:
            current = active_runtime_tasks.get(runtime_key)
            if current and current[0] is done_task:
                active_runtime_tasks.pop(runtime_key, None)

        running_task.add_done_callback(_cleanup)

    async def _cancel_runtime_task(task_id: str) -> None:
        runtime_key = _runtime_key(task_id)
        current = active_runtime_tasks.get(runtime_key)
        if not current:
            return
        running_task, abort_signal = current
        if running_task.done():
            active_runtime_tasks.pop(runtime_key, None)
            return
        abort_signal.set()
        running_task.cancel()
        try:
            await asyncio.wait({running_task}, timeout=2.0)
        except Exception:
            pass
        finally:
            active_runtime_tasks.pop(runtime_key, None)

    async def _cancel_all_runtime_tasks() -> None:
        task_ids = [key.split(":", 1)[1] for key in list(active_runtime_tasks.keys()) if key.startswith("task:")]
        for task_id in task_ids:
            await _cancel_runtime_task(task_id)

    async def _run_agent_task(
        content: str,
        task_id: str,
        user_id: str,
        model: str | None,
        local_abort_event: asyncio.Event,
    ) -> None:
        """在独立协程中运行 agent_loop，支持取消与清理。"""
        scoped_send = _build_scoped_send(task_id=task_id)
        async with async_session() as session:
            task = await _get_or_create_task(session, task_id, user_id)

            # Sprint 4: /compact 命令拦截
            if content.strip() == "/compact":
                try:
                    result = await handle_compact_command(
                        session=session,
                        task_id=task.id,
                        user_id=user_id,
                        send_fn=scoped_send,
                    )
                    await scoped_send({
                        "type": "message",
                        "role": "assistant",
                        "content": (
                            f"✅ 上下文压缩完成\n"
                            f"- 已压缩消息: {result.get('compressed', 0)} 条\n"
                            f"- 保留消息: {result.get('kept', 0)} 条\n"
                            f"- 摘要: {result.get('summary', '')}"
                        ),
                    })
                except Exception as e:
                    logger.exception(f"[WS] /compact 执行失败: {e}")
                    await scoped_send({
                        "type": "error",
                        "message": f"压缩失败: {str(e)}",
                        "recoverable": True,
                    })
                finally:
                    await scoped_send({"type": "processing_done"})
                return

            try:
                await agent_loop(
                    task=task,
                    user_message=content,
                    session=session,
                    send_fn=scoped_send,
                    model=model,
                )
            except asyncio.CancelledError:
                logger.info(f"[WS] Agent 任务已取消: task_id={task.id}")
                await scoped_send({"type": "status", "text": "✋ 任务已取消"})
                raise  # finally 会在此后执行
            except Exception as e:
                logger.exception(f"[WS] agent_loop 异常: {e}")
                await scoped_send({
                    "type": "error",
                    "message": f"处理消息时出错: {str(e)}",
                    "recoverable": True,
                })
            finally:
                await scoped_send({"type": "processing_done"})

    async def _run_webdeck_generate_task(
        brief: dict,
        task_id: str,
        user_id: str,
        model: str | None,
    ) -> None:
        scoped_send = _build_scoped_send(task_id=task_id)
        # 无论 brief 是否已含附件，始终从任务历史中自动合并（以 asset_id 去重）
        try:
            async with async_session() as session:
                auto_attachments = await collect_task_attachments(session, task_id, user_id)
                if auto_attachments:
                    existing_ids = {a.get("asset_id") for a in (brief.get("attachments") or []) if a.get("asset_id")}
                    new_ones = [a for a in auto_attachments if a.get("asset_id") not in existing_ids]
                    if new_ones:
                        brief["attachments"] = list(brief.get("attachments") or []) + new_ones
                        await scoped_send({
                            "type": "status",
                            "text": f"已自动关联 {len(new_ones)} 个对话附件到 Web Deck",
                        })
        except Exception as e:
            logger.warning(f"[WS] Auto-collect attachments failed: {e}")
        director = DeckDirector(send_fn=scoped_send, model=model)
        try:
            await director.run(
                brief=brief,
                task_id=task_id,
                user_id=user_id,
            )
        except asyncio.CancelledError:
            logger.info(f"[WS] WebDeck generate task cancelled: task_id={task_id}")
            await scoped_send({"type": "status", "text": "✋ Web Deck 生成已取消"})
            raise
        except Exception as e:
            logger.exception(f"[WS] webdeck_generate 异常: {e}")
            await scoped_send({
                "type": "error",
                "message": f"Web Deck 规划出错: {str(e)}",
                "recoverable": True,
            })
        finally:
            await scoped_send({"type": "processing_done"})

    async def _run_webdeck_generation_execution_task(
        task_id: str,
        project_id: str,
        model: str | None,
    ) -> None:
        scoped_send = _build_scoped_send(task_id=task_id, project_id=project_id)
        director = DeckDirector(send_fn=scoped_send, model=model)
        try:
            await director.execute_generation(project_id=project_id)
        except asyncio.CancelledError:
            logger.info(f"[WS] WebDeck generation execution cancelled: project_id={project_id}")
            await scoped_send({"type": "status", "text": "✋ Web Deck 生成已取消"})
            raise
        except Exception as e:
            logger.exception(f"[WS] webdeck_approve_plan 异常: {e}")
            await scoped_send({
                "type": "error",
                "message": f"Web Deck 生成失败: {str(e)}",
                "recoverable": True,
            })
        finally:
            await scoped_send({"type": "processing_done"})

    async def _run_webdeck_retry_page_task(
        task_id: str,
        project_id: str,
        page_id: str,
        model: str | None,
    ) -> None:
        scoped_send = _build_scoped_send(task_id=task_id, project_id=project_id)
        director = DeckDirector(send_fn=scoped_send, model=model)
        try:
            await director.retry_page(project_id=project_id, page_id=page_id)
        except asyncio.CancelledError:
            logger.info(f"[WS] WebDeck retry page cancelled: project_id={project_id} page_id={page_id}")
            await scoped_send({"type": "status", "text": "✋ 页面重试已取消"})
            raise
        except Exception as e:
            logger.exception(f"[WS] webdeck_retry_page 异常: {e}")
            await scoped_send({
                "type": "error",
                "message": f"页面重试失败: {str(e)}",
                "recoverable": True,
            })
        finally:
            await scoped_send({"type": "processing_done"})

    async def _run_webdeck_retry_lane_task(
        task_id: str,
        project_id: str,
        page_id: str,
        lane_id: str,
        model: str | None,
    ) -> None:
        scoped_send = _build_scoped_send(task_id=task_id, project_id=project_id)
        director = DeckDirector(send_fn=scoped_send, model=model)
        try:
            await director.retry_lane(project_id=project_id, page_id=page_id, lane_id=lane_id)
        except asyncio.CancelledError:
            logger.info(
                "[WS] WebDeck retry lane cancelled: project_id=%s page_id=%s lane_id=%s",
                project_id,
                page_id,
                lane_id,
            )
            await scoped_send({"type": "status", "text": "✋ Lane 重试已取消"})
            raise
        except Exception as e:
            logger.exception(f"[WS] webdeck_retry_lane 异常: {e}")
            await scoped_send({
                "type": "error",
                "message": f"Lane 重试失败: {str(e)}",
                "recoverable": True,
            })
        finally:
            await scoped_send({"type": "processing_done"})

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await safe_send({
                    "type": "error",
                    "message": "无效的 JSON 格式",
                    "recoverable": True,
                })
                continue

            msg_type = message.get("type", "")

            # 速率限制 (ping 免检)
            if msg_type != "ping" and not rate_limiter.check():
                await safe_send({
                    "type": "error",
                    "message": "请求过于频繁，请稍后再试",
                    "recoverable": True,
                })
                continue

            # 消息长度限制
            if msg_type == "chat":
                content_raw = message.get("content", "")
                if isinstance(content_raw, str) and len(content_raw) > WS_MAX_MESSAGE_LENGTH:
                    await safe_send({
                        "type": "error",
                        "message": f"消息内容过长（最大 {WS_MAX_MESSAGE_LENGTH} 字符），请缩短后重试",
                        "recoverable": True,
                    })
                    continue

            if msg_type == "chat":
                content = message.get("content", "").strip()
                if not content:
                    await safe_send({
                        "type": "error",
                        "message": "消息内容不能为空",
                        "recoverable": True,
                    })
                    continue

                requested_task_id = message.get("task_id")
                actual_task_id, user_id, title, status = await _resolve_task_scope(requested_task_id)
                await safe_send({
                    "type": "task_info",
                    "task_id": actual_task_id,
                    "title": title,
                    "status": status,
                })

                # J3: 若任务有 plan_ready deck 且消息是「开始生成」触发词，直接执行生成
                if await _try_trigger_plan_execution(
                    actual_task_id, content, safe_send, message.get("model")
                ):
                    continue

                await _cancel_runtime_task(actual_task_id)
                abort_event = asyncio.Event()
                _track_runtime_task(
                    actual_task_id,
                    _run_agent_task(
                        content=content,
                        task_id=actual_task_id,
                        user_id=user_id,
                        model=message.get("model"),
                        local_abort_event=abort_event,
                    ),
                    abort_event,
                )

            elif msg_type == "webdeck_generate":
                brief = message.get("brief")
                if not isinstance(brief, dict) or not str(brief.get("topic") or "").strip():
                    await safe_send({
                        "type": "error",
                        "message": "Web Deck 生成缺少 topic",
                        "recoverable": True,
                    })
                    continue

                actual_task_id, user_id, title, status = await _resolve_task_scope(message.get("task_id"))
                await safe_send({
                    "type": "task_info",
                    "task_id": actual_task_id,
                    "title": title,
                    "status": status,
                })

                await _cancel_runtime_task(actual_task_id)
                abort_event = asyncio.Event()
                _track_runtime_task(
                    actual_task_id,
                    _run_webdeck_generate_task(
                        brief=brief,
                        task_id=actual_task_id,
                        user_id=user_id,
                        model=message.get("model"),
                    ),
                    abort_event,
                )

            elif msg_type == "webdeck_approve_plan":
                project_id = str(message.get("project_id") or "").strip()
                if not project_id:
                    await safe_send({
                        "type": "error",
                        "message": "缺少 project_id",
                        "recoverable": True,
                    })
                    continue

                resolved_task_id, resolved_project_id = await _resolve_project_scope(project_id)
                await _cancel_runtime_task(resolved_task_id)
                abort_event = asyncio.Event()
                _track_runtime_task(
                    resolved_task_id,
                    _run_webdeck_generation_execution_task(
                        task_id=resolved_task_id,
                        project_id=resolved_project_id,
                        model=message.get("model"),
                    ),
                    abort_event,
                )

            elif msg_type == "webdeck_retry_page":
                project_id = str(message.get("project_id") or "").strip()
                page_id = str(message.get("page_id") or "").strip()
                if not project_id or not page_id:
                    await safe_send({
                        "type": "error",
                        "message": "缺少 project_id 或 page_id",
                        "recoverable": True,
                    })
                    continue

                resolved_task_id, resolved_project_id = await _resolve_project_scope(project_id)
                # 使用 page 级别的 key 跟踪重试任务，避免多页并行重试互相取消
                retry_key = f"{resolved_task_id}:retry:{page_id}"
                await _cancel_runtime_task(retry_key)
                abort_event = asyncio.Event()
                _track_runtime_task(
                    retry_key,
                    _run_webdeck_retry_page_task(
                        task_id=resolved_task_id,
                        project_id=resolved_project_id,
                        page_id=page_id,
                        model=message.get("model"),
                    ),
                    abort_event,
                )

            elif msg_type == "webdeck_retry_lane":
                project_id = str(message.get("project_id") or "").strip()
                page_id = str(message.get("page_id") or "").strip()
                lane_id = str(message.get("lane_id") or "").strip()
                if not project_id or not page_id or not lane_id:
                    await safe_send({
                        "type": "error",
                        "message": "缺少 project_id、page_id 或 lane_id",
                        "recoverable": True,
                    })
                    continue

                resolved_task_id, resolved_project_id = await _resolve_project_scope(project_id)
                # 使用 lane 级别的 key 跟踪重试任务，避免多 lane 并行重试互相取消
                retry_key = f"{resolved_task_id}:retry:{page_id}:{lane_id}"
                await _cancel_runtime_task(retry_key)
                abort_event = asyncio.Event()
                _track_runtime_task(
                    retry_key,
                    _run_webdeck_retry_lane_task(
                        task_id=resolved_task_id,
                        project_id=resolved_project_id,
                        page_id=page_id,
                        lane_id=lane_id,
                        model=message.get("model"),
                    ),
                    abort_event,
                )

            elif msg_type == "abort":
                task_id = str(message.get("task_id") or "").strip()
                if task_id and task_id != "new":
                    await _cancel_runtime_task(task_id)
                    await safe_send({"type": "processing_done", "task_id": task_id})
                else:
                    await _cancel_all_runtime_tasks()
                    await safe_send({"type": "processing_done"})

            elif msg_type == "mode":
                mode = message.get("value", "direct")
                await safe_send({
                    "type": "status",
                    "text": f"模式已切换为: {'直接生成' if mode == 'direct' else '先讨论'}",
                })

            elif msg_type == "ping":
                await safe_send({"type": "pong"})

            else:
                await safe_send({
                    "type": "error",
                    "message": f"未知消息类型: {msg_type}",
                    "recoverable": True,
                })

    except WebSocketDisconnect:
        sender.close()
        logger.info("[WS] 连接断开")
    except Exception as e:
        sender.close()
        logger.exception(f"[WS] 未预期错误: {e}")
    finally:
        sender.close()
        await _cancel_all_runtime_tasks()
        logger.info("[WS] 连接处理完毕")
