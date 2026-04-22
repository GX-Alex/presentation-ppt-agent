"""
Tests for scheduler timeout & resume fixes:
- Page-level timeout (asyncio.TimeoutError handling)
- Skip-completed pages on resume
- asyncio.wait timeout constant
"""
import asyncio
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

SCHEDULER_MODULE = "app.services.webdeck_runtime.scheduler"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_async_session_cm():
    """async with async_session() as session: mock"""
    inner_session = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=inner_session)
    cm.__aexit__ = AsyncMock(return_value=False)
    factory = MagicMock(return_value=cm)
    return factory, inner_session


def _make_page(page_id, status="pending", deps=None, html=None):
    page = MagicMock()
    page.id = f"db_{page_id}"
    page.page_id = page_id
    page.page_index = int(page_id.replace("p", "")) if page_id.startswith("p") else 0
    page.title = f"Page {page_id}"
    page.page_kind = "content"
    page.status = status
    page.html = html
    page.page_spec = {"dependencies": deps or []}
    return page


def _make_project():
    project = MagicMock()
    project.id = "proj1"
    project.manifest = {"pages": []}
    project.global_theme = {"accent_color": "#3b82f6"}
    return project


# ---------------------------------------------------------------------------
# Test 1: Skip-completed pages on resume
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skip_completed_pages_unlocks_dependents():
    """已完成的页面应被跳过，其依赖者应被立即解锁并生成。"""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    from app.services.webdeck_runtime.contracts import PageStatus

    p01 = _make_page("p01", status="completed", html="<h1>done</h1>")
    p02 = _make_page("p02", status="pending", deps=["p01"])

    project = _make_project()

    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=project)
    mock_store.get_pages = AsyncMock(return_value=[p01, p02])
    mock_store.update_page_status = AsyncMock()
    mock_store.save_page_html = AsyncMock()

    send_fn = AsyncMock()
    scheduler = LaneScheduler()

    # Mock page_orchestrator to track what gets generated
    generated = []

    async def _mock_run(page_db_id, project_id, global_theme, send_fn, model):
        pid = page_db_id.replace("db_", "")
        generated.append(pid)
        return pid, True, None

    scheduler._run_page_with_fresh_session = _mock_run

    session = AsyncMock()
    with patch(f"{SCHEDULER_MODULE}.deck_state_store", mock_store):
        result = await scheduler.run(session, "proj1", send_fn, model=None)

    # p01 skipped (1 completed) + p02 generated (2 completed)
    assert result["completed"] == 2
    assert result["failed"] == 0
    assert "p02" in generated
    assert "p01" not in generated  # p01 was skipped, not re-generated


# ---------------------------------------------------------------------------
# Test 2: Chain unlock through skip-completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_skip_completed_unlocks_chain():
    """p01(completed) -> p02(pending) -> p03(pending):
    跳过 p01 应一路解锁 p02 和 p03。"""
    from app.services.webdeck_runtime.scheduler import LaneScheduler

    p01 = _make_page("p01", status="completed", html="<section>done</section>")
    p02 = _make_page("p02", status="pending", deps=["p01"])
    p03 = _make_page("p03", status="pending", deps=["p02"])

    project = _make_project()

    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=project)
    mock_store.get_pages = AsyncMock(return_value=[p01, p02, p03])
    mock_store.update_page_status = AsyncMock()

    send_fn = AsyncMock()
    scheduler = LaneScheduler()

    generated = []

    async def _mock_run(page_db_id, project_id, global_theme, send_fn, model):
        pid = page_db_id.replace("db_", "")
        generated.append(pid)
        return pid, True, None

    scheduler._run_page_with_fresh_session = _mock_run

    session = AsyncMock()
    with patch(f"{SCHEDULER_MODULE}.deck_state_store", mock_store):
        result = await scheduler.run(session, "proj1", send_fn, model=None)

    assert result["completed"] == 3
    assert result["failed"] == 0
    assert generated == ["p02", "p03"]  # p01 skipped, p02 then p03


# ---------------------------------------------------------------------------
# Test 3: Page timeout → failure (not hang)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_timeout_produces_failure():
    """页面超时应标记为失败，而非导致调度器永远阻塞。"""
    from app.services.webdeck_runtime.scheduler import LaneScheduler
    import app.services.webdeck_runtime.scheduler as sched_mod

    p01 = _make_page("p01", status="pending")
    project = _make_project()

    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=project)
    mock_store.get_pages = AsyncMock(return_value=[p01])
    mock_store.update_page_status = AsyncMock()

    send_fn = AsyncMock()
    scheduler = LaneScheduler()

    async def _mock_run_slow(page_db_id, project_id, global_theme, send_fn, model):
        await asyncio.sleep(999)  # will be cancelled by wait_for
        return "p01", True, None  # unreachable

    scheduler._run_page_with_fresh_session = _mock_run_slow

    # Use very short timeout for test
    original_timeout = sched_mod.DEFAULT_PAGE_TIMEOUT_S
    sched_mod.DEFAULT_PAGE_TIMEOUT_S = 0.1  # 100ms

    session_factory, inner_session = _make_async_session_cm()

    try:
        session = AsyncMock()
        with patch(f"{SCHEDULER_MODULE}.deck_state_store", mock_store), \
             patch(f"{SCHEDULER_MODULE}.async_session", session_factory):
            result = await scheduler.run(session, "proj1", send_fn, model=None)

        assert result["failed"] >= 1
        assert result["completed"] == 0
    finally:
        sched_mod.DEFAULT_PAGE_TIMEOUT_S = original_timeout


# ---------------------------------------------------------------------------
# Test 4: Constants are reasonable
# ---------------------------------------------------------------------------

def test_timeout_constants():
    from app.services.webdeck_runtime.scheduler import (
        DEFAULT_PAGE_TIMEOUT_S,
        WAIT_POLL_TIMEOUT_S,
    )
    assert DEFAULT_PAGE_TIMEOUT_S >= 60
    assert WAIT_POLL_TIMEOUT_S >= 10


# ---------------------------------------------------------------------------
# Test 5: Completed page without html is NOT skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_completed_without_html_is_not_skipped():
    """status=completed 但 html 为空的页面应该被重新生成，不跳过。"""
    from app.services.webdeck_runtime.scheduler import LaneScheduler

    p01 = _make_page("p01", status="completed", html=None)  # no html

    project = _make_project()

    mock_store = MagicMock()
    mock_store.get_project = AsyncMock(return_value=project)
    mock_store.get_pages = AsyncMock(return_value=[p01])
    mock_store.update_page_status = AsyncMock()

    send_fn = AsyncMock()
    scheduler = LaneScheduler()

    generated = []

    async def _mock_run(page_db_id, project_id, global_theme, send_fn, model):
        pid = page_db_id.replace("db_", "")
        generated.append(pid)
        return pid, True, None

    scheduler._run_page_with_fresh_session = _mock_run

    session = AsyncMock()
    with patch(f"{SCHEDULER_MODULE}.deck_state_store", mock_store):
        result = await scheduler.run(session, "proj1", send_fn, model=None)

    assert "p01" in generated  # should NOT be skipped
    assert result["completed"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
