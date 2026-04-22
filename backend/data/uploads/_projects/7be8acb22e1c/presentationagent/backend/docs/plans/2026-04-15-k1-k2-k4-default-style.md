# K1/K2/K4 + Default PPT Style Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three deck generation reliability issues (lane retry, cascade failure, agent retry tool) and add a default McKinsey-style design template for PPT generation.

**Architecture:**
- K1 patches `lane_runner.py` to auto-retry API-overload errors with exponential backoff before giving up
- K2 patches `scheduler.py` cascade so dependent pages can be retried when their blocker recovers
- K4 adds a new `retry_failed_deck_pages` agent tool that lists failed pages and calls `scheduler.retry_page()` per page
- Default Style injects a fallback design spec into `DeckPlanner._build_planning_prompt()` when `notes` is empty

**Tech Stack:** Python/asyncio, SQLAlchemy async, existing `deck_state_store`, `DeckScheduler`, `DeckDirector`, `LaneRunner`, `DeckPlanner`

---

## Task 1: K1 — Lane Auto-Retry with Exponential Backoff

**Problem:** `diagram`/`chart` lanes fail with `AI 模型调用失败` after 2 seconds, `retries=1` in DB, and are never re-attempted automatically.

**Files:**
- Modify: `app/services/webdeck_runtime/lane_runner.py` (find the lane execution + error handling block)

**Step 1: Locate the lane execution error block**

In `lane_runner.py`, find the `try/except` block inside `run_lane()` (approximately lines 450–510) where the exception is caught and `deck_state_store.update_lane_status(..., LaneStatus.FAILED.value)` is called. Note exact line numbers.

**Step 2: Add retry constants above `LaneRunner` class**

```python
# Lane-level auto-retry for transient LLM errors
LANE_MAX_AUTO_RETRIES = 3          # total attempts = 1 original + 3 retries
LANE_RETRY_BACKOFF_BASE_S = 2.0    # 2s → 8s → 32s (exponential)
_TRANSIENT_ERROR_PATTERNS = (
    "负载过高",
    "overloaded",
    "rate limit",
    "529",
    "503",
    "AI 模型调用失败",
)
```

**Step 3: Wrap lane execution in retry loop**

Replace the single-shot lane call with a retry loop. The structure is:

```python
import asyncio as _asyncio

last_exc: Exception | None = None
for _attempt in range(LANE_MAX_AUTO_RETRIES + 1):
    try:
        result = await self._execute_lane_logic(...)   # existing call
        break   # success — exit loop
    except Exception as exc:
        last_exc = exc
        is_transient = any(p in str(exc) for p in _TRANSIENT_ERROR_PATTERNS)
        if not is_transient or _attempt >= LANE_MAX_AUTO_RETRIES:
            raise   # non-transient or exhausted — propagate
        wait = LANE_RETRY_BACKOFF_BASE_S ** (_attempt + 1)
        logger.warning(
            f"[LaneRunner] lane {lane.id} attempt {_attempt+1} failed "
            f"(transient), retrying in {wait:.0f}s: {exc}"
        )
        await _asyncio.sleep(wait)
```

**Step 4: Verify: write a unit test**

File: `test_lane_runner_retry.py` at project root.

```python
import asyncio, pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_lane_retries_on_transient_error():
    """Lane should retry up to LANE_MAX_AUTO_RETRIES times on transient errors."""
    call_count = 0

    async def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("AI 模型调用失败")
        return "ok"

    with patch(
        "app.services.webdeck_runtime.lane_runner.LaneRunner._execute_lane_logic",
        side_effect=fake_execute,
    ), patch("asyncio.sleep", new_callable=AsyncMock):
        from app.services.webdeck_runtime.lane_runner import LaneRunner
        # build minimal mock lane/context and call run_lane()
        # ... (adjust to actual signature)
        # assert call_count == 3 and no exception raised

@pytest.mark.asyncio  
async def test_lane_does_not_retry_non_transient():
    """Non-transient errors should not be retried."""
    call_count = 0

    async def fake_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("syntax error in generated code")

    with patch(
        "app.services.webdeck_runtime.lane_runner.LaneRunner._execute_lane_logic",
        side_effect=fake_execute,
    ), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # run_lane() should raise after 1 attempt, no sleep called
        assert call_count == 1
        mock_sleep.assert_not_called()
```

