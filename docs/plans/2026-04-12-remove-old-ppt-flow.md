# Remove Old PPT Generation Flow Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Permanently delete all code that can trigger the old Minimax PPT generation pipeline, preventing accidental LLM invocation of deprecated tools.

**Architecture:** Three layers to clean: (1) LLM-callable tool files that the agent can accidentally invoke, (2) backend service/middleware handlers that respond to those invocations, (3) frontend event handlers that render old-PPT WS events. The `Presentation`/`Slide` ORM tables are **kept** because the web-deck quality/export pipeline still uses them.

**Tech Stack:** Python/FastAPI backend (`backend/app/`), Next.js/TypeScript frontend (`frontend/src/`), SQLite via SQLAlchemy, no Alembic migrations (schema = `create_all` on startup).

---

## Scope Boundary

**DELETE** (old PPT flow):
- Tools LLM can call: `generate_ppt_deck`, `edit_slide`, `generate_slide`, `generate_outline`
- Generation engine: `minimax_ppt_generation_service.py`
- Dead legacy runner: `agent_loop.py` (replaced by `agent_runner.py`, only test files reference it)
- Middleware handlers: `_handle_generate_ppt*`, `_handle_edit_slide` in `PPTEventMiddleware`
- Old CRUD API endpoints: raw slide get/update/version endpoints
- Orphaned `ppt_service` functions: `update_slide`, `update_slide_by_index`, `get_slide_versions`, `revert_slide_version`, `get_slide_by_id`
- Frontend: WS handlers for `slide_ready`/`slide_updated`/`ppt_completed`/`outline`, `SlideEditor.tsx`, `VersionHistory.tsx`, old PPT state in chatStore

**KEEP** (web-deck quality flow still needs these):
- `Presentation`, `Slide`, `SlideVersion` ORM tables
- `ppt_service`: `create_presentation`, `save_slides`, `get_presentation`, `get_presentation_by_task`, `update_outline`, `build_full_html`, `get_canonical_deckspec*` functions
- `presentations.py` router: import PPTX, export, save-to-assets, native-pptx workflow endpoints
- `quality_generation_service.py`, `package_runtime.py`, `pptx_roundtrip_service.py`
- `PreviewPanel.tsx`, `ExportPanel.tsx` (export UI still active)

---

## Task 1: Delete LLM-Callable Old-PPT Tool Files

**Files:**
- Delete: `backend/app/tools/generate_ppt_deck.py`
- Delete: `backend/app/tools/edit_slide.py`
- Delete: `backend/app/tools/generate_slide.py`
- Delete: `backend/app/tools/generate_outline.py`

**Step 1: Delete the four tool files**

```bash
cd /Users/guoguo/quantlearn/generalagent/backend
rm app/tools/generate_ppt_deck.py
rm app/tools/edit_slide.py
rm app/tools/generate_slide.py
rm app/tools/generate_outline.py
```

**Step 2: Verify the tool autodiscovery no longer lists them**

```bash
python -c "
from app.core.tool_dispatch import get_tool_names
names = get_tool_names()
for bad in ['generate_ppt_deck','edit_slide','generate_slide','generate_outline']:
    assert bad not in names, f'{bad} still registered!'
print('OK — old tools not registered:', [n for n in names if 'ppt' in n or 'slide' in n or 'outline' in n or 'deck' in n])
"
```

Expected: prints something like `OK — old tools not registered: ['edit_deck_page']`

**Step 3: Commit**

```bash
git add -A app/tools/
git commit -m "chore: delete old PPT tool files (generate_ppt_deck, edit_slide, generate_slide, generate_outline)"
```

---

## Task 2: Delete Minimax PPT Generation Service

**Files:**
- Delete: `backend/app/services/minimax_ppt_generation_service.py`

**Step 1: Confirm nothing else imports it**

```bash
grep -rn "minimax_ppt_generation_service\|from app.services.minimax" backend/app/ --include="*.py"
```

Expected: no output (only tool file was the importer, which is already deleted).

**Step 2: Delete the file**

```bash
rm backend/app/services/minimax_ppt_generation_service.py
```

