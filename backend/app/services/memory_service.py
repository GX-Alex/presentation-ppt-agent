"""
记忆服务 — 四层记忆系统的核心实现。
Layer 0: 上下文组装（由 context_service 负责）
Layer 1: 会话 + 检查点（本模块负责 checkpoint 读写）
Layer 2: 用户记忆 — 自动捕获 + embedding + 相似度检索
Layer 3: 文档向量索引（嵌入 + 检索）

Sprint 4: embedding 使用 sentence-transformers (all-MiniLM-L6-v2, 384维),
         相似度检索使用 numpy cosine similarity，适用 <10K 条记录。
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import (
    DocumentChunk,
    Presentation,
    Slide,
    SlideVersion,
    Task,
    TaskCheckpoint,
    TaskMessage,
    UserMemory,
)

logger = logging.getLogger(__name__)

# ──────────────── Embedding 模型 ────────────────

# 全局 embedding 模型实例（延迟加载）
_embed_model = None
_embed_model_load_attempted = False
_EMBED_DIM = 384  # all-MiniLM-L6-v2 输出维度
_EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBED_MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
_EMBED_MODEL_CACHE_DIR = "models--sentence-transformers--all-MiniLM-L6-v2"


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _find_cached_embed_model_path() -> str | None:
    cache_roots: list[Path] = []
    hf_home = str(os.getenv("HF_HOME") or "").strip()
    if hf_home:
        cache_roots.append(Path(hf_home))
    cache_roots.append(Path.home() / ".cache" / "huggingface")

    seen: set[str] = set()
    for cache_root in cache_roots:
        snapshot_root = cache_root / "hub" / _EMBED_MODEL_CACHE_DIR / "snapshots"
        snapshot_key = str(snapshot_root)
        if snapshot_key in seen:
            continue
        seen.add(snapshot_key)

        if not snapshot_root.is_dir():
            continue

        snapshots = [path for path in snapshot_root.iterdir() if path.is_dir()]
        if not snapshots:
            continue

        snapshots.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return str(snapshots[0])

    return None


def _get_embed_model():
    """延迟加载 embedding 模型（首次调用时初始化）。"""
    global _embed_model, _embed_model_load_attempted
    if _embed_model is not None:
        return _embed_model
    if _embed_model_load_attempted:
        return None

    _embed_model_load_attempted = True
    allow_remote = _is_truthy_env(os.getenv("GENERALAGENT_EMBEDDING_ALLOW_REMOTE"))
    cached_model_path = _find_cached_embed_model_path()
    model_source = cached_model_path or _EMBED_MODEL_NAME

    try:
        from sentence_transformers import SentenceTransformer

        load_kwargs: dict[str, Any] = {"trust_remote_code": False}
        if not allow_remote:
            load_kwargs["local_files_only"] = True

        _embed_model = SentenceTransformer(model_source, **load_kwargs)
        logger.info(
            "[Memory] Embedding 模型加载完成: %s (%s)",
            cached_model_path or _EMBED_MODEL_REPO,
            "local-cache" if not allow_remote else "remote-enabled",
        )
    except Exception as e:
        logger.warning(
            "[Memory] Embedding 模型加载失败，当前进程将跳过向量检索: %s (%s)",
            e,
            "仅本地缓存" if not allow_remote else "允许远端下载",
        )
    return _embed_model


def compute_embedding(text: str) -> list[float] | None:
    """计算文本的 embedding 向量。"""
    model = _get_embed_model()
    if model is None:
        return None
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception as e:
        logger.error(f"[Memory] Embedding 计算失败: {e}")
        return None


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    a = np.array(vec_a, dtype=np.float32)
    b = np.array(vec_b, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ──────────────── Layer 1: 检查点管理 ────────────────


async def save_checkpoint(
    session: AsyncSession,
    task_id: str,
    step_index: int,
    state: dict[str, Any],
    summary: str | None = None,
) -> str:
    """保存任务检查点（Agent 状态快照 + 摘要）。支持 upsert 以防重复 step_index。"""
    # 先检查是否已存在同 (task_id, step_index) 的检查点
    existing = await session.execute(
        select(TaskCheckpoint).where(
            TaskCheckpoint.task_id == task_id,
            TaskCheckpoint.step_index == step_index,
        )
    )
    existing_cp = existing.scalar_one_or_none()

    if existing_cp:
        existing_cp.state = state
        existing_cp.summary = summary
        existing_cp.created_at = datetime.utcnow()
        await session.commit()
        logger.info(f"[Memory] 更新检查点: task={task_id} step={step_index}")
        return existing_cp.id
    else:
        checkpoint = TaskCheckpoint(
            id=str(uuid.uuid4()),
            task_id=task_id,
            step_index=step_index,
            state=state,
            summary=summary,
            created_at=datetime.utcnow(),
        )
        session.add(checkpoint)
        await session.commit()
        logger.info(f"[Memory] 保存检查点: task={task_id} step={step_index}")
        return checkpoint.id


async def get_latest_checkpoint(
    session: AsyncSession,
    task_id: str,
) -> dict[str, Any] | None:
    """获取任务最新的检查点。"""
    stmt = (
        select(TaskCheckpoint)
        .where(TaskCheckpoint.task_id == task_id)
        .order_by(TaskCheckpoint.step_index.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    cp = result.scalar_one_or_none()
    if not cp:
        return None
    return {
        "id": cp.id,
        "step_index": cp.step_index,
        "state": cp.state,
        "summary": cp.summary,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
    }


async def list_checkpoints(
    session: AsyncSession,
    task_id: str,
) -> list[dict[str, Any]]:
    """列出任务的所有检查点。"""
    result = await session.execute(
        select(TaskCheckpoint)
        .where(TaskCheckpoint.task_id == task_id)
        .order_by(TaskCheckpoint.step_index.desc(), TaskCheckpoint.created_at.desc())
    )
    checkpoints = result.scalars().all()
    return [
        {
            "id": cp.id,
            "step_index": cp.step_index,
            "summary": cp.summary,
            "created_at": cp.created_at.isoformat() if cp.created_at else None,
        }
        for cp in checkpoints
    ]


async def rollback_task_to_checkpoint(
    session: AsyncSession,
    task_id: str,
    checkpoint_id: str,
) -> dict[str, Any] | None:
    """回滚任务到指定检查点。"""
    cp_result = await session.execute(
        select(TaskCheckpoint)
        .where(TaskCheckpoint.id == checkpoint_id)
        .where(TaskCheckpoint.task_id == task_id)
    )
    checkpoint = cp_result.scalar_one_or_none()
    if not checkpoint:
        return None

    task_result = await session.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        return None

    state = checkpoint.state or {}
    keep_message_ids = set(state.get("task_message_ids") or [])
    compressed_flags = state.get("compressed_flags") or {}

    msg_result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .order_by(TaskMessage.created_at.asc())
    )
    task_messages = msg_result.scalars().all()

    deleted_count = 0
    if keep_message_ids:
        delete_ids = [msg.id for msg in task_messages if msg.id not in keep_message_ids]
        deleted_count = len(delete_ids)
        if delete_ids:
            await session.execute(
                delete(TaskMessage).where(TaskMessage.id.in_(delete_ids))
            )

        for msg in task_messages:
            if msg.id in keep_message_ids:
                msg.is_compressed = bool(compressed_flags.get(msg.id, False))
    
    await _restore_presentations_from_checkpoint(session, task_id, state)

    await session.execute(
        delete(TaskCheckpoint)
        .where(TaskCheckpoint.task_id == task_id)
        .where(TaskCheckpoint.step_index > checkpoint.step_index)
    )

    task.intent = state.get("task_intent") or task.intent
    task.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "checkpoint_id": checkpoint.id,
        "step_index": checkpoint.step_index,
        "deleted_messages": deleted_count,
        "summary": checkpoint.summary,
    }


async def _restore_presentations_from_checkpoint(
    session: AsyncSession,
    task_id: str,
    state: dict[str, Any],
) -> None:
    presentation_ids = set(state.get("presentation_ids") or [])
    active_snapshot = state.get("active_presentation") or {}

    result = await session.execute(
        select(Presentation)
        .where(Presentation.task_id == task_id)
        .options(selectinload(Presentation.slides).selectinload(Slide.versions))
        .order_by(Presentation.created_at.asc())
    )
    presentations = result.scalars().all()

    if not presentation_ids:
        for presentation in presentations:
            await session.delete(presentation)
        return

    active_presentation_id = active_snapshot.get("presentation_id")
    active_presentation = None

    for presentation in presentations:
        if presentation.id not in presentation_ids:
            await session.delete(presentation)
            continue
        if presentation.id == active_presentation_id:
            active_presentation = presentation

    if not active_presentation:
        return

    active_presentation.title = active_snapshot.get("title") or active_presentation.title
    active_presentation.theme = active_snapshot.get("theme") or active_presentation.theme
    active_presentation.outline = active_snapshot.get("outline") or active_presentation.outline
    active_presentation.updated_at = datetime.utcnow()

    slide_snapshots = {
        slide["id"]: slide for slide in active_snapshot.get("slides", []) if slide.get("id")
    }

    for slide in list(active_presentation.slides):
        snapshot = slide_snapshots.get(slide.id)
        if not snapshot:
            await session.delete(slide)
            continue

        target_version = snapshot.get("version")
        if target_version is not None and slide.version != target_version:
            version_row = next(
                (version for version in slide.versions if version.version == target_version),
                None,
            )
            if version_row:
                slide.html = version_row.html
                slide.version = version_row.version

        slide.index = snapshot.get("index", slide.index)
        slide.type = snapshot.get("type", slide.type)
        slide.speaker_notes = snapshot.get("speaker_notes", slide.speaker_notes)
        slide.updated_at = datetime.utcnow()


# ──────────────── Layer 2: 用户记忆 ────────────────

# 记忆自动捕获的关键词模式
_PREFERENCE_PATTERNS = [
    r"我(喜欢|偏好|习惯|倾向于|更愿意|想要)",
    r"我的(风格|偏好|习惯|要求|标准)",
    r"以后(都|总是|一直|始终)(用|使用|按照)",
    r"记住我(的|喜欢|偏好)",
    r"默认(使用|采用|用)",
]

_FACT_PATTERNS = [
    r"我(是|在|叫|名叫|来自|就职于|工作在)",
    r"我(的|们)(公司|团队|部门|项目|产品)",
    r"我负责",
]

_INSTRUCTION_PATTERNS = [
    r"(以后|今后|从现在开始|记住|请注意)(.*)(格式|方式|风格|规格|规范)",
    r"(每次|所有|全部)(.*)(必须|应该|需要|要求)",
]


def detect_memory_signals(text: str) -> list[dict[str, str]]:
    """
    从用户消息中检测可自动捕获的记忆信号。
    返回 [{category, content}] — 候选记忆列表。
    """
    signals: list[dict[str, str]] = []

    for pattern in _PREFERENCE_PATTERNS:
        if re.search(pattern, text):
            signals.append({"category": "preference", "content": text})
            break

    for pattern in _FACT_PATTERNS:
        if re.search(pattern, text):
            signals.append({"category": "fact", "content": text})
            break

    for pattern in _INSTRUCTION_PATTERNS:
        if re.search(pattern, text):
            signals.append({"category": "instruction", "content": text})
            break

    return signals


async def capture_memory(
    session: AsyncSession,
    user_id: str,
    category: str,
    content: str,
    source: str = "auto_captured",
    task_id: str | None = None,
    confidence: float = 0.8,
) -> dict[str, Any]:
    """
    捕获一条用户记忆 — 计算 embedding + 去重检查 + 持久化。
    如果存在高度相似的记忆（相似度 > 0.9），则更新而非创建。
    """
    # 计算 embedding
    embedding = compute_embedding(content)
    embedding_json = json.dumps(embedding) if embedding else None

    # 去重: 检查是否存在高度相似的记忆
    if embedding:
        existing = await search_memories(
            session, user_id, content, top_k=1, threshold=0.9
        )
        if existing:
            # 更新已有记忆
            old_id = existing[0]["id"]
            await session.execute(
                update(UserMemory)
                .where(UserMemory.id == old_id)
                .values(
                    content=content,
                    embedding=embedding_json,
                    confidence=max(confidence, existing[0].get("confidence", 0)),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
            logger.info(f"[Memory] 更新已有记忆: id={old_id}")
            return {"id": old_id, "action": "updated", "content": content}

    # 创建新记忆
    memory = UserMemory(
        id=str(uuid.uuid4()),
        user_id=user_id,
        category=category,
        content=content,
        embedding=embedding_json,
        source=source,
        source_task_id=task_id,
        confidence=confidence,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(memory)
    await session.commit()
    logger.info(f"[Memory] 捕获新记忆: category={category} source={source}")
    return {"id": memory.id, "action": "created", "content": content}


async def search_memories(
    session: AsyncSession,
    user_id: str,
    query: str,
    top_k: int = 5,
    threshold: float = 0.3,
    time_decay: bool = True,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    语义检索用户记忆 — 综合向量相似度 + 时间衰减 + 使用频次。
    当提供 task_id 时，优先返回同任务的记忆，同时包含全局记忆（source_task_id 为空的）。

    评分公式 (time_decay=True):
        final_score = similarity * 0.7 + recency_score * 0.2 + confidence * 0.1
    其中 recency_score 基于记忆的更新时间到当前的天数天然衰减。

    返回按综合分降序排列的 top_k 条结果。
    """
    query_vec = compute_embedding(query)
    if not query_vec:
        # 退回到关键词匹配
        return await _keyword_search_memories(session, user_id, query, top_k, task_id=task_id)

    # 加载活跃记忆 — 按 task_id 过滤以防止跨项目记忆泄漏
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active == True)  # noqa: E712
    )
    if task_id:
        # 只加载当前任务相关记忆 + 全局记忆（无 task 关联）
        stmt = stmt.where(
            or_(
                UserMemory.source_task_id == task_id,
                UserMemory.source_task_id == None,  # noqa: E711
            )
        )
    result = await session.execute(stmt)
    memories = result.scalars().all()

    now = datetime.utcnow()

    # 计算综合评分并排序
    scored: list[tuple[float, float, UserMemory]] = []
    for m in memories:
        if not m.embedding:
            continue
        try:
            m_vec = json.loads(m.embedding)
            sim = cosine_similarity(query_vec, m_vec)
            if sim < threshold:
                continue

            if time_decay and m.updated_at:
                # 时间衰减: 半衰期30天，越新的记忆分数越高
                days_old = (now - m.updated_at).total_seconds() / 86400
                recency = 1.0 / (1.0 + days_old / 30.0)
            else:
                recency = 0.5

            confidence = m.confidence if m.confidence else 0.5
            # 综合评分: 相似度为主(0.7) + 时间衰减(0.2) + 置信度(0.1)
            final_score = sim * 0.7 + recency * 0.2 + confidence * 0.1
            scored.append((final_score, sim, m))
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": m.id,
            "category": m.category,
            "content": m.content,
            "confidence": m.confidence,
            "similarity": round(sim, 4),
            "source": m.source,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for _, sim, m in scored[:top_k]
    ]


