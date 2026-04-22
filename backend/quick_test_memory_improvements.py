"""记忆与上下文改进验证脚本。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace

from app.core.agent_loop import _auto_capture_memories
from app.core.llm_client import LLMResponse, ToolCall
from app.core.tool_dispatch import auto_discover_tools, get_tool_names
from app.models.database import async_session, init_db
from app.models.tables import Task, TaskMessage
from app.services.context_service import (
    _build_messages,
    _flush_memories_before_compaction,
    assemble_context,
)
from app.services.memory_service import clear_user_memories, capture_memory, list_user_memories
from app.services.user_settings_service import ensure_user, update_user_settings

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(name: str, detail: str = "") -> None:
    print(f"{GREEN}✓{RESET} {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = "") -> None:
    raise AssertionError(f"{name}: {detail}")


async def run() -> None:
    print(f"{YELLOW}═══ Memory / Context Improvements 验证 ═══{RESET}")
    await init_db()

    user_id = f"test-user-{uuid.uuid4().hex[:8]}"
    task_id = f"task-{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        await ensure_user(session, user_id=user_id, name="Memory Test User")
        await clear_user_memories(session, user_id)

        task = Task(
            id=task_id,
            user_id=user_id,
            title="memory test",
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(task)
        await session.commit()

        async def fake_send(_: dict) -> None:
            return None

        # 1. fact 默认不开启自动捕获
        await update_user_settings(
            session,
            {
                "memory": {
                    "auto_capture": {
                        "preference": True,
                        "instruction": True,
                        "fact": False,
                    }
                }
            },
            user_id,
        )
        await _auto_capture_memories(
            session,
            user_id,
            "我是量化研究平台主管",
            task_id,
            fake_send,
        )
        memories = await list_user_memories(session, user_id)
        if memories:
            fail("fact 默认开关", "fact 关闭时仍被自动捕获")
        ok("fact 默认不开启自动捕获")

        # 2. 打开 fact 后允许自动捕获
        await update_user_settings(
            session,
            {"memory": {"auto_capture": {"fact": True}}},
            user_id,
        )
        await _auto_capture_memories(
            session,
            user_id,
            "我是量化研究平台主管",
            task_id,
            fake_send,
        )
        memories = await list_user_memories(session, user_id)
        if not any(mem["category"] == "fact" for mem in memories):
            fail("fact 自动捕获", "fact 打开后未捕获事实记忆")
        ok("fact 开启后可自动捕获")

        # 3. 相关记忆召回替代全量注入
        await capture_memory(
            session,
            user_id,
            "instruction",
            "所有 PPT 默认使用中文输出",
            source="user_explicit",
            task_id=task_id,
            confidence=1.0,
        )
        await capture_memory(
            session,
            user_id,
            "preference",
            "偏好深色科技风格",
            source="user_explicit",
            task_id=task_id,
            confidence=1.0,
        )
        await capture_memory(
            session,
            user_id,
            "feedback",
            "中文输出时避免英文标题",
            source="user_explicit",
            task_id=task_id,
            confidence=0.9,
        )
        for index in range(8):
            await capture_memory(
                session,
                user_id,
                "feedback",
                f"feedback-{index}",
                source="user_explicit",
                task_id=task_id,
                confidence=0.7,
            )

        user_msg = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=task_id,
            role="user",
            content="请继续按中文输出规范帮我做一份 PPT",
            msg_type="text",
            created_at=datetime.utcnow(),
        )
        session.add(user_msg)
        await session.commit()

        system_prompt, _, _ = await assemble_context(
            session=session,
            task_id=task_id,
            user_id=user_id,
            base_prompt="你是测试助手",
        )
        if "所有 PPT 默认使用中文输出" not in system_prompt:
            fail("相关记忆召回", "没有召回与当前请求相关的记忆")
        if "中文输出时避免英文标题" not in system_prompt:
            fail("相关记忆召回", "没有注入与当前请求匹配的反馈类长期记忆")
        if "feedback-7" in system_prompt:
            fail("全量记忆注入", "无关记忆仍被全量注入到系统提示词")
        ok("只注入相关长期记忆，不再全量塞入")

        # 4. 微压缩: 旧 tool_result 被截断，最近消息保留完整
        long_text = "x" * 600
        history = [
            SimpleNamespace(
                id=str(i),
                role="tool",
                content=long_text,
                msg_type="tool_result",
                tool_name="web_search",
                tool_input={"_tool_call_id": f"call-{i}"},
            )
            for i in range(2)
        ]
        history.extend(
            SimpleNamespace(
                id=f"m-{i}",
                role="user",
                content=f"msg-{i}",
                msg_type="text",
                tool_name=None,
                tool_input=None,
            )
            for i in range(8)
        )
        history.append(
            SimpleNamespace(
                id="recent-tool",
                role="tool",
                content=long_text,
                msg_type="tool_result",
                tool_name="parse_document",
                tool_input={"_tool_call_id": "call-recent"},
            )
        )
        history.append(
            SimpleNamespace(
                id="recent-user",
                role="user",
                content="最后一条消息",
                msg_type="text",
                tool_name=None,
                tool_input=None,
            )
        )
        built_messages = _build_messages(history)
        if not built_messages[0]["content"].endswith("...已截断"):
            fail("微压缩", "旧 tool_result 未被截断")
        if built_messages[-2]["content"] != long_text:
            fail("微压缩", "最近 tool_result 不应被截断")
        ok("旧 tool_result 会微压缩，最近消息保持完整")

        # 5. 压缩前刷盘 + 工具注册
        auto_discover_tools()
        tool_names = get_tool_names()
        if "save_to_memory" not in tool_names or "search_memory" not in tool_names:
            fail("记忆工具注册", f"当前工具列表: {tool_names}")
        ok("记忆工具已注册", ", ".join(sorted(name for name in tool_names if "memory" in name)))

        await clear_user_memories(session, user_id)

        import app.core.llm_client as llm_client_module

        original_chat = llm_client_module.chat

        async def fake_chat(**_: object) -> LLMResponse:
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="call-save-memory",
                        name="save_to_memory",
                        input={
                            "category": "instruction",
                            "content": "以后默认使用中文输出",
                            "confidence": 0.95,
                        },
                    )
                ]
            )

        llm_client_module.chat = fake_chat
        try:
            flushed = await _flush_memories_before_compaction(
                session=session,
                user_id=user_id,
                messages=[
                    SimpleNamespace(
                        role="user",
                        content="以后默认使用中文输出",
                        tool_name=None,
                    )
                ],
                task_id=task_id,
            )
        finally:
            llm_client_module.chat = original_chat

        memories = await list_user_memories(session, user_id)
        if flushed != 1 or not any("中文输出" in mem["content"] for mem in memories):
            fail("压缩前刷盘", f"flushed={flushed}, memories={memories}")
        ok("压缩前会通过 save_to_memory 工具刷盘重要记忆")

    print(f"{GREEN}所有验证通过{RESET}")


if __name__ == "__main__":
    asyncio.run(run())