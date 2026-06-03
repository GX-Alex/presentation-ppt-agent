# Offline Deployment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the app fully deployable in an air-gapped enterprise environment via Docker Compose, with no outbound network requests at runtime.

**Architecture:** Vendor JS/CSS files (ECharts, Reveal.js) are downloaded once and committed to `frontend/public/vendor/`, served by Next.js static server at `/vendor/...`. Backend-generated HTML and frontend React both reference these paths via env vars. draw.io runs as a sidecar container. External APIs (Pexels, GitHub) are guarded by `OFFLINE_MODE=true`.

**Tech Stack:** Docker Compose, Next.js static serving, FastAPI env vars, Python `os.getenv`, bash

---

### Task 1: Download vendor files and create download script

**Files:**
- Create: `scripts/download-vendors.sh`
- Create: `frontend/public/vendor/` (directory + files)

**Step 1: Create the download script**

```bash
# scripts/download-vendors.sh
#!/bin/bash
set -e
VENDOR_DIR="frontend/public/vendor"
mkdir -p "$VENDOR_DIR/reveal.js/theme"

echo "Downloading ECharts..."
curl -fL "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js" \
  -o "$VENDOR_DIR/echarts.min.js"

echo "Downloading Reveal.js..."
BASE="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist"
curl -fL "$BASE/reveal.min.js"       -o "$VENDOR_DIR/reveal.js/reveal.min.js"
curl -fL "$BASE/reveal.min.css"      -o "$VENDOR_DIR/reveal.js/reveal.min.css"
curl -fL "$BASE/theme/black.min.css" -o "$VENDOR_DIR/reveal.js/theme/black.min.css"

echo "✅ Vendor files ready in $VENDOR_DIR"
```

**Step 2: Run the script to download files**

```bash
bash scripts/download-vendors.sh
```

Expected output: 5 files created under `frontend/public/vendor/`, total ~1.3MB.

**Step 3: Verify files exist**

```bash
ls -lh frontend/public/vendor/echarts.min.js frontend/public/vendor/reveal.js/
```

Expected: echarts.min.js (~1.1MB), reveal.js/ directory with 3 files.

**Step 4: Commit**

```bash
git add scripts/download-vendors.sh frontend/public/vendor/
git commit -m "feat(offline): add vendor download script and bundled JS/CSS files"
```

---

### Task 2: ECharts URL → environment variable

**Files:**
- Modify: `backend/app/services/webdeck_runtime/artifact_composer.py` (lines 173–174)
- Modify: `backend/app/services/webdeck_runtime/lane_runner.py` (lines 453, 530)

**Step 1: Add module-level constant in `artifact_composer.py`**

At the top of the file, after existing imports, add:

```python
import os

_ECHARTS_JS_URL = os.getenv("ECHARTS_JS_URL", "/vendor/echarts.min.js")
```

**Step 2: Replace hardcoded CDN URL in `artifact_composer.py`**

Find line 174 (the `<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js">` line) and change:

```python
# Before
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
# After
  <script src="{_ECHARTS_JS_URL}"></script>
```

**Step 3: Add constant and replace in `lane_runner.py`**

Same pattern — add `import os` and `_ECHARTS_JS_URL` constant at top, then replace the same CDN string at lines 453 and 530:

```python
import os
_ECHARTS_JS_URL = os.getenv("ECHARTS_JS_URL", "/vendor/echarts.min.js")
```

Replace both occurrences of:
```
https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js
```
with `{_ECHARTS_JS_URL}` in the f-string HTML templates.

**Step 4: Verify no CDN echarts URLs remain**

```bash
grep -rn 'cdn.jsdelivr.net.*echarts' backend/app/services/webdeck_runtime/
```

Expected: no output.

**Step 5: Commit**

```bash
git add backend/app/services/webdeck_runtime/artifact_composer.py \
        backend/app/services/webdeck_runtime/lane_runner.py
git commit -m "feat(offline): replace ECharts CDN URL with env var ECHARTS_JS_URL"
```

---

### Task 3: Iconify → inline SVG

**Files:**
- Modify: `backend/app/services/webdeck_runtime/artifact_composer.py` (lines 173, 337, 373, 377)

**Step 1: Remove iconify script tag (line 173)**

Delete this line:
```html
<script src="https://code.iconify.design/iconify-icon/2.1.0/iconify-icon.min.js"></script>
```

**Step 2: Remove iconify CSS rule (line 337)**

Delete this CSS rule:
```css
iconify-icon { display: inline-block; vertical-align: middle; }
```

**Step 3: Replace iconify icon elements with inline SVG**

Line 373 — replace `<iconify-icon icon="mdi:chevron-left"></iconify-icon>` with:
```html
<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>
```