**Step 3: Commit**

```bash
git add -A backend/app/services/minimax_ppt_generation_service.py
git commit -m "chore: delete minimax_ppt_generation_service (old PPT engine)"
```

---

## Task 3: Slim `tool_dispatch.py` — Remove Old Tool Categories and Legacy Block

**Files:**
- Modify: `backend/app/core/tool_dispatch.py`

The changes are:
1. Remove 4 old tool entries from `TOOL_CATEGORIES` dict (lines ~43–47)
2. Remove the hard-coded legacy-block for `generate_ppt_deck` in `dispatch()` (lines ~222–235)
3. Update the `ToolCategory.PPT` class comment at line ~28

**Step 1: Remove old entries from TOOL_CATEGORIES**

In `tool_dispatch.py`, find and remove these 4 lines:
```python
# REMOVE these lines:
"generate_ppt_deck": [ToolCategory.PPT],
"edit_slide":        [ToolCategory.PPT],
"generate_slide":    [ToolCategory.PPT],
"generate_outline":  [ToolCategory.PPT],
```

Also update the comment on `ToolCategory.PPT`:
```python
# Before:
PPT = "ppt"                    # PPT/Deck类: generate_ppt_deck, edit_slide, generate_slide, generate_outline

# After:
PPT = "ppt"                    # Web Deck类: edit_deck_page
```

**Step 2: Remove the legacy dispatch block**

In `dispatch()` function, find and remove the block that starts around line 222:
```python
# REMOVE this entire block:
if tool_name == "generate_ppt_deck" and metadata.get("status") == "legacy":
    replacement = metadata.get("replacement") or "webdeck.quality_generation"
    logger.warning(
        "[ToolDispatch] 阻止已弃用 Tool: %s -> %s",
        tool_name,
        replacement,
    )
    return {
        "error": "工具 generate_ppt_deck 已弃用，必须改用 Web Deck / 高质量生成入口。",
        "tool": tool_name,
        "blocked": True,
        "deprecated": True,
        "replacement": replacement,
    }
```

**Step 3: Verify syntax**

```bash
cd backend && python -c "import app.core.tool_dispatch; print('OK')"
```

**Step 4: Commit**

```bash
git add backend/app/core/tool_dispatch.py
git commit -m "chore: remove old PPT tool categories and legacy dispatch block from tool_dispatch"
```

---

## Task 4: Slim `agent_middlewares.py` — Remove Old PPT Handlers from PPTEventMiddleware

**Files:**
- Modify: `backend/app/core/agent_middlewares.py`

**Step 1: Update `_PPT_TOOLS` set**

Find in `PPTEventMiddleware`:
```python
# Before:
_PPT_TOOLS = {"generate_ppt_deck", "edit_slide", "edit_deck_page"}

# After:
_PPT_TOOLS = {"edit_deck_page"}
```

**Step 2: Remove old tool dispatch branches from `on_tool_end`**

Find in `PPTEventMiddleware.on_tool_end`:
```python
# REMOVE these two branches:
if tool_name == "generate_ppt_deck":
    await self._handle_generate_ppt(ctx, result)
elif tool_name == "edit_slide":
    await self._handle_edit_slide(ctx, result)
elif tool_name == "edit_deck_page":
    await self._handle_edit_deck_page(ctx, result)

# After removal, only keep:
if tool_name == "edit_deck_page":
    await self._handle_edit_deck_page(ctx, result)
```

**Step 3: Delete `_handle_generate_ppt` and `_handle_generate_ppt_inner` methods**

Remove both methods entirely (~lines 548–662 in the original file). These import `ppt_service.create_presentation`, `save_slides`, and various plugin registry functions. They no longer have callers.

**Step 4: Delete `_handle_edit_slide` method**

Remove the method entirely (~lines 664–692 in the original file). It imports `ppt_service.update_slide_by_index` which is itself being removed.

**Step 5: Verify syntax and no broken references**

```bash
cd backend && python -c "from app.core.agent_middlewares import PPTEventMiddleware; print('OK', PPTEventMiddleware._PPT_TOOLS)"
```

