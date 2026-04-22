"""
上下文服务 — Layer 0 上下文组装 + 压缩 + /compact 命令。
Sprint 4: 负责将系统提示词、Skill 菜单、用户 Skill、用户记忆、
对话历史统一组装为 LLM 输入上下文。当 Token 占用超过阈值时触发压缩。

阈值:
  - 70% 模型上下文窗口: 触发自动压缩
  - 85%: llm_client 层发出告警
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

import tiktoken

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import TaskMessage

logger = logging.getLogger(__name__)


def _detect_model_context_window() -> int:
    """按活跃模型推断上下文窗口大小；优先尊重 MODEL_CONTEXT_WINDOW 环境变量。"""
    explicit = os.getenv("MODEL_CONTEXT_WINDOW")
    if explicit:
        return int(explicit)
    model = os.getenv("LLM_MODEL", "").lower()
    # 按模型系列映射 — 保守估计，宁小勿大
    _WINDOWS: list[tuple[str, int]] = [
        ("minimax-m2", 32768),        # MiniMax M2.x — 32K 实测安全范围
        ("minimax/minimax-01", 1048576),
        ("minimax-01", 1048576),
        ("deepseek", 131072),
        ("gpt-4o", 131072),
        ("claude", 200000),
        ("qwen", 32768),
        ("gemini", 131072),
    ]
    for key, window in _WINDOWS:
        if key in model:
            return window
    return 128000  # 保守默认


# 模型上下文窗口（动态按模型推断，可用 MODEL_CONTEXT_WINDOW 环境变量覆盖）
MODEL_CONTEXT_WINDOW = _detect_model_context_window()

# 压缩阈值: 当消息 Token 数占模型窗口的 70% 时触发
COMPRESS_RATIO = float(os.getenv("COMPRESS_RATIO", "0.70"))
COMPRESS_THRESHOLD = int(MODEL_CONTEXT_WINDOW * COMPRESS_RATIO)
RECENT_MESSAGES_WINDOW = 10
OLD_TOOL_RESULT_CHAR_LIMIT = 500
MEMORY_RECALL_TOP_K = 5

# ────────────── 智能截断: 按工具类型区分保留长度 ──────────────
# 小上下文模型（< 128K）缩减至 50%，保底保证分析质量；大上下文使用完整限制
_CONTEXT_SCALE = max(0.5, min(1.0, MODEL_CONTEXT_WINDOW / 128000))
TOOL_RESULT_CHAR_LIMITS: dict[str, int] = {
    "web_search":        int(1500 * _CONTEXT_SCALE),   # 32K→750, 128K→1500
    "fetch_url":         int(1500 * _CONTEXT_SCALE),
    "parse_document":    int(2000 * _CONTEXT_SCALE),   # 32K→1000
    "parse_project":     int(1200 * _CONTEXT_SCALE),   # 32K→600
    "read_project_file": int(800  * _CONTEXT_SCALE),   # 32K→400，代码截短更积极
    "search_memory":     int(800  * _CONTEXT_SCALE),
    "image_search":      400,
    "save_to_memory":    200,
    "load_skill":        400,
}

# ────────────── 消息重要性评分参数 ──────────────
# 角色基础分: 不同角色消息的固有重要性
_ROLE_BASE_SCORES: dict[str, float] = {
    "user": 0.9,        # 用户消息始终高优先级
    "assistant": 0.7,   # 助手回复中等偏高
    "tool": 0.4,        # 工具结果默认中等偏低
    "system": 1.0,      # 系统消息（如摘要）始终保留
}
# 高价值工具结果额外加分
_HIGH_VALUE_TOOLS: set[str] = {"web_search", "fetch_url", "parse_document", "parse_project", "read_project_file"}
_HIGH_VALUE_TOOL_BONUS = 0.3
# 位置衰减: 越旧的消息重要性越低（线性衰减，最低保底 0.1）
_POSITION_DECAY_WEIGHT = 0.2
MEMORY_RECALL_THRESHOLD = 0.3
PREFLUSH_MAX_TOOL_CALLS = 5

# tiktoken 编码器（延迟初始化）
_tokenizer = None


def _get_tokenizer():
    """获取 tiktoken 编码器（延迟加载，兼容 DeepSeek）。"""
    global _tokenizer
    if _tokenizer is None:
        try:
            # DeepSeek 使用 cl100k_base 编码
            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception as e:
            logger.warning(f"[Context] tiktoken 加载失败: {e}")
    return _tokenizer


def count_tokens(text: str) -> int:
    """计算文本的 Token 数量。"""
    enc = _get_tokenizer()
    if enc is None:
        # 回退: 按字符数粗略估算（中文约 1.5 Token/字）
        return int(len(text) * 1.5)
    return len(enc.encode(text))


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """计算消息列表的总 Token 数量。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += count_tokens(content)
        # tool_calls 也计入
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += count_tokens(json.dumps(tool_calls, ensure_ascii=False))
        # 角色名等额外开销（每条消息约 4 Token）
        total += 4
    return total


