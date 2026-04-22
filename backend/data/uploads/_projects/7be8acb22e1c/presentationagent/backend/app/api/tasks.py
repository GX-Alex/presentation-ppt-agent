"""Tasks API — 任务管理接口（CRUD）。"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.database import get_session
from app.models.tables import Task, TaskMessage
from app.services.memory_service import (
    get_latest_checkpoint,
    list_checkpoints,
    rollback_task_to_checkpoint,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

# 默认用户（一阶段无鉴权）
DEFAULT_USER_ID = "default-user-00000000"
WORKSPACE_ARTIFACT_TYPES = {"drawio", "document", "webpage", "code"}


def _build_workspace_sync_content(artifact_type: str, content: str) -> str:
    label_map = {
        "drawio": "draw.io 图",
        "document": "文档",
        "webpage": "网页原型",
        "code": "代码产物",
    }
    label = label_map.get(artifact_type, "工作区产物")
    normalized = content.strip()
    return (
        f"当前工作区中的最新{label}已由用户手动编辑并保存。后续修改必须严格以此版本为准。\n\n"
        f"<general-artifact type=\"{artifact_type}\">\n{normalized}\n</general-artifact>"
    )


@router.get("/")
async def list_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=100, description="每页数量"),
    session: AsyncSession = Depends(get_session),
):
    """列出当前用户的所有任务（按更新时间倒序，支持分页）。"""
    base_query = select(Task).where(Task.user_id == DEFAULT_USER_ID)

    # 总数
    count_q = select(func.count()).select_from(base_query.subquery())
    total_result = await session.execute(count_q)
    total = total_result.scalar() or 0

    stmt = (
        base_query
        .order_by(Task.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    tasks = result.scalars().all()

    return {
        "tasks": [
            {
                "id": t.id,
                "title": t.title or "未命名任务",
                "status": t.status,
                "intent": t.intent,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{task_id}")
async def get_task(task_id: str, session: AsyncSession = Depends(get_session)):
    """获取单个任务及其消息历史。"""
    stmt = (
        select(Task)
        .where(Task.id == task_id)
        .where(Task.user_id == DEFAULT_USER_ID)
        .options(selectinload(Task.messages))
    )
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    try:
        latest_checkpoint = await get_latest_checkpoint(session, task_id)
    except Exception:
        latest_checkpoint = None

    return {
        "task_id": task.id,
        "title": task.title or "未命名任务",
        "status": task.status,
        "intent": task.intent,
        "latest_checkpoint": latest_checkpoint,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content or "",
                "type": m.msg_type or "text",
                "tool_name": m.tool_name,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in sorted(task.messages, key=lambda x: x.created_at or datetime.min)
            if m.role in ("user", "assistant")
        ],
    }


@router.post("/{task_id}/workspace-artifact")
async def sync_workspace_artifact(
    task_id: str,
    body: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """将当前工作区中手动编辑后的工件同步回任务历史。"""
    stmt = select(Task).where(Task.id == task_id).where(Task.user_id == DEFAULT_USER_ID)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    artifact_type = str(body.get("artifact_type") or "").strip()
    content = str(body.get("content") or "").strip()
    if artifact_type not in WORKSPACE_ARTIFACT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的工作区工件类型")
    if not content:
        raise HTTPException(status_code=400, detail="工件内容不能为空")

    message_content = _build_workspace_sync_content(artifact_type, content)
    latest_result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.msg_type == "workspace_sync")
        .order_by(TaskMessage.created_at.desc())
        .limit(1)
    )
    latest_message = latest_result.scalar_one_or_none()
    if latest_message and (latest_message.content or "") == message_content:
        return {
            "success": True,
            "synced": False,
            "message_id": latest_message.id,
            "content": latest_message.content,
        }

    record = TaskMessage(
        id=str(uuid.uuid4()),
        task_id=task_id,
        role="user",
        content=message_content,
        msg_type="workspace_sync",
        created_at=datetime.utcnow(),
    )
    session.add(record)
    task.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "success": True,
        "synced": True,
        "message_id": record.id,
        "content": message_content,
    }


@router.get("/{task_id}/checkpoints")
async def get_task_checkpoints(task_id: str, session: AsyncSession = Depends(get_session)):
    """列出任务的所有检查点。"""
    task_result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .where(Task.user_id == DEFAULT_USER_ID)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    checkpoints = await list_checkpoints(session, task_id)
    return {"task_id": task_id, "checkpoints": checkpoints, "total": len(checkpoints)}


@router.post("/{task_id}/checkpoints/{checkpoint_id}/rollback")
async def rollback_task(
    task_id: str,
    checkpoint_id: str,
    session: AsyncSession = Depends(get_session),
):
    """回滚任务到指定检查点，并截断后续消息。"""
    task_result = await session.execute(
        select(Task)
        .where(Task.id == task_id)
        .where(Task.user_id == DEFAULT_USER_ID)
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = await rollback_task_to_checkpoint(session, task_id, checkpoint_id)
    if not result:
        raise HTTPException(status_code=404, detail="检查点不存在")

    try:
        latest_checkpoint = await get_latest_checkpoint(session, task_id)
    except Exception:
        latest_checkpoint = None
    return {
        "success": True,
        "task_id": task_id,
        "rollback": result,
        "latest_checkpoint": latest_checkpoint,
    }


@router.delete("/{task_id}")
async def delete_task(task_id: str, session: AsyncSession = Depends(get_session)):
    """删除任务及其所有关联数据（消息、PPT、幻灯片等）。"""
    # 查询任务
    stmt = select(Task).where(Task.id == task_id).where(Task.user_id == DEFAULT_USER_ID)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 删除任务（级联删除由数据库外键约束处理，或手动删除关联数据）
    # 先删除关联的 TaskMessage
    from sqlalchemy import delete

    await session.execute(delete(TaskMessage).where(TaskMessage.task_id == task_id))

    # 如果有PPT演示文稿，也删除（可能有多个）
    from app.models.tables import Presentation, Slide
    pres_stmt = select(Presentation).where(Presentation.task_id == task_id)
    pres_result = await session.execute(pres_stmt)
    presentations = pres_result.scalars().all()
    for presentation in presentations:
        # 删除幻灯片
        await session.execute(delete(Slide).where(Slide.presentation_id == presentation.id))
        # 删除演示文稿
        await session.execute(delete(Presentation).where(Presentation.id == presentation.id))

    # 删除任务
    await session.execute(delete(Task).where(Task.id == task_id))
    await session.commit()

    return {"success": True, "message": "任务已删除"}
