import asyncio
from types import SimpleNamespace

from app.services.webdeck_runtime.scheduler import LaneScheduler
from app.services.webdeck_runtime import scheduler as scheduler_module


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _dummy_async_session():
    return _DummySessionContext()


def test_scheduler_runs_independent_pages_concurrently_and_honors_dependencies(monkeypatch) -> None:
    project = SimpleNamespace(
        manifest={
            "title": "并发调度测试",
            "pages": [
                {"page_id": "p01", "title": "封面", "page_kind": "cover", "dependencies": []},
                {"page_id": "p02", "title": "摘要", "page_kind": "summary", "dependencies": []},
                {"page_id": "p03", "title": "结论", "page_kind": "closing", "dependencies": ["p01"]},
            ],
            "global_theme": {},
        },
        global_theme={},
    )
    pages = [
        SimpleNamespace(id="db1", page_id="p01", page_index=0, title="封面", page_spec={"dependencies": []}, status="pending"),
        SimpleNamespace(id="db2", page_id="p02", page_index=1, title="摘要", page_spec={"dependencies": []}, status="pending"),
        SimpleNamespace(id="db3", page_id="p03", page_index=2, title="结论", page_spec={"dependencies": ["p01"]}, status="pending"),
    ]
    pages_by_db_id = {page.id: page for page in pages}
    events: list[dict] = []
    running_pages: set[str] = set()
    max_running = 0
    start_times: dict[str, float] = {}
    end_times: dict[str, float] = {}

    async def fake_send(event: dict) -> None:
        events.append(event)

    async def fake_get_project(session, project_id):
        return project

    async def fake_get_pages(session, project_id):
        return pages

    async def fake_get_page(session, page_db_id):
        return pages_by_db_id.get(page_db_id)

    async def fake_update_page_status(session, page_db_id, status):
        pages_by_db_id[page_db_id].status = status

    async def fake_generate_page(session, page, project_id, global_theme, send_fn, model=None):
        nonlocal max_running
        start_times[page.page_id] = asyncio.get_running_loop().time()
        running_pages.add(page.page_id)
        max_running = max(max_running, len(running_pages))
        await asyncio.sleep(0.06 if page.page_id == "p01" else 0.02)
        running_pages.remove(page.page_id)
        end_times[page.page_id] = asyncio.get_running_loop().time()

    monkeypatch.setattr(scheduler_module, "async_session", _dummy_async_session)
    monkeypatch.setattr(scheduler_module.deck_state_store, "get_project", fake_get_project)
    monkeypatch.setattr(scheduler_module.deck_state_store, "get_pages", fake_get_pages)
    monkeypatch.setattr(scheduler_module.deck_state_store, "get_page", fake_get_page)
    monkeypatch.setattr(scheduler_module.deck_state_store, "update_page_status", fake_update_page_status)

    scheduler = LaneScheduler(max_page_concurrency=2)
    monkeypatch.setattr(scheduler.page_orchestrator, "generate_page", fake_generate_page)

    result = asyncio.run(
        scheduler.run(
            session=object(),
            project_id="proj_1",
            send_fn=fake_send,
            model=None,
        )
    )

    assert result == {"total": 3, "completed": 3, "failed": 0}
    assert max_running == 2
    assert start_times["p02"] < end_times["p01"]
    assert start_times["p03"] >= end_times["p01"]
    assert any(event["type"] == "webdeck_progress" and event["page_id"] == "p01" for event in events)
    assert any(event["type"] == "webdeck_progress" and event["page_id"] == "p03" for event in events)