async def assemble_system_prompt(
    session: AsyncSession,
    user_id: str,
    base_prompt: str,
    *,
    task_id: str | None = None,
    memory_query: str | None = None,
) -> str:
    """
    组装完整系统提示词（Layer 0）。
    将基础提示词 + Skill 菜单 + 已启用的用户 Skill + 用户记忆整合。

    Args:
        session: 数据库会话
        user_id: 当前用户 ID
        base_prompt: 基础系统提示词

    Returns:
        完整的系统提示词文本
    """
    parts = [base_prompt]

    # 1. 注入 Skill 菜单（可用的系统 Skill 列表）
    try:
        from app.services.skill_service import get_skill_menu
        menu = get_skill_menu()
        if menu:
            parts.append(f"\n\n{menu}")
    except Exception as e:
        logger.warning(f"[Context] 加载 Skill 菜单失败: {e}")

    # 2. 注入已启用的用户自定义 Skill
    try:
        from app.services.skill_service import get_enabled_user_skills
        user_skills = await get_enabled_user_skills(session, user_id)
        if user_skills:
            parts.append("\n\n## 已加载的自定义 Skill")
            for skill in user_skills:
                parts.append(
                    f"\n### {skill['display_name']} ({skill['name']})\n"
                    f"{skill.get('body', '')}"
                )
    except Exception as e:
        logger.warning(f"[Context] 加载用户 Skill 失败: {e}")

    # 3. 注入用户画像 + 相关长期记忆
    try:
        from app.services.memory_service import (
            get_latest_checkpoint,
            get_memory_count,
            list_user_memories,
            search_memories,
        )
        from app.services.user_settings_service import get_user_settings, is_memory_enabled

        settings = await get_user_settings(session, user_id)
        if is_memory_enabled(settings):
            mem_count = await get_memory_count(session, user_id)
            if mem_count > 0:
                memories = await list_user_memories(session, user_id, task_id=task_id)
                profile_memories = _select_profile_memories(memories)
                if profile_memories:
                    parts.append("\n\n<user_profile>")
                    for mem in profile_memories:
                        category_label = {
                            "preference": "偏好",
                            "fact": "事实",
                            "instruction": "指令",
                            "feedback": "反馈",
                        }.get(mem["category"], mem["category"])
                        parts.append(f"- [{category_label}] {mem['content']}")
                    parts.append("</user_profile>")

                if memory_query:
                    related_memories = await search_memories(
                        session,
                        user_id,
                        memory_query,
                        top_k=MEMORY_RECALL_TOP_K,
                        threshold=MEMORY_RECALL_THRESHOLD,
                        task_id=task_id,
                    )
                    profile_ids = {mem["id"] for mem in profile_memories}
                    related_memories = [
                        mem for mem in related_memories if mem["id"] not in profile_ids
                    ]
                    if related_memories:
                        parts.append("\n\n<user_context>")
                        for mem in related_memories:
                            parts.append(
                                f"- [{mem['category']}] {mem['content']}"
                            )
                        parts.append("</user_context>")

        if task_id:
            checkpoint = await get_latest_checkpoint(session, task_id)
            if checkpoint and checkpoint.get("summary"):
                parts.append(
                    "\n\n<task_context>\n"
                    f"{checkpoint['summary'][:600]}\n"
                    "</task_context>"
                )
    except Exception as e:
        logger.warning(f"[Context] 加载用户记忆失败: {e}")

    return "\n".join(parts)