async def _keyword_search_memories(
    session: AsyncSession,
    user_id: str,
    query: str,
    top_k: int,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """关键词回退搜索（embedding 不可用时）。"""
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active == True)  # noqa: E712
        .where(UserMemory.content.contains(query[:20]))
    )
    if task_id:
        stmt = stmt.where(
            or_(
                UserMemory.source_task_id == task_id,
                UserMemory.source_task_id == None,  # noqa: E711
            )
        )
    stmt = stmt.limit(top_k)
    result = await session.execute(stmt)
    return [
        {
            "id": m.id,
            "category": m.category,
            "content": m.content,
            "confidence": m.confidence,
            "similarity": 0.5,
            "source": m.source,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in result.scalars().all()
    ]


async def list_user_memories(
    session: AsyncSession,
    user_id: str,
    category: str | None = None,
    task_id: str | None = None,
) -> list[dict[str, Any]]:
    """列出用户活跃记忆。当提供 task_id 时只返回同任务+全局记忆。"""
    stmt = (
        select(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active == True)  # noqa: E712
    )
    if category:
        stmt = stmt.where(UserMemory.category == category)
    if task_id:
        stmt = stmt.where(
            or_(
                UserMemory.source_task_id == task_id,
                UserMemory.source_task_id == None,  # noqa: E711
            )
        )
    stmt = stmt.order_by(UserMemory.updated_at.desc())
    result = await session.execute(stmt)
    return [
        {
            "id": m.id,
            "category": m.category,
            "content": m.content,
            "confidence": m.confidence,
            "source": m.source,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in result.scalars().all()
    ]


async def delete_memory(
    session: AsyncSession,
    memory_id: str,
) -> bool:
    """软删除记忆（设为不活跃）。"""
    result = await session.execute(
        select(UserMemory).where(UserMemory.id == memory_id)
    )
    mem = result.scalar_one_or_none()
    if not mem:
        return False
    mem.is_active = False
    mem.updated_at = datetime.utcnow()
    await session.commit()
    return True


async def update_memory(
    session: AsyncSession,
    memory_id: str,
    *,
    category: str | None = None,
    content: str | None = None,
    source: str = "user_explicit",
) -> dict[str, Any] | None:
    """更新单条记忆内容。"""
    result = await session.execute(
        select(UserMemory).where(UserMemory.id == memory_id)
    )
    memory = result.scalar_one_or_none()
    if not memory:
        return None

    if category is not None:
        memory.category = category

    if content is not None:
        memory.content = content
        embedding = compute_embedding(content)
        memory.embedding = json.dumps(embedding) if embedding else None

    memory.source = source
    memory.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(memory)

    return {
        "id": memory.id,
        "category": memory.category,
        "content": memory.content,
        "confidence": memory.confidence,
        "source": memory.source,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
    }


async def clear_user_memories(
    session: AsyncSession,
    user_id: str,
) -> int:
    """清空用户所有记忆（软删除）。"""
    stmt = (
        update(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active == True)  # noqa: E712
        .values(is_active=False, updated_at=datetime.utcnow())
    )
    result = await session.execute(stmt)
    await session.commit()
    count = result.rowcount
    logger.info(f"[Memory] 清空用户记忆: user={user_id} count={count}")
    return count


async def get_memory_count(
    session: AsyncSession,
    user_id: str,
) -> int:
    """获取用户活跃记忆数量。"""
    stmt = (
        select(func.count())
        .select_from(UserMemory)
        .where(UserMemory.user_id == user_id)
        .where(UserMemory.is_active == True)  # noqa: E712
    )
    result = await session.execute(stmt)
    return result.scalar() or 0


# ──────────────── Layer 3: 文档向量索引 ────────────────


async def index_document_chunks(
    session: AsyncSession,
    asset_id: str,
    chunks: list[dict[str, Any]],
) -> int:
    """
    为文档创建向量索引 — 将分块文本计算 embedding 并持久化。
    返回成功索引的块数。
    """
    count = 0
    for chunk in chunks:
        content = chunk.get("content", "")
        if not content.strip():
            continue

        embedding = compute_embedding(content)
        embedding_json = json.dumps(embedding) if embedding else None

        doc_chunk = DocumentChunk(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            chunk_index=chunk.get("index", count),
            content=content,
            embedding=embedding_json,
            metadata_=chunk.get("metadata"),
            created_at=datetime.utcnow(),
        )
        session.add(doc_chunk)
        count += 1

    await session.commit()
    logger.info(f"[Memory] 文档索引完成: asset={asset_id} chunks={count}")
    return count


async def search_document_chunks(
    session: AsyncSession,
    asset_id: str | None,
    query: str,
    top_k: int = 5,
    threshold: float = 0.4,
) -> list[dict[str, Any]]:
    """语义检索文档块。"""
    query_vec = compute_embedding(query)
    if not query_vec:
        return []

    stmt = select(DocumentChunk)
    if asset_id:
        stmt = stmt.where(DocumentChunk.asset_id == asset_id)

    result = await session.execute(stmt)
    chunks = result.scalars().all()

    scored: list[tuple[float, DocumentChunk]] = []
    for c in chunks:
        if not c.embedding:
            continue
        try:
            c_vec = json.loads(c.embedding)
            sim = cosine_similarity(query_vec, c_vec)
            if sim >= threshold:
                scored.append((sim, c))
        except (json.JSONDecodeError, TypeError):
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "id": c.id,
            "asset_id": c.asset_id,
            "chunk_index": c.chunk_index,
            "content": c.content,
            "similarity": round(sim, 4),
            "metadata": c.metadata_,
        }
        for sim, c in scored[:top_k]
    ]
