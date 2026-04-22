"""
K2 tests — Cascade Failure: Mark Dependents as Retryable
Tests for the two additions in scheduler.py:
  1. _mark_page_failed_by_dependency logs the causing page_id
  2. retry_page warns (but does not block) when dependencies aren't completed
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

SCHEDULER_LOGGER = "app.services.webdeck_runtime.scheduler"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_async_session_cm():
    """Return a mock that behaves as `async with async_session() as session:`."""
    inner_session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory, inner_session


# ---------------------------------------------------------------------------
# Test 1: _mark_page_failed_by_dependency logs the failing dependency page_id
# ---------------------------------------------------------------------------

def test_cascade_log_includes_failed_page_id(caplog):
    """_mark_page_failed_by_dependency should emit an INFO log containing
    'cascade-failed' and the dependency page_id that triggered the cascade."""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    from app.services.webdeck_runtime.contracts import PageStatus

    # A page that is PENDING (not already FAILED) so the method proceeds
    mock_page = MagicMock()
    mock_page.page_id = "p09"
    mock_page.page_index = 8
    mock_page.title = "Content Page 9"
    mock_page.id = "db-id-p09"
    mock_page.status = PageStatus.PENDING.value  # "pending"

    mock_store = MagicMock()
    mock_store.get_pages = AsyncMock(return_value=[mock_page])
    mock_store.update_page_status = AsyncMock()

    session_factory, _ = _make_async_session_cm()
    send_fn = AsyncMock()

    scheduler = LaneScheduler()

    with patch("app.services.webdeck_runtime.scheduler.deck_state_store", mock_store), \
         patch("app.services.webdeck_runtime.scheduler.async_session", session_factory), \
         caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):

        result = asyncio.run(scheduler._mark_page_failed_by_dependency(
            project_id="proj-1",
            page_id="p09",
            page_index=8,
            title="Content Page 9",
            missing_dependencies=["p08"],
            send_fn=send_fn,
        ))

    # Method should have returned [page_id]
    assert result == ["p09"]

    # The new INFO log must mention the cascade and the dependency
    cascade_logs = [
        r for r in caplog.records
        if r.levelno == logging.INFO and "cascade-failed" in r.message
    ]
    assert cascade_logs, "Expected an INFO log containing 'cascade-failed'"
    assert any("p08" in r.message for r in cascade_logs), \
        "cascade-failed log must include the dependency page_id 'p08'"
    assert any("p09" in r.message for r in cascade_logs), \
        "cascade-failed log must include the failing page_id 'p09'"


def test_cascade_log_skipped_when_page_already_failed(caplog):
    """_mark_page_failed_by_dependency should return [] and skip logging
    when the page is already in FAILED state (idempotency guard)."""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    from app.services.webdeck_runtime.contracts import PageStatus

    mock_page = MagicMock()
    mock_page.page_id = "p09"
    mock_page.id = "db-id-p09"
    mock_page.status = PageStatus.FAILED.value  # already failed

    mock_store = MagicMock()
    mock_store.get_pages = AsyncMock(return_value=[mock_page])
    mock_store.update_page_status = AsyncMock()

    session_factory, _ = _make_async_session_cm()
    send_fn = AsyncMock()

    scheduler = LaneScheduler()

    with patch("app.services.webdeck_runtime.scheduler.deck_state_store", mock_store), \
         patch("app.services.webdeck_runtime.scheduler.async_session", session_factory), \
         caplog.at_level(logging.INFO, logger=SCHEDULER_LOGGER):

        result = asyncio.run(scheduler._mark_page_failed_by_dependency(
            project_id="proj-1",
            page_id="p09",
            page_index=8,
            title="Content Page 9",
            missing_dependencies=["p08"],
            send_fn=send_fn,
        ))

    assert result == []
    cascade_logs = [r for r in caplog.records if "cascade-failed" in r.message]
    assert not cascade_logs, "Should not log cascade-failed for already-failed page"


# ---------------------------------------------------------------------------
# Test 2: retry_page warns (but does not block) when deps aren't completed
# ---------------------------------------------------------------------------

def test_retry_page_warns_when_deps_incomplete(caplog):
    """retry_page should emit a WARNING containing 'incomplete deps' and the
    incomplete dependency page_id, and must still proceed to run the page."""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    from app.services.webdeck_runtime.contracts import PageStatus

    # Target page that has a declared dependency on p08
    mock_target = MagicMock()
    mock_target.page_id = "p09"
    mock_target.id = "db-id-p09"
    mock_target.title = "Content Page 9"
    mock_target.page_spec = {"dependencies": ["p08"]}
    mock_target.status = PageStatus.FAILED.value

    # Dependency page that is FAILED (not "completed")
    mock_dep = MagicMock()
    mock_dep.page_id = "p08"
    mock_dep.id = "db-id-p08"
    mock_dep.status = PageStatus.FAILED.value  # not "completed"

    # Project mock
    mock_project = MagicMock()
    mock_project.manifest = {
        "title": "Test Deck",
        "pages": [],
        "global_theme": {"primary_color": "#ffffff"},
    }
    mock_project.global_theme = {"theme": "default"}

    # Manifest mock
    mock_manifest = MagicMock()
    mock_manifest.global_theme.to_dict.return_value = {"theme": "default"}

    # Store mock
    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=mock_project)
    mock_store.get_pages = AsyncMock(return_value=[mock_target, mock_dep])
    mock_store.get_page = AsyncMock(return_value=mock_target)
    mock_store.update_page_status = AsyncMock()

    session_factory, _ = _make_async_session_cm()
    send_fn = AsyncMock()

    scheduler = LaneScheduler()
    # Replace orchestrator so the actual page generation is a no-op
    scheduler.page_orchestrator = MagicMock()
    scheduler.page_orchestrator.generate_page = AsyncMock()

    outer_session = AsyncMock()

    with patch("app.services.webdeck_runtime.scheduler.deck_state_store", mock_store), \
         patch("app.services.webdeck_runtime.scheduler.async_session", session_factory), \
         patch("app.services.webdeck_runtime.scheduler.DeckManifest") as mock_dm, \
         caplog.at_level(logging.WARNING, logger=SCHEDULER_LOGGER):

        mock_dm.from_dict.return_value = mock_manifest

        # Should complete without raising, even with incomplete deps
        asyncio.run(scheduler.retry_page(
            session=outer_session,
            project_id="proj-1",
            page_id="p09",
            send_fn=send_fn,
        ))

    # Warning must be present
    warn_logs = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "incomplete deps" in r.message
    ]
    assert warn_logs, "Expected a WARNING log containing 'incomplete deps'"
    assert any("p08" in r.message for r in warn_logs), \
        "Warning must name the incomplete dependency 'p08'"
    assert any("p09" in r.message for r in warn_logs), \
        "Warning must name the page being retried 'p09'"

    # The orchestrator must still have been called (retry was not blocked)
    assert scheduler.page_orchestrator.generate_page.called, \
        "generate_page should be called even when deps are incomplete"


def test_retry_page_no_warning_when_deps_completed(caplog):
    """retry_page should NOT warn when all dependency pages are completed."""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    from app.services.webdeck_runtime.contracts import PageStatus

    mock_target = MagicMock()
    mock_target.page_id = "p09"
    mock_target.id = "db-id-p09"
    mock_target.title = "Content Page 9"
    mock_target.page_spec = {"dependencies": ["p08"]}
    mock_target.status = PageStatus.FAILED.value

    # Dependency page is COMPLETED this time
    mock_dep = MagicMock()
    mock_dep.page_id = "p08"
    mock_dep.id = "db-id-p08"
    mock_dep.status = PageStatus.COMPLETED.value  # "completed"

    mock_project = MagicMock()
    mock_project.manifest = {"title": "Test Deck", "pages": [], "global_theme": {}}
    mock_project.global_theme = {"theme": "default"}

    mock_manifest = MagicMock()
    mock_manifest.global_theme.to_dict.return_value = {"theme": "default"}

    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=mock_project)
    mock_store.get_pages = AsyncMock(return_value=[mock_target, mock_dep])
    mock_store.get_page = AsyncMock(return_value=mock_target)
    mock_store.update_page_status = AsyncMock()

    session_factory, _ = _make_async_session_cm()
    send_fn = AsyncMock()

    scheduler = LaneScheduler()
    scheduler.page_orchestrator = MagicMock()
    scheduler.page_orchestrator.generate_page = AsyncMock()

    outer_session = AsyncMock()

    with patch("app.services.webdeck_runtime.scheduler.deck_state_store", mock_store), \
         patch("app.services.webdeck_runtime.scheduler.async_session", session_factory), \
         patch("app.services.webdeck_runtime.scheduler.DeckManifest") as mock_dm, \
         caplog.at_level(logging.WARNING, logger=SCHEDULER_LOGGER):

        mock_dm.from_dict.return_value = mock_manifest

        asyncio.run(scheduler.retry_page(
            session=outer_session,
            project_id="proj-1",
            page_id="p09",
            send_fn=send_fn,
        ))

    warn_logs = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "incomplete deps" in r.message
    ]
    assert not warn_logs, "Should not warn when all deps are completed"
    assert scheduler.page_orchestrator.generate_page.called