async def assemble_context(
    session: AsyncSession,
    task_id: str,
    user_id: str,
    base_prompt: str,
) -> tuple[str, list[dict[str, Any]], bool]:
    """
    组装完整的 LLM 输入上下文（系统提示词 + 消息列表）。
    如果 Token 超过压缩阈值，自动触发压缩。

    Args:
        session: 数据库会话
        task_id: 当前任务 ID
        user_id: 当前用户 ID
        base_prompt: 基础系统提示词

    Returns:
        (system_prompt, messages, needs_compress):
          - system_prompt: 完整系统提示词
          - messages: 构建好的消息列表
          - needs_compress: 是否需要压缩
    """
    # 1. 加载对话历史
    stmt = (
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.is_compressed == False)  # noqa: E712
        .order_by(TaskMessage.created_at.asc())
        .limit(80)
    )
    result = await session.execute(stmt)
    history = result.scalars().all()

    # 2. 构建消息列表（含微压缩）
    messages = _build_messages(history)
    msg_tokens = count_messages_tokens(messages)

    # 3. 基于最新用户消息召回相关长期记忆
    memory_query = _get_latest_user_message(history)

    # 4. 组装系统提示词
    system_prompt = await assemble_system_prompt(
        session,
        user_id,
        base_prompt,
        task_id=task_id,
        memory_query=memory_query,
    )
    system_tokens = count_tokens(system_prompt)

    total_tokens = system_tokens + msg_tokens
    needs_compress = total_tokens >= COMPRESS_THRESHOLD

    logger.info(
        f"[Context] task={task_id} "
        f"system_tokens={system_tokens} msg_tokens={msg_tokens} "
        f"total={total_tokens} threshold={COMPRESS_THRESHOLD} "
        f"compress={'YES' if needs_compress else 'no'}"
    )

    return system_prompt, messages, needs_compress


async def compress_context(
    session: AsyncSession,
    task_id: str,
    user_id: str,
    send_fn=None,
) -> dict[str, Any]:
    """
    压缩对话上下文 — 将旧消息摘要化 + 关键信息写入记忆。

    流程:
    1. 加载所有未压缩消息
    2. 保留最近 10 条消息不压缩
    3. 使用 LLM 对旧消息进行摘要
    4. 将摘要存为系统消息
    5. 标记旧消息为 is_compressed=True
    6. 从旧消息中提取关键信息写入用户记忆

    Returns:
        压缩结果统计
    """
    import uuid

    # 1. 加载未压缩消息
    stmt = (
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.is_compressed == False)  # noqa: E712
        .order_by(TaskMessage.created_at.asc())
    )
    result = await session.execute(stmt)
    all_msgs = result.scalars().all()

    if len(all_msgs) <= 10:
        return {"compressed": 0, "kept": len(all_msgs), "summary": "消息数过少，无需压缩"}

    # 2. 分割: 旧消息（压缩）+ 新消息（保留）
    old_msgs = all_msgs[:-RECENT_MESSAGES_WINDOW]
    kept_count = RECENT_MESSAGES_WINDOW

    # 2.1 压缩前记忆刷盘
    flushed_memories = await _flush_memories_before_compaction(
        session=session,
        user_id=user_id,
        messages=old_msgs,
        task_id=task_id,
    )

    # 3. 构建旧消息的摘要输入
    summary_text = _build_summary_input(old_msgs)

    # 4. 使用 LLM 生成摘要
    summary = await _generate_summary(summary_text, task_id)

    # 5. 将摘要存为系统消息
    summary_msg = TaskMessage(
        id=str(uuid.uuid4()),
        task_id=task_id,
        role="system",
        content=f"[对话摘要]\n{summary}",
        msg_type="summary",
        created_at=datetime.utcnow(),
    )
    session.add(summary_msg)

    # 6. 标记旧消息为已压缩
    old_ids = [m.id for m in old_msgs]
    await session.execute(
        update(TaskMessage)
        .where(TaskMessage.id.in_(old_ids))
        .values(is_compressed=True)
    )

    await session.commit()

    # 7. 从旧消息中自动提取记忆
    await _extract_memories_from_compressed(session, user_id, old_msgs, task_id)

    result_info = {
        "compressed": len(old_ids),
        "kept": kept_count,
        "flushed_memories": flushed_memories,
        "summary_length": len(summary),
        "summary": summary[:200] + "..." if len(summary) > 200 else summary,
    }

    logger.info(
        f"[Context] 压缩完成: task={task_id} "
        f"compressed={len(old_ids)} kept={kept_count}"
    )

    # 通知前端
    if send_fn:
        await send_fn({
            "type": "compact_done",
            "task_id": task_id,
            "compressed_count": len(old_ids),
            "kept_count": kept_count,
        })

    return result_info