Expected: `OK {'edit_deck_page'}`

**Step 6: Commit**

```bash
git add backend/app/core/agent_middlewares.py
git commit -m "chore: remove generate_ppt and edit_slide handlers from PPTEventMiddleware"
```

---

## Task 5: Clean Up `agent_prompts.py`

**Files:**
- Modify: `backend/app/core/agent_prompts.py`

**Step 1: Update `ppt_rules` section**

Find in `PROMPT_SECTIONS["ppt_rules"]` and remove the line that references `edit_slide` for old PPT, and the line saying `generate_ppt_deck` is deprecated:

```python
# REMOVE these two lines from ppt_rules:
"- 旧版 PPT 页面编辑（非 Web Deck 生成的演示文稿）使用 edit_slide 工具"
"- 不要调用旧版 generate_ppt_deck 工具（已弃用）"
```

The final `ppt_rules` body should only contain:
```
PPT/Web Deck 规则:
- Web Deck 页面编辑（修改某页内容、样式、布局）使用 edit_deck_page 工具（需要 project_id + page_id + instruction）
- 从零生成高质量演示文稿应引导用户使用 Web Deck 流程
- 可用主题: tech_dark, ocean_gradient, warm_sunset, forest_green, royal_purple, minimal_gray, coral_energy, classic_blue
```

**Step 2: Verify**

```bash
cd backend && python -c "from app.core.agent_prompts import PROMPT_SECTIONS; p=PROMPT_SECTIONS['ppt_rules']; assert 'edit_slide' not in p; assert 'generate_ppt_deck' not in p; print('OK'); print(p)"
```

**Step 3: Commit**

```bash
git add backend/app/core/agent_prompts.py
git commit -m "chore: remove edit_slide and generate_ppt_deck references from agent_prompts ppt_rules"
```

---

## Task 6: Slim `ppt_service.py` — Delete Old-PPT-Only Functions

**Files:**
- Modify: `backend/app/services/ppt_service.py`

Delete these 5 functions which are only called by old-PPT paths (all callers will be removed in earlier tasks):

| Function | Lines (approx) | Only caller |
|---|---|---|
| `update_slide` | 385–445 | `presentations.py` PUT /slides/{id} (being deleted) |
| `update_slide_by_index` | 448–474 | `PPTEventMiddleware._handle_edit_slide` (deleted in Task 4) |
| `get_slide_versions` | 477–504 | `presentations.py` GET /slides/{id}/versions (being deleted) |
| `revert_slide_version` | 507–544 | `presentations.py` POST /slides/{id}/versions/{v}/revert (being deleted) |
| `get_slide_by_id` | 547–569 | No callers (dead code) |

**Step 1: Delete the 5 functions**

Remove each function body including its docstring. Be careful not to remove anything above `update_slide` (line ~384) which contains active code.

**Step 2: Verify no broken imports**

```bash
cd backend && python -c "
import app.services.ppt_service as s
# Verify removed functions are gone
for fn in ['update_slide','update_slide_by_index','get_slide_versions','revert_slide_version','get_slide_by_id']:
    assert not hasattr(s, fn), f'{fn} still exists!'
# Verify kept functions still exist
for fn in ['create_presentation','save_slides','get_presentation','build_full_html','get_canonical_deckspec']:
    assert hasattr(s, fn), f'{fn} missing!'
print('OK')
"
```

**Step 3: Commit**

```bash
git add backend/app/services/ppt_service.py
git commit -m "chore: delete old-PPT-only functions from ppt_service (update_slide*, get_slide_versions, revert, get_by_id)"
```

---

## Task 7: Delete Old CRUD Endpoints from `presentations.py` API

**Files:**
- Modify: `backend/app/api/presentations.py`

Delete these endpoints (they are all old-PPT-only; the export/import/quality endpoints below them are kept):

