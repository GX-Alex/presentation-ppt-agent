from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import TaskMessage
from app.services.diagram_xml_validator import summarize_diagram_xml


DIAGRAM_SESSION_MSG_TYPE = "diagram_session"


@dataclass
class DiagramSessionSnapshot:
    session_id: str
    task_id: str
    version: int
    xml: str
    summary: str
    source: str
    created_at: str
    svg: str | None = None
    png: str | None = None
    validation: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _payload_to_snapshot(payload: dict[str, Any]) -> DiagramSessionSnapshot:
    return DiagramSessionSnapshot(
        session_id=str(payload.get("session_id") or ""),
        task_id=str(payload.get("task_id") or ""),
        version=int(payload.get("version") or 0),
        xml=str(payload.get("xml") or ""),
        summary=str(payload.get("summary") or ""),
        source=str(payload.get("source") or "unknown"),
        created_at=str(payload.get("created_at") or ""),
        svg=payload.get("svg"),
        png=payload.get("png"),
        validation=payload.get("validation"),
    )


async def get_latest_diagram_session(session: AsyncSession, task_id: str) -> DiagramSessionSnapshot | None:
    result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.msg_type == DIAGRAM_SESSION_MSG_TYPE)
        .order_by(TaskMessage.created_at.desc())
        .limit(1)
    )
    record = result.scalar_one_or_none()
    if record is None or not record.content:
        return None
    return _payload_to_snapshot(json.loads(record.content))


async def list_diagram_history(session: AsyncSession, task_id: str, *, limit: int = 20) -> list[DiagramSessionSnapshot]:
    result = await session.execute(
        select(TaskMessage)
        .where(TaskMessage.task_id == task_id)
        .where(TaskMessage.msg_type == DIAGRAM_SESSION_MSG_TYPE)
        .order_by(TaskMessage.created_at.desc())
        .limit(limit)
    )
    snapshots: list[DiagramSessionSnapshot] = []
    for record in result.scalars().all():
        if not record.content:
            continue
        snapshots.append(_payload_to_snapshot(json.loads(record.content)))
    return snapshots


async def get_diagram_session_by_version(
    session: AsyncSession,
    task_id: str,
    version: int,
) -> DiagramSessionSnapshot | None:
    history = await list_diagram_history(session, task_id, limit=max(version + 5, 50))
    for snapshot in history:
        if snapshot.version == version:
            return snapshot
    return None


async def persist_diagram_session(
    session: AsyncSession,
    *,
    task_id: str,
    xml: str,
    source: str,
    svg: str | None = None,
    png: str | None = None,
    validation: dict[str, Any] | None = None,
) -> DiagramSessionSnapshot:
    latest = await get_latest_diagram_session(session, task_id)
    version = (latest.version if latest else 0) + 1
    stats = summarize_diagram_xml(xml)
    created_at = datetime.utcnow().isoformat()
    payload = {
        "session_id": f"diagram-session:{task_id}",
        "task_id": task_id,
        "version": version,
        "xml": xml,
        "summary": str(stats.get("summary") or "diagram updated"),
        "source": source,
        "svg": svg,
        "png": png,
        "validation": validation,
        "created_at": created_at,
    }
    record = TaskMessage(
        id=str(uuid.uuid4()),
        task_id=task_id,
        role="system",
        content=json.dumps(payload, ensure_ascii=False),
        msg_type=DIAGRAM_SESSION_MSG_TYPE,
        tool_name=source,
        created_at=datetime.utcnow(),
    )
    session.add(record)
    await session.commit()
    return _payload_to_snapshot(payload)


def snapshot_to_wire(snapshot: DiagramSessionSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()