async def handle_compact_command(
    session: AsyncSession,
    task_id: str,
    user_id: str,
    send_fn=None,
) -> dict[str, Any]:
    """
    处理 /compact 命令 — 用户主动触发上下文压缩。

    Returns:
        压缩结果
    """
    if send_fn:
        await send_fn({
            "type": "status",
            "text": "正在压缩对话上下文...",
            "task_id": task_id,
        })

    result = await compress_context(session, task_id, user_id, send_fn)

    return result


async def _generate_summary(text: str, task_id: str) -> str:
    """使用 LLM 生成对话摘要。"""
    try:
        from app.core.llm_client import chat as llm_chat

        summary_prompt = (
            "请将以下对话历史压缩为简洁摘要，保留关键信息（决策、结论、待办事项）。"
            "用中文回复，100-300字。\n\n"
        )

        response = await llm_chat(
            system=summary_prompt,
            messages=[{"role": "user", "content": text[:8000]}],  # 限制输入长度
            tools=None,
            task_id=task_id,
        )
        return response.content.strip() or "（摘要生成失败）"
    except Exception as e:
        logger.error(f"[Context] 摘要生成失败: {e}")
        # 回退: 简单截断
        return text[:500] + "\n...(已自动截断)"


async def _extract_memories_from_compressed(
    session: AsyncSession,
    user_id: str,
    messages: list,
    task_id: str,
) -> None:
    """从被压缩的消息中提取可能的记忆信号并保存。"""
    try:
        from app.services.memory_service import detect_memory_signals, capture_memory
        from app.services.user_settings_service import (
            get_user_settings,
            is_auto_memory_capture_enabled,
            is_memory_enabled,
        )

        settings = await get_user_settings(session, user_id)
        if not is_memory_enabled(settings):
            return

        for msg in messages:
            if msg.role != "user" or not msg.content:
                continue
            signals = detect_memory_signals(msg.content)
            for signal in signals:
                if not is_auto_memory_capture_enabled(settings, signal["category"]):
                    continue
                await capture_memory(
                    session=session,
                    user_id=user_id,
                    category=signal["category"],
                    content=signal["content"],
                    source="compress_extracted",
                    task_id=task_id,
                    confidence=0.6,
                )
    except Exception as e:
        logger.warning(f"[Context] 压缩记忆提取失败: {e}")


def _build_messages(history: list) -> list[dict[str, Any]]:
    """
    将数据库消息记录转换为 OpenAI 格式的消息列表。
    关键: 正确重建 assistant(tool_calls) + tool 的配对关系，
    否则 API 会报错 "Messages with role 'tool' must be a response to
    a preceding message with 'tool_calls'"。

    智能截断策略:
    - 最近 RECENT_MESSAGES_WINDOW 条消息: 不截断 tool result
    - 较旧消息: 按消息重要性 + 工具类型差异化截断
    """
    messages = []
    recent_start = max(len(history) - RECENT_MESSAGES_WINDOW, 0)
    total = len(history)

    for index, msg in enumerate(history):
        if msg.role == "assistant" and msg.msg_type == "tool_calls":
            # 重建 assistant tool_calls 消息
            try:
                data = json.loads(msg.content) if msg.content else {}
                tool_calls_raw = data.get("tool_calls", [])
                text = data.get("text", "")
                entry: dict[str, Any] = {
                    "role": "assistant",
                    "content": text,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc.get("input", {}), ensure_ascii=False),
                            },
                        }
                        for tc in tool_calls_raw
                    ],
                }
            except (json.JSONDecodeError, KeyError):
                entry = {"role": "assistant", "content": msg.content or ""}
            messages.append(entry)

        elif msg.role == "tool" and msg.tool_name:
            # 从 tool_input 中提取原始 tool_call_id
            tool_call_id = ""
            if msg.tool_input and isinstance(msg.tool_input, dict):
                tool_call_id = msg.tool_input.get("_tool_call_id", "")
            if not tool_call_id:
                tool_call_id = f"call_{msg.id}"  # 兜底: 生成一个
            content = msg.content or ""
            # 智能截断: 仅对旧消息截断，且按工具类型区分保留长度
            if index < recent_start and msg.msg_type == "tool_result":
                importance = _score_message_importance(msg, index, total)
                # 高重要性消息(>0.6)使用完整工具限制; 低重要性消息额外缩减
                if importance < 0.4:
                    # 低重要性: 仅保留最小摘要
                    content = _truncate_tool_result(content[:200], msg.tool_name)
                else:
                    content = _truncate_tool_result(content, msg.tool_name)
            entry = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
            messages.append(entry)

        else:
            messages.append({"role": msg.role, "content": msg.content or ""})

    return _sanitize_tool_call_pairing(messages)