Run: `cd backend && python -m pytest test_lane_runner_retry.py -v`

---

## Task 2: K2 — Cascade Failure: Mark Dependents as Retryable

**Problem:** When page p08 fails (1 lane), pages p09–p13 (which declared p08 as a dependency) get cascade-marked `failed` immediately, even though the failure is transient and those pages never executed a single lane.

**Files:**
- Modify: `app/services/webdeck_runtime/scheduler.py` lines 308–342 (`_cascade_dependency_failure`)
- Modify: `app/services/webdeck_runtime/scheduler.py` `retry_page()` (lines ~190–236)

**Step 1: Read `_cascade_dependency_failure` and `_mark_page_failed_by_dependency`**

Confirm exact signatures. Key: `_mark_page_failed_by_dependency` sets `PageStatus.FAILED.value`.

**Step 2: Add `cascade_failed_by` metadata to cascade pages**

Instead of just marking failed, also write which page caused the cascade into `page.error_message` (or a new metadata JSON column if available). Check `deck_pages` schema for a `meta`/`error_message` column.

```python
# _mark_page_failed_by_dependency — add this before/after status update:
error_note = f"cascade_failed_by:{failed_page_id}"
await deck_state_store.update_page_status(
    session, target_page.id, PageStatus.FAILED.value,
    # pass error_note if the store function accepts it
)
logger.info(
    f"[Scheduler] page {target_page.page_id} cascade-failed "
    f"due to dependency failure on {failed_page_id}"
)
```

**Step 3: Make `retry_page` handle cascade-failed pages correctly**

In `retry_page()`, before running the page generation, check if it was cascade-failed and if its dependency page has since recovered:

```python
async def retry_page(self, project_id: str, page_id: str) -> None:
    async with async_session() as session:
        page = await deck_state_store.get_page_by_page_id(session, project_id, page_id)
        # If this page cascade-failed, check if blocker is now ok
        if page and page.status == "failed":
            spec = page.page_spec or {}
            deps = spec.get("dependencies", [])
            if deps:
                all_deps_ok = all(
                    (await deck_state_store.get_page_by_page_id(session, project_id, dep_id)).status == "completed"
                    for dep_id in deps
                )
                if not all_deps_ok:
                    # log that deps aren't ready yet — retry will still proceed
                    # (page can be rendered with fallback data)
                    logger.warning(
                        f"[Scheduler] retrying page {page_id} whose deps "
                        f"{deps} are not all completed"
                    )
    # ... existing retry logic continues unchanged
```

**Step 4: Verify with a unit test**

```python
def test_cascade_failed_pages_are_retryable():
    """Cascade-failed pages should not be blocked from re-execution."""
    # Mock scheduler with a project where p08 is failed, p09 is cascade-failed
    # Call retry_page(p09)
    # Assert that the page generation was attempted (not skipped)
    pass
```

---

## Task 3: K4 — `retry_failed_deck_pages` Agent Tool

**Problem:** When user says "重试失败页面", agent has no tool to actually trigger `director.retry_page()`. It falls back to writing JS files that do nothing.

**Files:**
- Create: `app/tools/retry_failed_deck_pages.py`
- Modify: `app/core/tool_dispatch.py` — add to PPT tool category

**Step 1: Create the tool file**