| Endpoint | Approx lines | Why delete |
|---|---|---|
| `GET /presentations/{id}` | 61–70 | Raw old-PPT data, no web-deck use |
| `GET /presentations/task/{task_id}` | 73–83 | Old-PPT lookup (ChatPanel.tsx will be cleaned up) |
| `GET /presentations/{id}/html` | 110–119 | Reveal.js HTML from old PPT |
| `PUT /presentations/{id}/outline` | 126–136 | Old outline update |
| `PUT /slides/{slide_id}` | 142–169 | WYSIWYG slide save (SlideEditor will be deleted) |
| `GET /slides/{slide_id}/versions` | 172–179 | Slide version history |
| `POST /slides/{slide_id}/versions/{version}/revert` | 182–194 | Version revert |

Also remove the imports of deleted `ppt_service` functions from the top of the file: `update_slide`, `update_slide_by_index`, `get_slide_versions`, `revert_slide_version`, `get_slide_by_id`.

**Step 1: Delete the 7 endpoint functions and their unused ppt_service imports**

**Step 2: Start backend and verify the removed routes return 404**

```bash
# Start backend (in another terminal), then:
curl -s http://localhost:8002/api/presentations/nonexistent | python -m json.tool
# Should get FastAPI 404, NOT a ppt_service error
```

**Step 3: Verify active endpoints still work**

```bash
curl -s http://localhost:8002/api/presentations/export-capabilities | python -m json.tool
# Should return capabilities JSON
```

**Step 4: Commit**

```bash
git add backend/app/api/presentations.py
git commit -m "chore: delete old PPT slide CRUD endpoints from presentations API"
```

---

## Task 8: Delete Dead `agent_loop.py` and Its Test Files

`agent_loop.py` has been superseded by `agent_runner.py`. `chat_handler.py` imports `agent_loop_v2 as agent_loop` from `agent_runner.py`. The only references to `agent_loop.py` are legacy test files in the backend root.

**Files:**
- Delete: `backend/app/core/agent_loop.py` (915 lines, dead code)
- Delete: `backend/quick_test_checkpoint_recovery.py`
- Delete: `backend/quick_test_memory_improvements.py`
- Delete: `backend/test_p4_minimax_zero_to_one_flow.py`
- Delete: `backend/test_sprint4.py`
- Delete: `backend/test_p0_native_pptx_platform.py`

**Step 1: Confirm no production code imports agent_loop.py**

```bash
grep -rn "from app.core.agent_loop import\|import app.core.agent_loop" backend/app/ --include="*.py"
```

Expected: **no output** (only test files in root import it).

**Step 2: Delete files**

```bash
cd /Users/guoguo/quantlearn/generalagent/backend
rm app/core/agent_loop.py
rm quick_test_checkpoint_recovery.py
rm quick_test_memory_improvements.py
rm test_p4_minimax_zero_to_one_flow.py
rm test_sprint4.py
rm test_p0_native_pptx_platform.py
```

**Step 3: Verify backend still starts cleanly**

```bash
python -c "
from app.ws.chat_handler import *   # imports agent_loop_v2 from agent_runner
from app.core.agent_runner import agent_loop_v2
print('OK — chat_handler uses agent_runner, not agent_loop')
"
```

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete dead agent_loop.py (superseded by agent_runner.py) and orphaned test files"
```

---

## Task 9: Remove Old PPT WebSocket Event Handlers from Frontend

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`
- Modify: `frontend/src/lib/ws.ts`

**Step 1: Remove 4 case blocks from `useWebSocket.ts`**

In the `handleMessage` switch/if-else chain, delete these 4 case handlers:

```typescript
// REMOVE case "outline" handler (~lines 334–353)
case "outline": {
  const outline = ((data.outline as OutlineItem[]) || []) as OutlineItem[];
  ...
  store.setPptState("outline_ready");
  break;
}

// REMOVE case "slide_ready" handler (~lines 355–371)
case "slide_ready": {
  ...
  store.addSlide(slideData);
  break;
}

// REMOVE case "slide_updated" handler (~lines 373–393)
case "slide_updated": {
  ...
  break;
}

// REMOVE case "ppt_completed" handler (~lines 395–407)
case "ppt_completed": {
  ...
  store.setPptState("completed");
  break;
}
```

Also remove the import of `OutlineItem` from chatStore if it's only used in the `outline` handler.