def _sanitize_tool_call_pairing(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """修复 tool_call / tool_result 不匹配问题。

    MiniMax 等 LLM API 要求: assistant tool_calls 中的每个 id 都必须有对应的
    tool role 消息。如果 DB 中因中断/崩溃产生了孤立的 tool_calls，此函数会:
    1. 为缺失 result 的 tool_call 补充一条占位 tool result
    2. 移除没有对应 tool_call 的孤立 tool result
    """
    # 第一遍: 收集所有 tool_call IDs 和已有 tool_result IDs
    declared_tc_ids: dict[int, set[str]] = {}  # message index -> {tool_call_ids}
    existing_result_ids: set[str] = set()

    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            declared_tc_ids[i] = {tc["id"] for tc in msg["tool_calls"] if tc.get("id")}
        elif msg.get("role") == "tool" and msg.get("tool_call_id"):
            existing_result_ids.add(msg["tool_call_id"])

    if not declared_tc_ids:
        return messages

    # 第二遍: 找出缺失的 result，在对应 assistant 消息后插入占位
    patched: list[dict[str, Any]] = []
    for i, msg in enumerate(messages):
        patched.append(msg)
        if i in declared_tc_ids:
            missing_ids = declared_tc_ids[i] - existing_result_ids
            for tc_id in missing_ids:
                # 找到对应的 tool name
                tc_name = "unknown"
                for tc in msg.get("tool_calls", []):
                    if tc.get("id") == tc_id:
                        tc_name = tc.get("function", {}).get("name", "unknown")
                        break
                patched.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": f"[系统] 工具 {tc_name} 的执行结果因中断丢失",
                })
                logger.warning(
                    "[Context] 补充缺失的 tool_result: tool_call_id=%s tool=%s",
                    tc_id, tc_name,
                )

    # 第三遍: 移除 tool_call_id 不匹配任何已声明 tool_call 的 tool result
    all_declared = set()
    for ids in declared_tc_ids.values():
        all_declared.update(ids)

    result = []
    for msg in patched:
        if msg.get("role") == "tool" and msg.get("tool_call_id"):
            tc_id = msg["tool_call_id"]
            if tc_id not in all_declared:
                logger.warning("[Context] 移除孤立 tool_result: tool_call_id=%s", tc_id)
                continue
        result.append(msg)

    return result


def _select_profile_memories(
    memories: list[dict[str, Any]],
    max_count: int = 6,
) -> list[dict[str, Any]]:
    """选取用户画像记忆。

    策略改进: 不再固定每类1条（共3条），而是按 confidence 降序选取
    最多 max_count 条高质量记忆，覆盖所有有效类别。
    """
    valid_categories = {"preference", "instruction", "fact", "feedback"}
    candidates = [m for m in memories if m.get("category") in valid_categories]
    # 按 confidence 降序排列，同等 confidence 按最近更新优先
    candidates.sort(
        key=lambda m: (m.get("confidence", 0.5), m.get("created_at", "")),
        reverse=True,
    )
    # 每个类别最多选 2 条，总数不超过 max_count
    selected: list[dict[str, Any]] = []
    category_count: dict[str, int] = {}
    for m in candidates:
        cat = m["category"]
        if category_count.get(cat, 0) >= 2:
            continue
        selected.append(m)
        category_count[cat] = category_count.get(cat, 0) + 1
        if len(selected) >= max_count:
            break
    return selected


def _get_latest_user_message(history: list[TaskMessage]) -> str | None:
    for msg in reversed(history):
        if msg.role == "user" and msg.content:
            return msg.content[:1000]
    return None


def _truncate_tool_result(content: str, tool_name: str | None = None) -> str:
    """按工具类型智能截断 tool result，高价值工具保留更多内容。"""
    limit = TOOL_RESULT_CHAR_LIMITS.get(tool_name or "", OLD_TOOL_RESULT_CHAR_LIMIT)
    if len(content) <= limit:
        return content
    return content[:limit] + "...已截断"