```python
# app/tools/retry_failed_deck_pages.py
"""Agent-callable tool to retry all failed pages in a Web Deck project."""
from __future__ import annotations
import asyncio
import logging
from typing import Any

from app.db.session import async_session
from app.services.webdeck_runtime.deck_state_store import deck_state_store
from app.services.webdeck_runtime.director import DeckDirector

logger = logging.getLogger(__name__)

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "retry_failed_deck_pages",
        "description": (
            "重试 Web Deck 项目中所有状态为失败的页面。"
            "当用户要求重试、重新生成失败页面或修复 Web Deck 时使用。"
            "会返回每个页面的重试结果摘要。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Web Deck 项目 ID（格式：UUID，例如 53ce5422-2506-4dd7-af1a-f30e78da2e2f）",
                },
            },
            "required": ["project_id"],
        },
    },
}


async def execute(project_id: str, ctx: Any = None) -> str:
    """List failed pages and retry each via DeckDirector."""
    send_fn = getattr(ctx, "send_fn", None)
    task_id = getattr(ctx, "task_id", None)

    async with async_session() as session:
        pages = await deck_state_store.get_pages(session, project_id)

    failed_pages = [p for p in pages if p.status == "failed"]
    if not failed_pages:
        return "✅ 没有失败的页面，所有页面均已完成。"

    # Sort by page index so dependency pages are retried first
    failed_pages.sort(key=lambda p: p.page_index if hasattr(p, "page_index") else 0)

    page_titles = [getattr(p, "title", p.page_id) for p in failed_pages]
    logger.info(
        f"[retry_failed_deck_pages] project={project_id} "
        f"retrying {len(failed_pages)} pages: {page_titles}"
    )

    if send_fn:
        await send_fn({
            "type": "status",
            "text": f"正在重试 {len(failed_pages)} 个失败页面...",
            "task_id": task_id,
        })

    # Build a send_fn wrapper that the director can use
    async def _noop_send(msg: dict) -> None:
        if send_fn:
            await send_fn(msg)

    director = DeckDirector(project_id=project_id, send_fn=_noop_send)

    retry_results: list[str] = []
    for page in failed_pages:
        try:
            await director.retry_page(project_id=project_id, page_id=page.page_id)
            retry_results.append(f"✅ {getattr(page, 'title', page.page_id)}")
        except Exception as exc:
            retry_results.append(f"❌ {getattr(page, 'title', page.page_id)}: {exc}")

    summary = "\n".join(retry_results)
    return f"已重试 {len(failed_pages)} 个失败页面：\n{summary}"
```

**Step 2: Verify DeckDirector constructor signature**

Open `app/services/webdeck_runtime/director.py` and confirm `__init__` accepts `project_id` and `send_fn`. Adjust `execute()` if signature differs.

**Step 3: Register tool in `tool_dispatch.py`**

Find the `ToolCategory.PPT` list in `app/core/tool_dispatch.py` (near line 43):

```python
# Before:
"edit_deck_page": [ToolCategory.PPT],

# After:
"edit_deck_page":           [ToolCategory.PPT],
"retry_failed_deck_pages":  [ToolCategory.PPT],
```

**Step 4: Add to tool category docstring / system prompt**

In `app/core/agent_prompts.py`, find `ppt_rules` and add one line:
```
- 重试失败页面使用 retry_failed_deck_pages 工具（需要 project_id）
```

**Step 5: Write unit test**

```python
# test_retry_failed_deck_pages_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_retry_failed_pages_calls_director():
    """Tool should call director.retry_page for each failed page."""
    mock_page = MagicMock()
    mock_page.status = "failed"
    mock_page.page_id = "p08"
    mock_page.title = "三层架构总览"
    mock_page.page_index = 7

    with (
        patch("app.tools.retry_failed_deck_pages.async_session"),
        patch("app.tools.retry_failed_deck_pages.deck_state_store.get_pages",
              new=AsyncMock(return_value=[mock_page])),
        patch("app.tools.retry_failed_deck_pages.DeckDirector") as MockDirector,
    ):
        mock_director = AsyncMock()
        MockDirector.return_value = mock_director

        from app.tools.retry_failed_deck_pages import execute
        result = await execute(project_id="fake-uuid")

        mock_director.retry_page.assert_called_once_with(
            project_id="fake-uuid", page_id="p08"
        )
        assert "三层架构总览" in result

@pytest.mark.asyncio
async def test_retry_no_failed_pages():
    """Tool should return success message when no pages are failed."""
    mock_page = MagicMock()
    mock_page.status = "completed"

    with (
        patch("app.tools.retry_failed_deck_pages.async_session"),
        patch("app.tools.retry_failed_deck_pages.deck_state_store.get_pages",
              new=AsyncMock(return_value=[mock_page])),
    ):
        from app.tools.retry_failed_deck_pages import execute
        result = await execute(project_id="fake-uuid")
        assert "没有失败" in result
```

Run: `cd backend && python -m pytest test_retry_failed_deck_pages_tool.py -v`

---

## Task 4: Default PPT Style

**Problem:** When agent generates webdeck_brief without style specs, the planner has no design guidance. User-specified style in `notes` goes through `build_research_summary()` which may dilute specific font names and hex codes.

**Files:**
- Modify: `app/services/webdeck_runtime/planner.py` — `_build_planning_prompt()` (lines ~152–223)