**Step 2: Remove old PPT types from `ws.ts`**

In `frontend/src/lib/ws.ts`, remove `"outline"`, `"slide_ready"`, `"slide_updated"`, `"ppt_completed"` from the WS message type union (~lines 24–26).

**Step 3: Verify TypeScript compiles**

```bash
cd /Users/guoguo/quantlearn/generalagent/frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors (or only pre-existing errors unrelated to this change).

**Step 4: Commit**

```bash
git add frontend/src/hooks/useWebSocket.ts frontend/src/lib/ws.ts
git commit -m "feat: remove old PPT WS event handlers (outline/slide_ready/slide_updated/ppt_completed)"
```

---

## Task 10: Remove Old PPT State from `chatStore.ts`

**Files:**
- Modify: `frontend/src/stores/chatStore.ts`

**Step 1: Remove old PPT state fields and actions**

Find and remove:

```typescript
// REMOVE from PptState union type:
| "outline_pending"
| "outline_ready"

// REMOVE state field:
outline: OutlineItem[];

// REMOVE action:
setOutline: (data: { outline: OutlineItem[]; ... }) => void;

// REMOVE action:
addSlide: (slide: SlideData) => void;  // if only used by old PPT
```

In the initial state and reset block, remove `outline: []` and related old PPT fields.

Remove the `OutlineItem` type export if it was only for old PPT (check if anything else imports it).

**Step 2: Check nothing in active code uses the removed state**

```bash
grep -rn "setOutline\|OutlineItem\|outline_pending\|outline_ready" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v "chatStore.ts"
```

Expected: No active component should be calling these actions after Task 9 removed the WS handlers.

**Step 3: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

**Step 4: Commit**

```bash
git add frontend/src/stores/chatStore.ts
git commit -m "chore: remove old PPT outline/slide state from chatStore"
```

---

## Task 11: Delete `SlideEditor.tsx` and `VersionHistory.tsx`, Remove Their References

**Files:**
- Delete: `frontend/src/components/ppt/SlideEditor.tsx`
- Delete: `frontend/src/components/ppt/VersionHistory.tsx`
- Modify: `frontend/src/components/ppt/PreviewPanel.tsx` (remove imports and usages)

**Step 1: Find all import sites**

```bash
grep -rn "SlideEditor\|VersionHistory" frontend/src/ --include="*.tsx" --include="*.ts"
```

Expected: only `PreviewPanel.tsx` imports them.

**Step 2: Remove SlideEditor and VersionHistory usages from PreviewPanel.tsx**

- Remove `import SlideEditor from './SlideEditor'` 
- Remove `import VersionHistory from './VersionHistory'`
- Remove the JSX usage of `<SlideEditor .../>` and `<VersionHistory .../>`
- Remove any state that only existed to drive SlideEditor (WYSIWYG edit mode)

**Step 3: Delete the two files**

```bash
rm frontend/src/components/ppt/SlideEditor.tsx
rm frontend/src/components/ppt/VersionHistory.tsx
```

**Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

**Step 5: Commit**

```bash
git add -A frontend/src/components/ppt/
git commit -m "chore: delete SlideEditor and VersionHistory components (old PPT WYSIWYG/versioning)"
```

---

## Task 12: Remove Old PPT Fetch from `ChatPanel.tsx`

**Files:**
- Modify: `frontend/src/components/chat/ChatPanel.tsx`

**Step 1: Remove the fetch to `/api/presentations/task/{taskId}`**

Find (~line 124):
```typescript
fetch(`/api/presentations/task/${taskId}`),
```

This was used to rehydrate old-PPT state on panel load. Remove it and any store calls that used the result (e.g., `store.setPresentation(...)` or similar if they exist).

**Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

**Step 3: Commit**

```bash
git add frontend/src/components/chat/ChatPanel.tsx
git commit -m "chore: remove old PPT presentation fetch from ChatPanel on load"
```

---

## Task 13: Final Verification — Full Backend Boot Test

**Goal:** Confirm the backend boots without import errors, all old tools are gone, all web-deck tools still work.

**Step 1: Boot backend and check tool registry**

```bash
cd /Users/guoguo/quantlearn/generalagent/backend
python -c "
# Verify old tools are gone
from app.core.tool_dispatch import get_tool_names, dispatch
names = get_tool_names()
old = ['generate_ppt_deck','edit_slide','generate_slide','generate_outline']
for t in old:
    assert t not in names, f'OLD TOOL STILL REGISTERED: {t}'
