"""Unit tests for retry_failed_deck_pages tool."""
import sys
from unittest.mock import AsyncMock, MagicMock


def _make_module():
    """Import the tool module with DB dependencies mocked."""
    # Mock dependencies before import
    mock_async_session = MagicMock()
    mock_database_module = MagicMock()
    mock_database_module.async_session = mock_async_session

    mock_deck_state_store_obj = MagicMock()
    mock_state_store_module = MagicMock()
    mock_state_store_module.deck_state_store = mock_deck_state_store_obj

    mock_director_class = MagicMock()
    mock_director_module = MagicMock()
    mock_director_module.DeckDirector = mock_director_class

    sys.modules["app.models.database"] = mock_database_module
    sys.modules["app.services"] = MagicMock()
    sys.modules["app.services.webdeck_runtime"] = MagicMock()
    sys.modules["app.services.webdeck_runtime.state_store"] = mock_state_store_module
    sys.modules["app.services.webdeck_runtime.director"] = mock_director_module

    # Force reimport
    sys.modules.pop("app.tools.retry_failed_deck_pages", None)
    import importlib
    mod = importlib.import_module("app.tools.retry_failed_deck_pages")
    return mod, mock_async_session, mock_deck_state_store_obj, mock_director_class


import pytest


@pytest.mark.asyncio
async def test_retry_failed_pages_calls_director():
    """Tool should call director.retry_page for each failed page."""
    mod, mock_async_session, mock_store, MockDirector = _make_module()

    mock_page = MagicMock()
    mock_page.status = "failed"
    mock_page.page_id = "p08"
    mock_page.title = "三层架构总览"
    mock_page.page_index = 7

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_async_session.return_value = mock_ctx
    mock_store.get_pages = AsyncMock(return_value=[mock_page])

    mock_director = AsyncMock()
    MockDirector.return_value = mock_director

    result = await mod.execute({"project_id": "fake-uuid"})

    mock_director.retry_page.assert_called_once_with(project_id="fake-uuid", page_id="p08")
    assert "三层架构总览" in result["result"]
    assert "1 个失败页面" in result["result"]


@pytest.mark.asyncio
async def test_retry_no_failed_pages():
    """Tool should return success message when no pages are failed."""
    mod, mock_async_session, mock_store, _ = _make_module()

    mock_page = MagicMock()
    mock_page.status = "completed"

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_async_session.return_value = mock_ctx
    mock_store.get_pages = AsyncMock(return_value=[mock_page])

    result = await mod.execute({"project_id": "fake-uuid"})
    assert "没有失败" in result["result"]


@pytest.mark.asyncio
async def test_retry_missing_project_id():
    """Tool should return error when project_id is missing."""
    mod, _, _, _ = _make_module()
    result = await mod.execute({})
    assert "error" in result
    assert "project_id" in result["error"]


@pytest.mark.asyncio
async def test_retry_pages_sorted_by_index():
    """Pages should be retried in page_index order."""
    mod, mock_async_session, mock_store, MockDirector = _make_module()

    mock_p10 = MagicMock()
    mock_p10.status = "failed"
    mock_p10.page_id = "p10"
    mock_p10.page_index = 9
    mock_p10.title = "第十页"

    mock_p03 = MagicMock()
    mock_p03.status = "failed"
    mock_p03.page_id = "p03"
    mock_p03.page_index = 2
    mock_p03.title = "第三页"

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_async_session.return_value = mock_ctx
    mock_store.get_pages = AsyncMock(return_value=[mock_p10, mock_p03])

    call_order: list[str] = []

    async def capture_retry(project_id, page_id):
        call_order.append(page_id)

    mock_director = MagicMock()
    mock_director.retry_page = AsyncMock(side_effect=capture_retry)
    MockDirector.return_value = mock_director

    await mod.execute({"project_id": "fake-uuid"})
    assert call_order == ["p03", "p10"]  # lower page_index first


def test_tool_definition_structure():
    """TOOL_DEFINITION should have correct schema."""
    mod, _, _, _ = _make_module()
    td = mod.TOOL_DEFINITION
    assert td["type"] == "function"
    assert td["function"]["name"] == "retry_failed_deck_pages"
    assert "project_id" in td["function"]["parameters"]["properties"]
    assert "project_id" in td["function"]["parameters"]["required"]
