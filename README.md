# 智能演示平台 (Presentation Agent Platform)

> **一阶段聚焦 PPT/文档生成** 的通用 AI 智能体平台。  
> 核心理念：Agent Loop + Tool Dispatch + Skill 按需加载 + 四层记忆 + 上下文压缩。

---

## 目录

- [项目概述](#项目概述)
- [系统架构](#系统架构)
- [技术栈](#技术栈)
- [功能概览](#功能概览)
- [快速启动](#快速启动)
- [本地开发](#本地开发)
- [项目结构](#项目结构)
- [API 接口](#api-接口)
- [环境变量](#环境变量)
- [内置 Tool](#内置-tool)
- [测试与验证](#测试与验证)
- [安全说明](#安全说明)
- [开发路线](#开发路线)
- [许可证](#许可证)

---

## 项目概述

通用智能体平台采用 **learn-claude-code** 的核心理念构建：

| 理念 | 说明 | 本项目体现 |
|---|---|---|
| Agent Loop | `while + stop_reason + tool_dispatch` | 主循环不变，所有能力通过 Tool 扩展 |
| Tool Dispatch | 加工具只加 handler | 10 个内置 Tool，自动发现注册 |
| Skill | 两层懒加载 | 6 个系统 Skill + 用户自定义 |
| Subagent | 独立 `messages[]`，上下文隔离 | 每页幻灯片由独立子 Agent 生成 |
| TodoWrite | 可见计划提升完成率 | PPT 生成全程有计划列表 + 进度推送 |
| Compact | 上下文压缩 + 记忆刷盘 | 70% 阈值自动压缩，85% Token 告警 |

---

## 系统架构

```
┌───────────────────────────────────────────────────┐
│     Frontend (Next.js 15 + React 19 + Tailwind)    │
│  /chat/:id  │  /assets  │  /gallery  │  /settings  │
└──────────────────┬────────────────────────────────┘
                   │ WebSocket + REST (/api/*)
┌──────────────────▼────────────────────────────────┐
│         API Gateway (FastAPI + Uvicorn)             │
│  /ws/chat │ /api/health │ /api/tasks │ /api/files  │
│  /api/assets │ /api/gallery │ /api/skills          │
│  /api/presentations                                 │
└──────────────────┬────────────────────────────────┘
                   │
┌──────────────────▼────────────────────────────────┐
│         Coordinator Agent (主循环)                   │
│  意图识别 → 路由 → TodoWrite → Tool / Subagent      │
└──┬───────────────┬───────────────┬────────────────┘
   │               │               │
┌──▼──┐        ┌───▼──┐        ┌───▼──────┐
│ PPT │        │ 研究  │        │ 通用对话  │
│Agent│        │ Agent │        │ (直接LLM) │
└──┬──┘        └───┬──┘        └──────────┘
   │               │
┌──▼───────────────▼────────────────────────────────┐
│              Tool Layer（11 个内置工具）              │
│  web_search │ fetch_url │ generate_ppt_deck │ ...   │
└──────────────────┬────────────────────────────────┘
                   │
┌──────────────────▼────────────────────────────────┐
│              SQLite + 本地文件存储                    │
│  12 张表 │ data/uploads │ data/exports              │
└───────────────────────────────────────────────────┘
```

---

## 技术栈

| 层级 | 技术选型 |
|---|---|
| 后端 | Python 3.12, FastAPI 0.115.6, SQLAlchemy 2.0.36 (async), aiosqlite |
| LLM | litellm (默认 DeepSeek V3, 可选 Claude / GPT-4o) |
| 前端 | Next.js 15.1.4, React 19, TypeScript 5.7.3, Tailwind CSS 3.4.17 |
| 状态管理 | Zustand 5.0.3 |
| PPT 渲染 | reveal.js 5.x (iframe 隔离) |
| 文档解析 | PyMuPDF, python-docx, python-pptx, openpyxl |
| PDF/PPTX 导出 | Playwright headless (浏览器池化) |
| 图片搜索 | Pexels API |
| 数据库 | SQLite (预留 PostgreSQL 扩展) |
| 部署 | Docker Compose |

---

## 功能概览

### Sprint 0-1: 工程基础 + 对话引擎
- FastAPI + Next.js 全栈脚手架
- Agent Loop 主循环 + WebSocket 双向通信
- 12 张 ORM 表 + 自动建表
- WebSocket 指数退避重连 (1s→2s→4s, 上限 30s)
- 意图识别 (ppt / research / code_analysis / chat)

### Sprint 2: PPT 生成引擎
- 需求澄清 → 大纲生成 → Subagent 逐页生成
- reveal.js 实时预览 + 缩略图导航
- 3 个内置主题 (tech_dark / business_light / academic)
- TodoWrite 进度推送

### Sprint 3: 编辑 + 导出
- WYSIWYG contentEditable 编辑器
- 自然语言修改 (edit_slide Tool)
- 版本控制 (slide_versions 表)
- 四种导出: HTML / PDF / PPTX保真 / PPTX可编辑
- Playwright 浏览器实例池化 (Semaphore 并发控制)

### Sprint 4: Skill 体系 + 四层记忆
- 6 个系统 Skill + 用户自定义 Skill CRUD
- 四层记忆: 上下文组装 → 会话+checkpoint → 用户记忆 → 文档向量
- 上下文压缩 (70% 阈值 + 记忆刷盘)
- Token 预算监控 (85% 阈值告警 + 开发者 Token 计数器)

### Sprint 5: 文件上传与解析
- 文件上传 + 安全校验 (白名单 / 大小限制 / Zip Slip 防护)
- 5 个解析 Tool (parse_document / parse_project / read_project_file / fetch_url / web_search)
- 前端 📎 附件 + 拖拽上传

### Sprint 6: 资产管理 + 画廊
- 资产空间 CRUD + 自动沉淀 + 缩略图
- 画廊: 发布 / Fork / 版本冻结
- 设置页: API Key 管理 + 模型选择
- 6 条页面间关联跳转路径

### Sprint 7: 工程收尾与质量保障
- 全局错误处理中间件 (超时 / 重试 / 错误推送)
- 响应式侧边栏 (桌面折叠 + 移动端覆盖层)
- i18n 国际化壳 (zh-CN 语言包)
- 性能基线验证脚本
- 安全 checklist 自动检测
- Docker 生产配置 (内存限制 / 参数化端口 / 健康检查)

---

## 快速启动

### 前置条件
- Docker & Docker Compose
- LLM API Key (DeepSeek / OpenAI / Anthropic 任选其一)

### 一键启动

```bash
# 1. 克隆项目
git clone <repo-url> && cd generalagent

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 LLM_API_KEY

# 3. 启动服务
docker compose up -d

# 4. 访问应用
# 前端: http://localhost:3000
# 后端: http://localhost:8000/api/health
```

### 自定义端口

```bash
BACKEND_PORT=9000 FRONTEND_PORT=4000 docker compose up -d
```

---

## 本地开发

### 后端

```bash
cd backend

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright Chromium（导出功能需要）
playwright install chromium

# 启动开发服务器（自动重载）
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 访问 http://localhost:3000
```

### 前后端联调

前端 `next.config.js` 已配置 API 反代：
- `/api/*` → `http://localhost:8000/api/*`
- `/ws/*` → `ws://localhost:8000/ws/*`

---

## 项目结构

```
generalagent/
├── backend/                     # FastAPI 后端
│   ├── main.py                  # 应用入口 + 生命周期管理
│   ├── config.py                # 配置（环境变量读取）
│   ├── requirements.txt         # Python 依赖（精确锁定版本）
│   ├── Dockerfile               # 后端容器（含 Playwright）
│   ├── app/
│   │   ├── core/                # 核心引擎
│   │   │   ├── agent_loop.py    #   Agent 主循环
│   │   │   ├── llm_client.py    #   LLM 统一调用（litellm）
│   │   │   ├── tool_dispatch.py #   Tool 注册表 + 自动发现
│   │   │   └── error_handling.py#   全局错误处理 + 重试 + 超时
│   │   ├── tools/               # 11 个内置 Tool
│   │   │   ├── web_search.py    #   网页搜索
│   │   │   ├── fetch_url.py     #   URL 抓取
│   │   │   ├── generate_ppt_deck.py # PPT 整稿生成（MiniMax zero-to-one）
│   │   │   ├── edit_slide.py    #   自然语言修改幻灯片
│   │   │   ├── image_search.py  #   Pexels 图片搜索
│   │   │   ├── load_skill.py    #   Skill 按需加载
│   │   │   ├── parse_document.py#   文档解析
│   │   │   ├── parse_project.py #   项目结构解析
│   │   │   ├── read_project_file.py # 读取项目文件
│   │   │   ├── save_to_memory.py # 写入长期记忆
│   │   │   └── search_memory.py # 搜索历史记忆
│   │   ├── skills/              # 系统预置 Skill（.md）
│   │   ├── api/                 # REST 路由
│   │   │   ├── health.py        #   GET /api/health
│   │   │   ├── tasks.py         #   任务 CRUD
│   │   │   ├── files.py         #   文件上传 + 安全校验
│   │   │   ├── assets.py        #   资产管理
│   │   │   ├── gallery.py       #   画廊（发布/Fork）
│   │   │   ├── skills.py        #   Skill CRUD
│   │   │   └── presentations.py #   演示文稿
│   │   ├── ws/                  # WebSocket
│   │   │   └── chat_handler.py  #   对话处理 + Agent 调度
│   │   ├── models/              # 数据模型
│   │   │   ├── database.py      #   SQLAlchemy async 引擎
│   │   │   ├── orm.py           #   12 张 ORM 表
│   │   │   └── schemas.py       #   Pydantic 请求/响应模型
│   │   └── services/            # 业务逻辑
│   │       ├── asset_service.py #   资产沉淀 + 缩略图
│   │       ├── browser_pool.py  #   Playwright 浏览器池
│   │       ├── context_service.py#  上下文组装 + 压缩
│   │       ├── memory_service.py#   四层记忆管理
│   │       ├── skill_service.py #   Skill 加载 + 管理
│   │       └── export_service.py#   导出（HTML/PDF/PPTX）
│   ├── data/                    # 运行时数据
│   │   ├── generalagent.db      #   SQLite 数据库
│   │   ├── uploads/             #   用户上传文件
│   │   └── exports/             #   导出文件
│   ├── perf_baseline.py         # 性能基线脚本
│   ├── security_checklist.py    # 安全 checklist 脚本
│   └── quick_test_sprint*.py    # 各 Sprint 验证脚本
├── frontend/                    # Next.js 前端
│   ├── src/
│   │   ├── app/                 # App Router 页面
│   │   │   ├── chat/            #   /chat/:id 对话页
│   │   │   ├── assets/          #   /assets 资产管理
│   │   │   ├── gallery/         #   /gallery 画廊
│   │   │   └── settings/        #   /settings 设置
│   │   ├── components/          # React 组件
│   │   │   ├── layout/          #   Sidebar 侧边栏（响应式）
│   │   │   ├── chat/            #   对话面板
│   │   │   └── ppt/             #   PPT 预览 + 编辑
│   │   ├── hooks/               # 自定义 Hook
│   │   │   └── useWebSocket.ts  #   WebSocket 连接管理
│   │   ├── stores/              # Zustand 状态
│   │   │   └── chatStore.ts     #   对话状态机
│   │   └── lib/                 # 工具库
│   │       └── i18n.ts          #   国际化（zh-CN）
│   ├── package.json             # Node 依赖（精确锁定版本）
│   └── Dockerfile               # 前端容器
├── docker-compose.yml           # 一键编排（含资源限制 + 健康检查）
├── .env.example                 # 环境变量模板
└── README.md                    # 本文件
```

---

## API 接口

### 健康检查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务健康状态 |

### 任务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/tasks/{task_id}` | 任务详情 |
| DELETE | `/api/tasks/{task_id}` | 删除任务 |

### 文件

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/files/upload` | 上传文件（安全校验） |
| GET | `/api/files/{file_id}` | 获取文件信息 |

### 资产

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/assets` | 资产列表（分页 + 筛选） |
| GET | `/api/assets/{asset_id}` | 资产详情 |
| PUT | `/api/assets/{asset_id}` | 更新资产 |
| DELETE | `/api/assets/{asset_id}` | 删除资产 |
| POST | `/api/assets/{asset_id}/settle` | 手动沉淀 |

### 画廊

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/gallery` | 画廊列表 |
| POST | `/api/gallery/publish` | 发布到画廊 |
| POST | `/api/gallery/{item_id}/fork` | Fork 作品 |
| GET | `/api/gallery/{item_id}` | 画廊详情 |
| DELETE | `/api/gallery/{item_id}` | 删除画廊项 |

### Skill

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills` | Skill 列表 |
| POST | `/api/skills` | 创建自定义 Skill |
| PUT | `/api/skills/{skill_id}` | 更新 Skill |
| DELETE | `/api/skills/{skill_id}` | 删除 Skill |

### 演示文稿

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/presentations/{pres_id}` | 获取演示文稿 |
| POST | `/api/presentations/{pres_id}/export` | 导出(html/pdf/pptx) |

### WebSocket

| 路径 | 说明 |
|---|---|
| `ws://host/ws/chat` | 对话 WebSocket (JSON 消息) |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_API_KEY` | (必填) | LLM 服务 API Key |
| `LLM_MODEL` | `deepseek/deepseek-chat` | 默认模型 |
| `LLM_BASE_URL` | (可选) | 自定义 API 端点 |
| `MODEL_CONTEXT_WINDOW` | `128000` | 模型上下文窗口大小 |
| `PEXELS_API_KEY` | (可选) | Pexels 图片搜索 |
| `TAVILY_API_KEY` | (可选) | Tavily 搜索引擎 |
| `CORS_ORIGINS` | `http://localhost:3000` | 允许的跨域来源 |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/generalagent.db` | 数据库连接 |
| `PLAYWRIGHT_MAX_PAGES` | `3` | 浏览器池最大页面数 |
| `BACKEND_PORT` | `8000` | 后端服务端口 |
| `FRONTEND_PORT` | `3000` | 前端服务端口 |
| `NODE_ENV` | `development` | 前端运行环境 |

完整列表见 `.env.example`。

---

## 内置 Tool

| Tool | 说明 |
|---|---|
| `web_search` | 网页搜索 (Tavily / DuckDuckGo) |
| `fetch_url` | URL 内容抓取 (含 SSRF 防护) |
| `generate_ppt_deck` | PPT 整稿生成 (MiniMax zero-to-one) |
| `edit_slide` | 自然语言修改幻灯片 |
| `image_search` | 图片搜索 (Pexels API) |
| `load_skill` | Skill 按需加载 |
| `parse_document` | 文档解析 (PDF/Word/PPT/Excel/MD) |
| `parse_project` | 项目/压缩包结构解析 |
| `read_project_file` | 读取项目中的指定文件 |
| `save_to_memory` | 写入用户长期记忆 |
| `search_memory` | 搜索历史记忆 |

---

## 测试与验证

### 自动化测试脚本

```bash
cd backend
source .venv/bin/activate

# Sprint 各阶段验证（后端启动后运行）
python quick_test.py             # Sprint 1-3 基础测试
python quick_test_sprint4.py     # Sprint 4 Skill + 记忆
python quick_test_sprint7.py     # Sprint 7 工程质量

# 性能基线（无需启动后端）
python perf_baseline.py

# 安全 checklist（无需启动后端）
python security_checklist.py
```

### 性能基线指标

| 指标 | 目标 |
|---|---|
| 首 Token 延迟 | < 2s |
| 单页 PPT 生成 | < 15s |
| 导出（PDF/PPTX） | < 30s |
| Prompt Token 占比 | < 85% 上下文窗口 |
| DB 查询 | < 100ms |
| FastAPI 启动 | < 2000ms |

### TypeScript 类型检查

```bash
cd frontend && npx tsc --noEmit
```

---

## 安全说明

- **文件上传**: 扩展名白名单 + 文件大小限制 + Zip Slip 防护 + sanitize_filename
- **CORS**: 白名单域名控制
- **输入验证**: Pydantic 模型全覆盖
- **错误处理**: 生产环境不泄露堆栈信息
- **SSRF 防护**: URL 抓取过滤内网地址
- **WebSocket**: JSON 解析异常处理 + 结构化错误推送

---

## 开发路线

| Sprint | 周期 | 内容 | 状态 |
|---|---|---|---|
| 0 | 2天 | 工程脚手架 + 基础设施 | ✅ |
| 1 | 3天 | Agent 主循环 + 通用对话 | ✅ |
| 2 | 5天 | PPT 生成引擎 | ✅ |
| 3 | 4天 | 编辑系统 + 导出 | ✅ |
| 4 | 4天 | Skill 体系 + 四层记忆 | ✅ |
| 5 | 3天 | 文件上传与解析 | ✅ |
| 6 | 4天 | 资产管理 + 画廊 | ✅ |
| 7 | 3天 | 工程收尾与质量保障 | ✅ |

---

## 许可证

本项目仅供内部使用。