# Verify web-deck tools still present
assert 'edit_deck_page' in names
print('Tool registry OK. Registered PPT tools:', [n for n in names if 'deck' in n or 'ppt' in n or 'slide' in n or 'outline' in n])
"
```

**Step 2: Verify middleware chain assembles without error**

```bash
python -c "
from app.core.agent_factory import AgentFactory
# Check PPTEventMiddleware has no old handler references
from app.core.agent_middlewares import PPTEventMiddleware
mw = PPTEventMiddleware()
assert not hasattr(mw, '_handle_generate_ppt'), '_handle_generate_ppt should be gone'
assert not hasattr(mw, '_handle_edit_slide'), '_handle_edit_slide should be gone' 
print('Middleware OK. _PPT_TOOLS:', mw._PPT_TOOLS)
"
```

**Step 3: Verify ppt_service no longer has old functions**

```bash
python -c "
import app.services.ppt_service as s
removed = ['update_slide','update_slide_by_index','get_slide_versions','revert_slide_version','get_slide_by_id']
for fn in removed:
    assert not hasattr(s, fn), f'{fn} still exists in ppt_service!'
print('ppt_service clean. Remaining functions:', [f for f in dir(s) if not f.startswith('_')])
"
```

**Step 4: Verify agent_loop.py is gone and chat_handler still works**

```bash
python -c "
import importlib.util
spec = importlib.util.find_spec('app.core.agent_loop')
assert spec is None, 'agent_loop.py should be deleted!'
from app.ws.chat_handler import ChatHandler
print('chat_handler imports OK (uses agent_runner, not agent_loop)')
"
```

**Step 5: Commit final state if any loose ends**

```bash
git add -A
git status  # should be clean
```

---

## Summary of Deletions

| File | Action |
|---|---|
| `backend/app/tools/generate_ppt_deck.py` | DELETE |
| `backend/app/tools/edit_slide.py` | DELETE |
| `backend/app/tools/generate_slide.py` | DELETE |
| `backend/app/tools/generate_outline.py` | DELETE |
| `backend/app/services/minimax_ppt_generation_service.py` | DELETE |
| `backend/app/core/agent_loop.py` | DELETE |
| `backend/quick_test_checkpoint_recovery.py` | DELETE |
| `backend/quick_test_memory_improvements.py` | DELETE |
| `backend/test_p4_minimax_zero_to_one_flow.py` | DELETE |
| `backend/test_sprint4.py` | DELETE |
| `backend/test_p0_native_pptx_platform.py` | DELETE |
| `frontend/src/components/ppt/SlideEditor.tsx` | DELETE |
| `frontend/src/components/ppt/VersionHistory.tsx` | DELETE |
| `backend/app/core/tool_dispatch.py` | MODIFY (remove 4 categories + legacy block) |
| `backend/app/core/agent_middlewares.py` | MODIFY (slim PPTEventMiddleware) |
| `backend/app/core/agent_prompts.py` | MODIFY (remove 2 old tool references) |
| `backend/app/services/ppt_service.py` | MODIFY (delete 5 old-only functions) |
| `backend/app/api/presentations.py` | MODIFY (delete 7 old CRUD endpoints) |
| `frontend/src/hooks/useWebSocket.ts` | MODIFY (remove 4 WS case handlers) |
| `frontend/src/lib/ws.ts` | MODIFY (remove 4 type literals) |
| `frontend/src/stores/chatStore.ts` | MODIFY (remove outline/slide state) |
| `frontend/src/components/chat/ChatPanel.tsx` | MODIFY (remove 1 fetch) |
| `frontend/src/components/ppt/PreviewPanel.tsx` | MODIFY (remove SlideEditor/VersionHistory imports) |
