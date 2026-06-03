# 离线部署方案设计

**日期**: 2026-06-03  
**分支**: feat/offline-deploy  
**目标**: 支持企业内网环境的纯 Docker Compose 离线部署，无需任何外网访问

---

## 背景与约束

- 目标环境：企业内网，无公网访问
- 大模型调用：内网已有 LLM 代理，无需处理
- 部署方式：纯 Docker Compose，目标机器只需 Docker
- 浏览器要求：Chrome 90+（已通过 crypto.randomUUID polyfill 兼容）

---

## 一、整体架构

```
docker-compose.yml
├── frontend    — Next.js，内置 vendor 静态资源
├── backend     — FastAPI + Playwright Chromium
└── drawio      — jgraph/drawio:24，替代 embed.diagrams.net
```

**交付流程**：
1. 有网机器：`bash scripts/download-vendors.sh` → `docker compose build` → `docker save -o offline-bundle.tar`
2. 内网机器：`docker load -i offline-bundle.tar` → 配置 `.env.offline` → `docker compose up -d`

---

## 二、Runtime CDN 资源本地化

### Vendor 文件目录

```
frontend/public/vendor/
├── echarts.min.js
└── reveal.js/
    ├── reveal.min.js
    ├── reveal.min.css
    └── theme/black.min.css
```

由 Next.js 静态服务器暴露为 `/vendor/...`，后端生成的 iframe HTML 和前端 React 均从此路径加载。

### ECharts

- 影响文件：`artifact_composer.py`、`lane_runner.py`
- 改动：CDN URL 改为读取 `ECHARTS_JS_URL` 环境变量
- 默认值：`/vendor/echarts.min.js`

### Reveal.js

- 影响文件：`theme_manager.py`（后端）、`PreviewPanel.tsx`（前端）
- 改动：3 个文件路径改为读取 `REVEAL_JS_BASE_URL` / `NEXT_PUBLIC_REVEAL_JS_BASE_URL`
- 默认值：`/vendor/reveal.js`

### Iconify

- 影响文件：`artifact_composer.py`（2 个导航箭头图标）
- 改动：移除 iconify-icon.min.js 加载，替换为内联 SVG
- 原因：iconify 有两层网络请求（JS 加载 + 每个图标实时拉取 SVG），无法离线

---

## 三、服务配置层改动

### draw.io 容器

```yaml
# docker-compose.yml 新增
drawio:
  image: jgraph/drawio:24
  restart: unless-stopped
```

环境变量（前端已支持）：
```env
NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL=http://drawio:8080
NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL=http://drawio:8080
```

### 内网搜索适配器

在 `web_search.py` 优先级链头插入内网搜索：

```
内网搜索（INTRANET_SEARCH_URL 有值时）→ Tavily → DuckDuckGo
```

接口约定：POST `INTRANET_SEARCH_URL`，body `{"query": str, "max_results": int}`，
返回 `{"results": [{"title": str, "url": str, "snippet": str}]}`

### 禁用 Pexels / GitHub 插件注册表

```env
PEXELS_API_KEY=     # 留空 → image_search 返回空结果
GITHUB_TOKEN=       # 留空 → remote_package_sources 跳过远程拉取
```

需确保两处代码在 key 为空时优雅降级（不抛异常）。

---

## 四、构建打包流程

### 下载脚本：`scripts/download-vendors.sh`

```bash
#!/bin/bash
set -e
VENDOR_DIR="frontend/public/vendor"
mkdir -p "$VENDOR_DIR/reveal.js/theme"

curl -fL "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js" \
  -o "$VENDOR_DIR/echarts.min.js"

BASE="https://cdn.jsdelivr.net/npm/reveal.js@5.1.0/dist"
curl -fL "$BASE/reveal.min.js"       -o "$VENDOR_DIR/reveal.js/reveal.min.js"
curl -fL "$BASE/reveal.min.css"      -o "$VENDOR_DIR/reveal.js/reveal.min.css"
curl -fL "$BASE/theme/black.min.css" -o "$VENDOR_DIR/reveal.js/theme/black.min.css"

echo "✅ Vendor files downloaded"
```

vendor 文件提交进 git（约 1.3MB），`docker build` 时直接 COPY，不依赖构建时联网。

### 离线交付命令

```bash
# 有网机器（一次性）
bash scripts/download-vendors.sh
docker compose build
docker save presentationagent-frontend presentationagent-backend jgraph/drawio:24 \
  -o offline-bundle.tar

# 内网机器
docker load -i offline-bundle.tar
cp .env.offline .env
docker compose up -d
```

### .env.offline 模板

```env
# LLM（指向内网代理）
LLM_BASE_URL=http://your-llm-proxy/v1
LLM_API_KEY=your-key

# draw.io
NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL=http://drawio:8080
NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL=http://drawio:8080

# Vendor 静态资源
ECHARTS_JS_URL=/vendor/echarts.min.js
REVEAL_JS_BASE_URL=/vendor/reveal.js
NEXT_PUBLIC_REVEAL_JS_BASE_URL=/vendor/reveal.js

# 内网搜索
INTRANET_SEARCH_URL=http://your-es-host:9200/_search

# 禁用外网服务
PEXELS_API_KEY=
GITHUB_TOKEN=
TAVILY_API_KEY=
```

---

## 五、改动文件清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `scripts/download-vendors.sh` | 新建 | vendor 下载脚本 |
| `frontend/public/vendor/` | 新增目录+文件 | ECharts、Reveal.js 静态资源 |
| `.env.offline` | 新建 | 离线环境配置模板 |
| `docker-compose.yml` | 修改 | 新增 drawio 服务 |
| `backend/app/services/webdeck_runtime/artifact_composer.py` | 修改 | ECharts URL 环境变量化；Iconify 换内联 SVG |
| `backend/app/services/webdeck_runtime/lane_runner.py` | 修改 | ECharts URL 环境变量化 |
| `backend/app/services/theme_manager.py` | 修改 | Reveal.js URL 环境变量化 |
| `frontend/src/components/ppt/PreviewPanel.tsx` | 修改 | Reveal.js URL 读取环境变量 |
| `backend/app/tools/web_search.py` | 修改 | 新增内网搜索适配器 |
| `backend/app/tools/image_search.py` | 修改 | PEXELS_API_KEY 为空时优雅降级 |
| `backend/app/services/remote_package_sources.py` | 修改 | GITHUB_TOKEN 为空时跳过远程拉取 |