def _score_message_importance(
    msg,
    index: int,
    total: int,
) -> float:
    """计算单条消息的重要性分数 (0.0 ~ 1.0)。

    评分维度:
    1. 角色基础分 — user > assistant > tool/system
    2. 工具类型加分 — 高价值工具 (web_search/parse_document等) 额外加分
    3. 位置衰减 — 越旧的消息分数越低（线性衰减）
    4. 内容长度加分 — 较长的用户/助手消息通常包含更多信息

    Returns:
        0.0 ~ 1.0 的重要性分数
    """
    role = getattr(msg, "role", "user")
    base_score = _ROLE_BASE_SCORES.get(role, 0.5)

    # 高价值工具额外加分
    tool_name = getattr(msg, "tool_name", None)
    if role == "tool" and tool_name in _HIGH_VALUE_TOOLS:
        base_score += _HIGH_VALUE_TOOL_BONUS

    # 位置衰减: index=0 最旧, index=total-1 最新
    if total > 1:
        position_ratio = index / (total - 1)  # 0.0(最旧) ~ 1.0(最新)
    else:
        position_ratio = 1.0
    position_factor = 1.0 - _POSITION_DECAY_WEIGHT * (1.0 - position_ratio)

    # 内容长度加分（仅对 user/assistant 消息，长消息通常更重要）
    content_bonus = 0.0
    content = getattr(msg, "content", "") or ""
    if role in ("user", "assistant") and len(content) > 500:
        content_bonus = 0.05

    score = base_score * position_factor + content_bonus
    return min(max(score, 0.0), 1.0)


def _build_summary_input(messages: list[TaskMessage]) -> str:
    summary_input = []
    for msg in messages:
        role = msg.role
        content = (msg.content or "")[:500]
        if msg.tool_name:
            summary_input.append(f"[{role}] 调用工具 {msg.tool_name}: {content[:200]}")
        else:
            summary_input.append(f"[{role}] {content}")
    return "\n".join(summary_input)


async def _flush_memories_before_compaction(
    session: AsyncSession,
    user_id: str,
    messages: list[TaskMessage],
    task_id: str,
) -> int:
    """压缩前让模型用 save_to_memory 工具主动刷盘重要长期信息。"""
    if not messages:
        return 0

    try:
        from app.core.llm_client import chat as llm_chat
        from app.services.memory_service import capture_memory
        from app.services.user_settings_service import (
            get_user_settings,
            is_auto_memory_capture_enabled,
            is_memory_enabled,
        )
        from app.tools.save_to_memory import TOOL_DEFINITION as SAVE_TO_MEMORY_TOOL

        settings = await get_user_settings(session, user_id)
        if not is_memory_enabled(settings):
            return 0

        transcript = _build_summary_input(messages)
        if not transcript.strip():
            return 0

        response = await llm_chat(
            system=(
                "你是长期记忆提取器。请从对话历史中提取值得长期保存的稳定信息，"
                "仅限用户偏好、长期指令、稳定事实、长期反馈。"
                "不要保存一次性任务细节、临时数字、工具执行过程。"
                "如果存在应保存的信息，请调用 save_to_memory 工具；没有则不要调用工具。"
            ),
            messages=[{"role": "user", "content": transcript[:8000]}],
            tools=[SAVE_TO_MEMORY_TOOL],
            task_id=task_id,
        )

        saved = 0
        for tool_call in response.tool_calls[:PREFLUSH_MAX_TOOL_CALLS]:
            if tool_call.name != "save_to_memory":
                continue

            category = str(tool_call.input.get("category") or "").strip()
            content = str(tool_call.input.get("content") or "").strip()
            confidence = float(tool_call.input.get("confidence", 0.7) or 0.7)

            if category not in {"preference", "instruction", "fact", "feedback"}:
                continue
            if not content:
                continue
            if not is_auto_memory_capture_enabled(settings, category):
                continue

            await capture_memory(
                session=session,
                user_id=user_id,
                category=category,
                content=content,
                source="agent_inferred",
                task_id=task_id,
                confidence=max(0.0, min(confidence, 1.0)),
            )
            saved += 1

        if saved:
            logger.info(
                f"[Context] 压缩前刷盘长期记忆: task={task_id} saved={saved}"
            )
        return saved
    except Exception as e:
        logger.warning(f"[Context] 压缩前记忆刷盘失败: {e}")
        return 0


def get_token_budget_info() -> dict[str, Any]:
    """获取 Token 预算配置信息。"""
    return {
        "model_context_window": MODEL_CONTEXT_WINDOW,
        "compress_ratio": COMPRESS_RATIO,
        "compress_threshold": COMPRESS_THRESHOLD,
        "alert_threshold": int(MODEL_CONTEXT_WINDOW * 0.85),
    }
