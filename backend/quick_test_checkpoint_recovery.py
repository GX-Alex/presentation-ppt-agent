"""Checkpoint 恢复与回滚验证脚本。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.agent_loop import _save_round_checkpoint
from app.core.llm_client import LLMResponse
from app.models.database import async_session, init_db
from app.models.tables import Presentation, Slide, SlideVersion, Task, TaskMessage
from app.services.memory_service import list_checkpoints, rollback_task_to_checkpoint

GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(name: str) -> None:
    print(f"{GREEN}✓{RESET} {name}")


def now_utc() -> datetime:
    return datetime.now(UTC)


async def run() -> None:
    print(f"{YELLOW}═══ Checkpoint Recovery 验证 ═══{RESET}")
    await init_db()

    task_id = f"task-{uuid.uuid4().hex[:8]}"
    presentation_id = f"pres-{uuid.uuid4().hex[:8]}"

    async with async_session() as session:
        task = Task(
            id=task_id,
            user_id="default-user-00000000",
            title="checkpoint test",
            status="active",
            intent="ppt",
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        session.add(task)
        await session.commit()

        user_msg = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=task_id,
            role="user",
            content="帮我做一份汇报 PPT",
            msg_type="text",
            created_at=now_utc(),
        )
        assistant_msg = TaskMessage(
            id=str(uuid.uuid4()),
            task_id=task_id,
            role="assistant",
            content="好的，我先给你一个大纲。",
            msg_type="text",
            created_at=now_utc(),
        )
        session.add_all([user_msg, assistant_msg])

        presentation = Presentation(
            id=presentation_id,
            task_id=task_id,
            title="季度汇报",
            theme={"id": "tech_dark", "name": "科技暗色"},
            outline=[{"index": 0, "title": "封面"}],
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        session.add(presentation)
        await session.flush()

        slide = Slide(
            id=str(uuid.uuid4()),
            presentation_id=presentation_id,
            index=0,
            type="title",
            html="<section>v1</section>",
            speaker_notes="v1-note",
            version=1,
            created_at=now_utc(),
            updated_at=now_utc(),
        )
        session.add(slide)
        await session.flush()

        session.add(
            SlideVersion(
                id=str(uuid.uuid4()),
                slide_id=slide.id,
                version=1,
                html="<section>v1</section>",
                source="ai",
                created_at=now_utc(),
            )
        )
        await session.commit()

        await _save_round_checkpoint(
            session=session,
            task=task,
            step_index=5,
            response=LLMResponse(total_tokens=123),
        )
        checkpoints = await list_checkpoints(session, task_id)
        assert checkpoints, "未创建 checkpoint"
        checkpoint_id = checkpoints[0]["id"]
        ok("已创建 checkpoint")

        # 模拟后续消息和 PPT 编辑
        session.add(
            TaskMessage(
                id=str(uuid.uuid4()),
                task_id=task_id,
                role="assistant",
                content="这是后续新增消息",
                msg_type="text",
                created_at=now_utc(),
            )
        )
        slide.html = "<section>v2</section>"
        slide.version = 2
        slide.speaker_notes = "v2-note"
        slide.updated_at = now_utc()
        session.add(
            SlideVersion(
                id=str(uuid.uuid4()),
                slide_id=slide.id,
                version=2,
                html="<section>v2</section>",
                source="wysiwyg",
                created_at=now_utc(),
            )
        )
        await session.commit()

        result = await rollback_task_to_checkpoint(session, task_id, checkpoint_id)
        assert result is not None, "rollback 返回为空"
        ok("rollback 接口返回成功")

        msg_result = await session.execute(
            select(TaskMessage)
            .where(TaskMessage.task_id == task_id)
            .order_by(TaskMessage.created_at.asc())
        )
        messages = msg_result.scalars().all()
        assert len(messages) == 2, f"消息未回滚，当前数量={len(messages)}"
        ok("消息已截断回 checkpoint")

        slide_result = await session.execute(select(Slide).where(Slide.id == slide.id))
        restored_slide = slide_result.scalar_one()
        assert restored_slide.version == 1, f"slide version={restored_slide.version}"
        assert restored_slide.html == "<section>v1</section>", restored_slide.html
        ok("PPT 最新幻灯片内容已恢复到 checkpoint")

    print(f"{GREEN}所有 checkpoint 验证通过{RESET}")


if __name__ == "__main__":
    asyncio.run(run())