**Step 1: Define `DEFAULT_DESIGN_STYLE` constant**

Add near top of `planner.py` (after imports, before class definition):

```python
DEFAULT_DESIGN_STYLE: str = """\
视觉与美学风格（默认麦肯锡商业报告风格）：
- 美学风格：科技极简主义，高信息密度，简洁、锐利、权威
- 标题字体：衬线字体（Times New Roman 或 Garamond），传递专业质感
- 数据/标签字体：无衬线字体（Arial 或 Roboto），确保可读性
- 配色：白色背景 (#FFFFFF)；文字黑色 (#000000)；图表主色深宝蓝 (#0A2463)；灰阶辅助色 (#4A4A4A, #9E9E9E, #E0E0E0)
- 图形：表格使用细发丝边框，图表使用精确矢量线条，禁止3D效果和阴影
- 布局：每页必须有完整句子作为行动标题（So What结论）
- 数据可视化：优先使用复杂图表（软件架构图、业务流程图、堆叠柱状图、瀑布图、马里梅科图）、详细数据表格、战略框架或2x2矩阵
- 栏式布局：2-3栏多信息密度，模仿真实商业分析报告
- 数据完整性：未知数字使用占位符 [Data: XX%]，不编造数据来源\
"""
```

**Step 2: Inject design style into `_build_planning_prompt()`**

In `_build_planning_prompt()`, find where `notes` is currently NOT injected and add a dedicated design style section. Locate the `prompt_parts` list assembly and append:

```python
# After existing field extractions, before final join:

# Design style: use user-provided notes if available, else fall back to default
design_style = (brief.get("notes") or "").strip()
if not design_style:
    design_style = DEFAULT_DESIGN_STYLE
prompt_parts.append(f"**设计风格要求**:\n{design_style}")
```

This ensures:
- If `brief.notes` has user style → verbatim injection (bypasses research_summary summarization)
- If empty → default McKinsey style is used

**Step 3: Write a unit test**

```python
# test_planner_default_style.py
from app.services.webdeck_runtime.planner import DeckPlanner, DEFAULT_DESIGN_STYLE

def test_planner_uses_default_style_when_notes_empty():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5}
    prompt = planner._build_planning_prompt(brief)
    assert "设计风格要求" in prompt
    assert "Times New Roman" in prompt   # default style injected
    assert DEFAULT_DESIGN_STYLE[:30] in prompt

def test_planner_uses_user_style_when_notes_provided():
    planner = DeckPlanner()
    brief = {"topic": "测试主题", "page_count": 5, "notes": "极简黑白风格，禁止蓝色"}
    prompt = planner._build_planning_prompt(brief)
    assert "极简黑白风格" in prompt
    assert "Times New Roman" not in prompt  # default NOT injected
```

Run: `cd backend && python -m pytest test_planner_default_style.py -v`

---

## Task 5: Integration Test — Full Retry Flow

**Files:**
- Modify: `test_hermes_simple.py` — add retry flow validation

**Step 1: Extend test to verify `retry_failed_deck_pages` tool**

After the main flow test, add a second phase that:
1. Checks if any pages failed
2. Sends a chat message: `"请用 retry_failed_deck_pages 重试失败页面，project_id 是 XXX"`
3. Waits for status messages confirming retry was triggered
4. Confirms pages move from `failed` → `completed`/`retrying`

**Step 2: Verify default style in planning prompt**

Query the DB for the most recent `deck_projects.brief`, deserialize it, confirm:
- If `notes` was provided → it appears in the planner's system context
- If `notes` was not provided → `DEFAULT_DESIGN_STYLE` appears in planning context

**Step 3: Run full test**

```bash
cd backend && python test_hermes_simple.py
```
Expected output:
- `[PASS] dispatch #2 allowed` — K2 / Plan B exemption working
- `[PASS] webdeck_brief artifact detected` — brief generated
- `[PASS] plan_ready` — deck planning succeeded
- `[INFO] retry tool available` — K4 tool in agent's toolkit

---

## Implementation Order

```
Task 1 (K1: lane retry)           → independent, start here
Task 2 (K2: cascade fix)          → independent
Task 3 (K4: retry tool)           → depends on understanding director API
Task 4 (Default style)            → fully independent
Task 5 (Integration test)         → after all above
```

Tasks 1, 2, 4 are fully independent and can be parallelized.
