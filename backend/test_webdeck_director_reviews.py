import asyncio
from types import SimpleNamespace

import pytest

from app.services.webdeck_runtime import director as director_module
from app.services.webdeck_runtime.contracts import ReviewReport
from app.services.webdeck_runtime.director import DeckDirector


class _DummySessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _dummy_async_session():
    return _DummySessionContext()


def _pages() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id="db1", page_id="p01", page_index=0, title="封面", page_kind="cover", status="completed"),
        SimpleNamespace(id="db2", page_id="p02", page_index=1, title="摘要", page_kind="summary", status="completed"),
    ]


def test_director_emits_deck_review_and_completes(monkeypatch) -> None:
    statuses: list[str] = []
    events: list[dict] = []
    assembled: list[str] = []

    async def fake_send(event: dict) -> None:
        events.append(event)

    async def fake_update_project_status(session, project_id, status):
        statuses.append(status)

    async def fake_get_pages(session, project_id):
        return _pages()

    async def fake_update_page_status(session, page_db_id, status):
        return None

    async def fake_scheduler_run(session, project_id, send_fn, model=None):
        return {"total": 2, "completed": 2, "failed": 0}

    async def fake_review_deck(session, project_id, model=None):
        return ReviewReport(passed=True, score=0.91, issues=[], suggestions=["整体质量良好"])

    async def fake_assemble(session, project_id):
        assembled.append(project_id)

    monkeypatch.setattr(director_module, "async_session", _dummy_async_session)
    monkeypatch.setattr(director_module.deck_state_store, "update_project_status", fake_update_project_status)
    monkeypatch.setattr(director_module.deck_state_store, "get_pages", fake_get_pages)
    monkeypatch.setattr(director_module.deck_state_store, "update_page_status", fake_update_page_status)

    director = DeckDirector(send_fn=fake_send)
    monkeypatch.setattr(director.scheduler, "run", fake_scheduler_run)
    monkeypatch.setattr(director.reviewer, "review_deck", fake_review_deck)
    monkeypatch.setattr(director, "_assemble_final_deck", fake_assemble)

    asyncio.run(director.execute_generation("project-pass"))

    assert statuses == ["generating", "reviewing", "completed"]
    assert assembled == ["project-pass"]
    assert any(
        event["type"] == "webdeck_review"
        and event["level"] == "deck"
        and event["passed"] is True
        for event in events
    )


def test_director_blocks_completion_when_deck_review_fails(monkeypatch) -> None:
    statuses: list[str] = []
    events: list[dict] = []
    assembled: list[str] = []
    failed_pages: list[tuple[str, str]] = []

    async def fake_send(event: dict) -> None:
        events.append(event)

    async def fake_update_project_status(session, project_id, status):
        statuses.append(status)

    async def fake_get_pages(session, project_id):
        return [
            SimpleNamespace(id="db1", page_id="p01", page_index=0, title="封面", page_kind="cover", status="completed"),
            SimpleNamespace(id="db2", page_id="p02", page_index=1, title="摘要", page_kind="summary", status="pending"),
        ]

    async def fake_update_page_status(session, page_db_id, status):
        failed_pages.append((page_db_id, status))

    async def fake_scheduler_run(session, project_id, send_fn, model=None):
        return {"total": 2, "completed": 2, "failed": 0}

    async def fake_review_deck(session, project_id, model=None):
        return ReviewReport(
            passed=False,
            score=0.42,
            issues=[{"level": "error", "message": "跨页结论不一致", "suggestion": "统一各页收束结论"}],
            suggestions=[],
        )

    async def fake_assemble(session, project_id):
        assembled.append(project_id)

    monkeypatch.setattr(director_module, "async_session", _dummy_async_session)
    monkeypatch.setattr(director_module.deck_state_store, "update_project_status", fake_update_project_status)
    monkeypatch.setattr(director_module.deck_state_store, "get_pages", fake_get_pages)
    monkeypatch.setattr(director_module.deck_state_store, "update_page_status", fake_update_page_status)

    director = DeckDirector(send_fn=fake_send)
    monkeypatch.setattr(director.scheduler, "run", fake_scheduler_run)
    monkeypatch.setattr(director.reviewer, "review_deck", fake_review_deck)
    monkeypatch.setattr(director, "_assemble_final_deck", fake_assemble)

    with pytest.raises(ValueError, match="跨页结论不一致"):
        asyncio.run(director.execute_generation("project-fail"))

    assert statuses == ["generating", "reviewing", "failed"]
    assert assembled == []
    assert any(
        event["type"] == "webdeck_review"
        and event["level"] == "deck"
        and event["passed"] is False
        for event in events
    )
    assert any(
        event["type"] == "webdeck_status"
        and event["status"] == "failed"
        for event in events
    )
    assert failed_pages == [("db2", "failed")]
    assert any(
        event["type"] == "webdeck_page_ready"
        and event["page_id"] == "p02"
        and event["status"] == "failed"
        for event in events
    )