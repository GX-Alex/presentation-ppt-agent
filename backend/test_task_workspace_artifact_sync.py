import asyncio
import uuid

import httpx
from sqlalchemy import select

from app.models.database import async_session, init_db
from app.models.tables import Task, User
from main import app

DEFAULT_USER_ID = "default-user-00000000"


def test_workspace_artifact_sync_api_persists_latest_drawio_version() -> None:
    async def _run() -> None:
        await init_db()

        async with async_session() as session:
            user_result = await session.execute(select(User).where(User.id == DEFAULT_USER_ID))
            user = user_result.scalar_one_or_none()
            if user is None:
                session.add(User(id=DEFAULT_USER_ID, name="默认用户", email="default@agent.local"))

            task_id = str(uuid.uuid4())
            session.add(Task(id=task_id, user_id=DEFAULT_USER_ID, title="drawio sync test", status="active"))
            await session.commit()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            xml = "<mxfile><diagram id=\"d1\" name=\"Page-1\"><mxGraphModel><root><mxCell id=\"0\"/><mxCell id=\"1\" parent=\"0\"/></root></mxGraphModel></diagram></mxfile>"
            sync_resp = await client.post(
                f"/api/tasks/{task_id}/workspace-artifact",
                json={"artifact_type": "drawio", "content": xml},
            )
            assert sync_resp.status_code == 200
            sync_payload = sync_resp.json()
            assert sync_payload["success"] is True
            assert sync_payload["synced"] is True
            assert '<general-artifact type="drawio">' in sync_payload["content"]
            assert xml in sync_payload["content"]

            duplicate_resp = await client.post(
                f"/api/tasks/{task_id}/workspace-artifact",
                json={"artifact_type": "drawio", "content": xml},
            )
            assert duplicate_resp.status_code == 200
            assert duplicate_resp.json()["synced"] is False

            task_resp = await client.get(f"/api/tasks/{task_id}")
            assert task_resp.status_code == 200
            messages = task_resp.json()["messages"]
            sync_message = next(message for message in messages if message["type"] == "workspace_sync")
            assert sync_message["role"] == "user"
            assert xml in sync_message["content"]

    asyncio.run(_run())