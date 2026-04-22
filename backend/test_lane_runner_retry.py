"""
Tests for LaneRunner auto-retry with exponential backoff (Task 1 / K1).

Run:
    cd /Users/guoguo/quantlearn/generalagent/backend && python -m pytest test_lane_runner_retry.py -v
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webdeck_runtime.lane_runner import (
    LANE_MAX_AUTO_RETRIES,
    LANE_RETRY_BACKOFF_BASE_S,
    LaneRunner,
    _TRANSIENT_ERROR_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lane(kind: str = "narrative", retries: int = 0) -> SimpleNamespace:
    """Minimal stand-in for a LaneRun ORM object."""
    return SimpleNamespace(
        id="lane-db-1",
        lane_id="lane_test_001",
        kind=kind,
        input_data={},
        retries=retries,
    )


async def _noop_update(*args, **kwargs) -> None:
    """Async no-op replacement for deck_state_store.update_lane_status."""
    return None


_PATCH_STATE = "app.services.webdeck_runtime.lane_runner.deck_state_store.update_lane_status"
_PATCH_SLEEP = "asyncio.sleep"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLaneRetryConstants:
    """Verify module-level constants are set to the spec values."""

    def test_max_retries_is_3(self) -> None:
        assert LANE_MAX_AUTO_RETRIES == 3

    def test_backoff_base_is_2(self) -> None:
        assert LANE_RETRY_BACKOFF_BASE_S == 2.0

    def test_transient_patterns_contain_expected_strings(self) -> None:
        required = {"负载过高", "overloaded", "rate limit", "529", "503", "AI 模型调用失败"}
        for pattern in required:
            assert pattern in _TRANSIENT_ERROR_PATTERNS, (
                f"Missing transient pattern: {pattern!r}"
            )


class TestLaneRetryBehavior:
    """Verify retry loop inside run_lane()."""

    def test_succeeds_on_first_attempt_no_sleep(self) -> None:
        """No retries needed when handler succeeds immediately."""
        runner = LaneRunner()
        lane = _make_lane()
        session = MagicMock()
        expected = {"content": "<div>ok</div>", "asset": None, "metadata": {"kind": "narrative"}}
        call_count = 0
        sleep_calls: list[float] = []

        async def immediate_success(input_data, model):
            nonlocal call_count
            call_count += 1
            return expected

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=_noop_update)),
                patch(_PATCH_SLEEP, new=AsyncMock(side_effect=sleep_calls.append)),
            ):
                runner._get_handler = MagicMock(return_value=immediate_success)
                return await runner.run_lane(session, lane)

        result = asyncio.run(scenario())

        assert result == expected
        assert call_count == 1
        assert sleep_calls == []

    def test_retries_transient_then_succeeds(self) -> None:
        """Fails twice with transient error then succeeds; sleep called with correct backoff."""
        runner = LaneRunner()
        lane = _make_lane()
        session = MagicMock()
        expected = {"content": "<div>ok</div>", "asset": None, "metadata": {"kind": "narrative"}}
        call_count = 0
        sleep_calls: list[float] = []

        async def twice_failing(input_data, model):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("AI 模型调用失败")
            return expected

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=_noop_update)),
                patch(_PATCH_SLEEP, new=AsyncMock(side_effect=sleep_calls.append)),
            ):
                runner._get_handler = MagicMock(return_value=twice_failing)
                return await runner.run_lane(session, lane)

        result = asyncio.run(scenario())

        assert result == expected
        assert call_count == 3  # 2 transient failures + 1 success

        # Exponential backoff: 2^1 = 2.0, 2^2 = 4.0
        assert sleep_calls == [
            LANE_RETRY_BACKOFF_BASE_S ** 1,
            LANE_RETRY_BACKOFF_BASE_S ** 2,
        ]

    def test_non_transient_error_not_retried(self) -> None:
        """Non-transient error propagates immediately; no sleep, only 1 attempt."""
        runner = LaneRunner()
        lane = _make_lane()
        session = MagicMock()
        call_count = 0
        sleep_calls: list[float] = []

        async def non_transient_failure(input_data, model):
            nonlocal call_count
            call_count += 1
            raise ValueError("schema validation error — non-transient")

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=_noop_update)),
                patch(_PATCH_SLEEP, new=AsyncMock(side_effect=sleep_calls.append)),
            ):
                runner._get_handler = MagicMock(return_value=non_transient_failure)
                with pytest.raises(ValueError, match="non-transient"):
                    await runner.run_lane(session, lane)

        asyncio.run(scenario())

        assert call_count == 1
        assert sleep_calls == []

    def test_exhausts_all_retries_and_raises(self) -> None:
        """Always-failing transient error: all retries exhausted, exception propagates."""
        runner = LaneRunner()
        lane = _make_lane()
        session = MagicMock()
        call_count = 0
        sleep_calls: list[float] = []

        async def always_fails(input_data, model):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("AI 模型调用失败")

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=_noop_update)),
                patch(_PATCH_SLEEP, new=AsyncMock(side_effect=sleep_calls.append)),
            ):
                runner._get_handler = MagicMock(return_value=always_fails)
                with pytest.raises(RuntimeError, match="AI 模型调用失败"):
                    await runner.run_lane(session, lane)

        asyncio.run(scenario())

        # Total attempts: 1 original + LANE_MAX_AUTO_RETRIES retries
        assert call_count == LANE_MAX_AUTO_RETRIES + 1
        # Sleep between each attempt (not after the final failed one)
        assert len(sleep_calls) == LANE_MAX_AUTO_RETRIES
        # Verify the backoff progression: 2^1, 2^2, 2^3
        assert sleep_calls == [
            LANE_RETRY_BACKOFF_BASE_S ** 1,
            LANE_RETRY_BACKOFF_BASE_S ** 2,
            LANE_RETRY_BACKOFF_BASE_S ** 3,
        ]

    def test_overloaded_keyword_triggers_retry(self) -> None:
        """'overloaded' in exception message triggers a retry."""
        runner = LaneRunner()
        lane = _make_lane()
        session = MagicMock()
        call_count = 0
        sleep_calls: list[float] = []
        expected = {"content": "ok", "asset": None, "metadata": {}}

        async def once_overloaded(input_data, model):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("503 service overloaded, try again")
            return expected

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=_noop_update)),
                patch(_PATCH_SLEEP, new=AsyncMock(side_effect=sleep_calls.append)),
            ):
                runner._get_handler = MagicMock(return_value=once_overloaded)
                return await runner.run_lane(session, lane)

        result = asyncio.run(scenario())

        assert result == expected
        assert call_count == 2
        assert len(sleep_calls) == 1

    def test_existing_error_handler_called_on_final_failure(self) -> None:
        """After all retries, deck_state_store.update_lane_status is called with FAILED."""
        from app.services.webdeck_runtime.contracts import LaneStatus

        runner = LaneRunner()
        lane = _make_lane(retries=0)
        session = MagicMock()
        status_updates: list[str] = []

        async def capture_status_update(session, lane_id, status, **kwargs):
            status_updates.append(status)

        async def always_fails(input_data, model):
            raise RuntimeError("AI 模型调用失败")

        async def scenario():
            with (
                patch(_PATCH_STATE, new=AsyncMock(side_effect=capture_status_update)),
                patch(_PATCH_SLEEP, new=AsyncMock()),
            ):
                runner._get_handler = MagicMock(return_value=always_fails)
                with pytest.raises(RuntimeError):
                    await runner.run_lane(session, lane)

        asyncio.run(scenario())

        # First call sets RUNNING, last call sets FAILED
        assert status_updates[0] == LaneStatus.RUNNING.value
        assert status_updates[-1] == LaneStatus.FAILED.value