Line 377 — replace `<iconify-icon icon="mdi:chevron-right"></iconify-icon>` with:
```html
<svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/></svg>
```

**Step 4: Verify no iconify references remain**

```bash
grep -rn 'iconify' backend/app/services/webdeck_runtime/artifact_composer.py
```

Expected: no output.

**Step 5: Commit**

```bash
git add backend/app/services/webdeck_runtime/artifact_composer.py
git commit -m "feat(offline): replace iconify web component with inline SVG arrows"
```

---

### Task 4: Reveal.js URL → environment variable (backend)

**Files:**
- Modify: `backend/app/services/theme_manager.py` (lines 307, 308, 374)

**Step 1: Add constant at top of `theme_manager.py`**

After existing imports:
```python
import os

_REVEAL_JS_BASE = os.getenv("REVEAL_JS_BASE_URL", "/vendor/reveal.js")
```

**Step 2: Replace the three CDN lines**

Line 307:
```python
# Before
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.min.css">
# After
    <link rel="stylesheet" href="{_REVEAL_JS_BASE}/reveal.min.css">
```

Line 308:
```python
# Before
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/theme/black.min.css" id="theme">
# After
    <link rel="stylesheet" href="{_REVEAL_JS_BASE}/theme/black.min.css" id="theme">
```

Line 374:
```python
# Before
    <script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.min.js"></script>
# After
    <script src="{_REVEAL_JS_BASE}/reveal.min.js"></script>
```

**Step 3: Verify no CDN reveal.js URLs remain in backend**

```bash
grep -rn 'cdn.jsdelivr.net.*reveal' backend/
```

Expected: no output.

**Step 4: Commit**

```bash
git add backend/app/services/theme_manager.py
git commit -m "feat(offline): replace Reveal.js CDN URLs with env var REVEAL_JS_BASE_URL"
```

---

### Task 5: Reveal.js URL → environment variable (frontend)

**Files:**
- Modify: `frontend/src/components/ppt/PreviewPanel.tsx` (lines 70, 71, 190)

**Step 1: Add env var read at top of component file**

After imports, before the component:
```typescript
const REVEAL_JS_BASE = process.env.NEXT_PUBLIC_REVEAL_JS_BASE_URL ?? "/vendor/reveal.js";
```

**Step 2: Replace the three CDN lines**

Line 70:
```typescript
// Before
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.min.css">
// After
  <link rel="stylesheet" href="${REVEAL_JS_BASE}/reveal.min.css">
```

Line 71:
```typescript
// Before
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/theme/black.min.css" id="theme">
// After
  <link rel="stylesheet" href="${REVEAL_JS_BASE}/theme/black.min.css" id="theme">
```

Line 190:
```typescript
// Before
  <script src="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist/reveal.min.js"></script>
// After
  <script src="${REVEAL_JS_BASE}/reveal.min.js"></script>
```

**Step 3: Verify no CDN reveal.js URLs remain in frontend**

```bash
grep -rn 'cdn.jsdelivr.net.*reveal' frontend/src/
```

Expected: no output.

**Step 4: Commit**

```bash
git add frontend/src/components/ppt/PreviewPanel.tsx
git commit -m "feat(offline): replace Reveal.js CDN in PreviewPanel with NEXT_PUBLIC_REVEAL_JS_BASE_URL"
```

---

### Task 6: Intranet search adapter in web_search.py

**Files:**
- Modify: `backend/app/tools/web_search.py`

**Step 1: Add intranet search function**

After the existing constants (`TAVILY_API_KEY`, `HTTPX_TIMEOUT`), add:

```python
INTRANET_SEARCH_URL = os.getenv("INTRANET_SEARCH_URL", "")

async def _intranet_search(query: str, max_results: int) -> list[dict[str, str]] | None:
    """Call intranet search API. Returns None if not configured or on failure."""
    if not INTRANET_SEARCH_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTPX_TIMEOUT) as client:
            resp = await client.post(
                INTRANET_SEARCH_URL,
                json={"query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as exc:
        logger.warning("[web_search] 内网搜索失败: %s", exc)
        return None
```

**Step 2: Insert intranet search at top of `execute()` priority chain**

At the start of the `execute()` function, before the Tavily block:

```python
# 优先使用内网搜索
intranet_results = await _intranet_search(query, max_results)
if intranet_results is not None:
    return {"results": intranet_results, "source": "intranet"}
```

**Step 3: Verify logic**

```bash
grep -n 'intranet\|INTRANET' backend/app/tools/web_search.py
```

Expected: constant, helper function, and call site all present.

**Step 4: Commit**

```bash
git add backend/app/tools/web_search.py
git commit -m "feat(offline): add intranet search adapter with INTRANET_SEARCH_URL env var"
```

---

### Task 7: remote_package_sources.py offline guard

**Files:**
- Modify: `backend/app/services/remote_package_sources.py` (around line 107)

**Step 1: Add offline guard at top of `fetch_remote_package_bundle`**

The function at line 107 makes HTTP requests to GitHub. Add an early return when `OFFLINE_MODE=true`:

```python
async def fetch_remote_package_bundle(source_id: str) -> RemotePackageBundle:
    if os.getenv("OFFLINE_MODE", "").lower() == "true":
        raise ValueError(f"离线模式：跳过远程插件拉取 ({source_id})")
    # ... rest of existing code
```

**Step 2: Verify**

```bash
grep -n 'OFFLINE_MODE\|fetch_remote_package_bundle' \
  backend/app/services/remote_package_sources.py | head -5
```

**Step 3: Commit**

```bash
git add backend/app/services/remote_package_sources.py
git commit -m "feat(offline): skip GitHub remote package fetch when OFFLINE_MODE=true"
```

---

### Task 8: docker-compose.yml — add drawio service and env vars

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Add drawio service**

Add after the `frontend` service block, before `volumes:`:

```yaml
  drawio:
    image: jgraph/drawio:24
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
```

**Step 2: Add env vars to frontend service**

In the `frontend` service `environment:` block, add:

```yaml
      - NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL=${NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL:-}
      - NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL=${NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL:-}
      - NEXT_PUBLIC_REVEAL_JS_BASE_URL=${NEXT_PUBLIC_REVEAL_JS_BASE_URL:-}
```

**Step 3: Add env vars to backend service**

In the `backend` service `environment:` block, add:

```yaml
      - ECHARTS_JS_URL=${ECHARTS_JS_URL:-}
      - REVEAL_JS_BASE_URL=${REVEAL_JS_BASE_URL:-}
      - INTRANET_SEARCH_URL=${INTRANET_SEARCH_URL:-}
      - OFFLINE_MODE=${OFFLINE_MODE:-false}
```

**Step 4: Verify compose file is valid**

```bash
docker compose config --quiet && echo "✅ compose config valid"
```

**Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(offline): add drawio service and offline env vars to docker-compose"
```

---

### Task 9: Create .env.offline template

**Files:**
- Create: `.env.offline`

**Step 1: Create the file**

```bash
# .env.offline — 离线部署配置模板
# 复制为 .env 后修改以下值

# ── LLM（指向内网代理）──
LLM_BASE_URL=http://your-llm-proxy/v1
LLM_API_KEY=your-key-here

# ── draw.io（容器内部通信）──
NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL=http://drawio:8080
NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL=http://drawio:8080

# ── Vendor 静态资源（已打包进镜像，无需修改）──
ECHARTS_JS_URL=/vendor/echarts.min.js
REVEAL_JS_BASE_URL=/vendor/reveal.js
NEXT_PUBLIC_REVEAL_JS_BASE_URL=/vendor/reveal.js

# ── 内网搜索（填写内网搜索服务地址）──
INTRANET_SEARCH_URL=http://your-search-host/search

# ── 离线模式（禁用所有外网服务）──
OFFLINE_MODE=true

# ── 禁用外网 API ──
PEXELS_API_KEY=
GITHUB_TOKEN=
TAVILY_API_KEY=
```

**Step 2: Commit**

```bash
git add .env.offline
git commit -m "feat(offline): add .env.offline template for air-gapped deployment"
```

---

### Task 10: Final verification and push

**Step 1: Verify all CDN URLs are gone from production code**

```bash
grep -rn 'cdn.jsdelivr.net\|code.iconify.design\|cdnjs.cloudflare' \
  backend/app/ frontend/src/ \
  --include='*.py' --include='*.ts' --include='*.tsx' \
  | grep -v '__pycache__'
```

Expected: no output (only remaining references should be in skill prompt `.md` files, which are AI-generated output templates, handled separately).

**Step 2: Verify vendor files are present**

```bash
ls -lh frontend/public/vendor/echarts.min.js \
       frontend/public/vendor/reveal.js/reveal.min.js \
       frontend/public/vendor/reveal.js/reveal.min.css \
       frontend/public/vendor/reveal.js/theme/black.min.css
```

**Step 3: Push branch**

```bash
git push origin feat/offline-deploy
```

---

## Offline Delivery Checklist

On the internet-connected build machine:
```bash
bash scripts/download-vendors.sh   # already done if vendors are committed
docker compose build
docker save \
  presentationagent-frontend \
  presentationagent-backend \
  jgraph/drawio:24 \
  -o offline-bundle.tar
```

On the air-gapped target machine:
```bash
docker load -i offline-bundle.tar
cp .env.offline .env
# Edit .env: set LLM_BASE_URL, LLM_API_KEY, INTRANET_SEARCH_URL
docker compose up -d
```
