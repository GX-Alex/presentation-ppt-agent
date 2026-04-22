# 通用智能体平台一阶段执行计划（v1.1）

**TL;DR**: 基于 V3.1 需求文档，将一阶段拆为 **7 个 Sprint**（每 Sprint 约 3-5 天，总计 ~30 个工作日）。核心策略是 **"纵切为主先通后精"**——Sprint 1-3 打通"对话→PPT生成→预览→导出"最小完整链路，Sprint 4-5 补全记忆/技能/编辑三大横切能力，Sprint 6-7 完成资产画廊与工程收尾。每个 Sprint 产出可独立演示的增量，避免长周期集成风险。

关键技术决策：
- SQLite + 本地文件存储贯穿一阶段，Schema 预留 `user_id` 但不实现鉴权
- 前后端通过 Docker Compose 一键拉起，前端 Next.js 通过 `/api` 反代到 FastAPI
- LLM 调用统一走 `litellm`，从第一天就做好模型切换能力
- reveal.js 运行在 `<iframe>` 内，通过 `postMessage` 与主应用通信

---

## Sprint 0: 工程脚手架与基础设施（2天）

**目标**: 项目结构初始化、Docker 环境、CI 基础、DB Schema 落库。

### Steps

1. 创建 monorepo 目录结构：
   ```
   generalagent/
   ├── backend/          (FastAPI)
   │   ├── app/
   │   │   ├── core/     (agent_loop, llm_client, tool_dispatch)
   │   │   ├── tools/    (每个 tool 一个文件)
   │   │   ├── skills/   (系统预置 .md)
   │   │   ├── api/      (REST routes)
   │   │   ├── ws/       (WebSocket handlers)
   │   │   ├── models/   (SQLAlchemy/Pydantic models)
   │   │   └── services/ (业务逻辑层)
   │   ├── data/         (SQLite DB + uploads + exports)
   │   ├── requirements.txt
   │   ├── Dockerfile
   │   └── main.py
   ├── frontend/         (Next.js 15)
   │   ├── src/app/      (App Router: chat/[id], assets, gallery, settings)
   │   ├── src/components/
   │   ├── src/hooks/
   │   ├── src/lib/      (ws client, api client)
   │   ├── src/stores/   (Zustand 全局状态)
   │   ├── package.json
   │   └── Dockerfile
   ├── docker-compose.yml
   └── requirement_doc.md
   ```

2. FastAPI 骨架：`main.py` 入口 + CORS + 静态文件 + WebSocket endpoint `/ws/chat`；健康检查 `/health`

3. Next.js 15 初始化：App Router + Tailwind + shadcn/ui；创建 4 个页面占位（`/chat/[id]`, `/assets`, `/gallery`, `/settings`）；左侧导航栏布局壳子

4. 数据库 Schema：用 SQLAlchemy + Alembic 管理迁移，一次性建表——`users`、`tasks`、`task_messages`、`task_checkpoints`、`assets`、`gallery_items`、`user_skills`、`user_memories`、`document_chunks`、`presentations`、`slides`、`slide_versions`（完全对齐需求文档第八章）

5. Docker Compose：`backend` + `frontend` 两个 service，前端 `next.config.js` 配 rewrites 代理 `/api/*` 和 `/ws/*` 到 backend

6. `litellm` 封装：`app/core/llm_client.py`，统一暴露 `async def chat(system, messages, tools, model=None) -> LLMResponse`，支持环境变量切换模型

7. **依赖版本强锁定**：`requirements.txt` 中所有依赖使用 `==` 精确锁定到 patch 版本；`package.json` 中禁止使用 `^` 或 `~`，全部采用精确版本号。提交 `package-lock.json` / `requirements.txt` 到版本控制，保证任何环境下的复现一致性

**验证**: `docker compose up` 一键拉起，浏览器访问 `localhost:3000` 看到 Next.js 壳页面，`/health` 返回 200，SQLite DB 文件生成且表结构正确。

---

## Sprint 1: Agent 主循环 + 通用对话（3天）

**目标**: 实现 `agent_loop` 核心引擎 + WebSocket 双向通信 + 前端对话基础 UI，可以进行通用聊天。

### Steps

1. 实现 `app/core/agent_loop.py`——完全对齐需求 2.2 伪代码：`while True` → `llm.chat()` → 检查 `stop_reason` → `dispatch_tool()` → 持久化 → WebSocket 推送。关键：这个循环从第一天就不应该再改，所有能力通过 Tool 扩展

2. 实现 `app/core/tool_dispatch.py`——Tool 注册表（dict-based），自动从 `app/tools/` 扫描注册。每个 Tool 是一个 Python 文件暴露 `TOOL_DEFINITION`（JSON Schema）和 `async def execute(params) -> dict`

3. WebSocket Handler (`app/ws/chat_handler.py`)——接收 `ClientMessage`，创建/恢复 Task，启动 `agent_loop`，流式推送 `ServerMessage`。消息类型严格对齐需求第九章

4. 前端 Chat 页面核心：
   - `useWebSocket` hook：连接管理、自动重连（指数退避 1s→2s→4s，上限 30s）、消息分发
   - **Zustand 全局状态管理**：创建 `src/stores/chatStore.ts`，管理消息列表、连接状态和任务元数据。所有 WebSocket 收到的消息统一写入 store，UI 组件纯消费 store 状态，杜绝 `useState` 散落导致的状态不一致
   - `ChatPanel` 组件：消息列表（支持 `message`、`status`、`thinking` 类型渲染）+ 输入框 + 发送
   - 消息持久化到 `task_messages` 表

5. 意图识别（轻量版）：在 system prompt 中指导 Agent 在首次回复时输出 `intent` 标记（如 `[INTENT:ppt]`），后端解析后推送 `intent_detected` 消息。**不引入独立分类模型**，依赖主模型 few-shot 判断即可

6. 实现第一个 Tool：`web_search`（接入 Tavily，fallback DuckDuckGo），验证 tool_use 循环能跑通

**验证**: 在浏览器中与 Agent 对话，Agent 能回复文字，能自主调用 `web_search` 搜索并总结结果返回。刷新页面后对话历史从 DB 恢复。

---

## Sprint 2: PPT 生成引擎 — 从大纲到预览（5天）

**目标**: 实现 PPT 核心链路——需求澄清 → `generate_ppt_deck` 统一规划与生成 → reveal.js 实时预览。

### Steps

1. 实现 `generate_ppt_deck` Tool：接收用户需求 + 参考文档摘要 + 主题要求，走 MiniMax zero-to-one 插件工作流，输出结构化页面蓝图、DeckSpec 和逐页预览数据。前端继续消费 `outline` 消息渲染可编辑大纲列表。

2. 在一次 `generate_ppt_deck` 调用中逐页生成幻灯片 HTML 与 speaker notes，并持续推送 `slide_ready` 事件；后续细改仍通过 `edit_slide` 完成。

3. 主题系统：3 个内置主题（`tech_dark`、`business_light`、`academic`）

4. **PPT 生成状态机（Zustand）**：`Idle → Outline_Pending → Outline_Ready → Generating(currentPage) → Completed → Editing`。断线重连基于 `message_id` 增量同步

5. 前端 Preview Panel：iframe + reveal.js + postMessage + 缩略图导航

6. TodoWrite 机制：计划列表 + 进度条

7. 需求澄清流程："直接生成" vs "先讨论"双路径

8. 数据持久化：`presentations` + `slides` 表

**验证**: 输入"帮我做一个10页的AI趋势PPT" → 全流程走通。断网重连后自动补齐。

---

## Sprint 3: 编辑系统 + 导出（4天）

**目标**: WYSIWYG 直接编辑 + 自然语言修改 + 版本控制 + 四种格式导出。

### Steps

1. WYSIWYG 编辑器：contentEditable + 浮动工具栏 + DOMPurify + compositionstart/end + 撤销栈 + Shadow DOM 隔离
2. 自然语言修改：`edit_slide` Tool
3. 版本控制：`slide_versions` 表 + 版本历史面板
4. 导出四件套：HTML / PDF / PPTX保真 / PPTX可编辑
5. **Playwright 浏览器实例池化**：`max_pages=3`，Semaphore 并发控制

**验证**: 编辑+导出全流程。同时 5 次 PDF 导出不 OOM。

---

## Sprint 4: Skill 体系 + 四层记忆（4天）

**目标**: Skill 两层加载 + 用户自定义 Skill + 四层记忆系统。

### Steps

1. 系统 Skill：6 个预置 .md + `load_skill` Tool + Layer 1 菜单注入
2. 用户自定义 Skill：CRUD API + 校验流程 + 作用域 + 冲突策略
3. 前端 Skill 管理（资产页 Skill Tab）
4. 四层记忆：Layer 0（上下文组装）、Layer 1（会话+checkpoint）、Layer 2（用户记忆+自动捕获+embedding）、Layer 3（文档向量索引）
5. 上下文压缩：70% 阈值 + 记忆刷盘
6. `/compact` 命令
7. **Token 预算监控与告警**：日志记录 + 85% 阈值告警 + 开发者模式 Token 计数器

**验证**: 自定义 Skill 全流程。长对话自动压缩+记忆刷盘。Token 日志与告警。

---

## Sprint 5: 文件上传与解析 + 搜索（3天）

**目标**: 文件上传 + 安全约束 + URL 抓取 + 图片搜索。

### Steps

1. 文件上传 API + 安全校验（白名单/大小/Zip Slip）
2. 文档解析 Tools：`parse_document` / `parse_project` / `read_project_file`
3. URL 抓取 + SSRF 防护
4. 图片搜索：Pexels API
5. 前端：📎 附件 + 拖拽 + URL 识别

**验证**: 多格式上传解析。安全校验拦截。

---

## Sprint 6: 资产管理 + 画廊（4天）

**目标**: 资产空间、画廊系统、页面间关联跳转。

### Steps

1. 资产管理后端 CRUD + 自动沉淀 + 缩略图
2. 资产管理前端（Tab 分类/筛选/卡片/跳转）
3. 画廊后端（发布/Fork/版本冻结/版权）
4. 画廊前端（Tab/卡片/预览/Fork）
5. 页面间关联链路（6 条跳转路径）
6. 设置页（记忆管理/模型选择/开发者模式+Token 计数/API Key）

**验证**: 生成→资产→画廊→Fork→发布 v2 全链路。

---

## Sprint 7: 工程收尾与质量保障（3天）

**目标**: 错误处理、边界情况、性能优化、文档、部署验证。

### Steps

1. 错误处理加固（超时/重试/重连/错误推送）
2. 前端收尾（侧边栏/任务记录/响应式/i18n 壳子）
3. 性能基线验证（首 token <2s / 单页 <15s / 导出 <30s / prompt token <85%窗口）
4. 安全 checklist 全面复验
5. Docker Compose 生产配置（Playwright 预装 + `max_pages` 环境变量 + .env.example + 数据卷 + 健康检查）
6. README

**验证**: 全新环境 clone → 一键启动 → 全链路走通。

---

## 关键风险与应对

| 风险 | 影响 | 应对策略 |
|---|---|---|
| reveal.js iframe 与主应用通信复杂度 | 编辑/翻页/缩略图三处耦合 | Sprint 2 第一天先做 iframe postMessage PoC |
| contentEditable 浏览器兼容性（尤其中文输入法） | WYSIWYG 编辑体验降级 | Sprint 3 首日做 PoC；若不可控降级为纯自然语言编辑 |
| PPTX 可编辑版排版还原度低 | 用户预期落空 | 导出按钮明确标注差异文案，先做保真版兜底 |
| SQLite 向量检索性能 | Layer 2/3 记忆检索慢 | embedding 降至 384 维 + numpy，<10k 条够用 |
| LLM 生成 HTML 质量不稳定 | 幻灯片样式崩坏 | 严格 HTML 模板 + few-shot + DOMPurify 清洗 |
| PPT 生成过程中网络断线 | 前端状态不一致 | Zustand 状态机 + message_id 增量同步 |
| 大量导出请求叠加 | Playwright OOM | 浏览器实例池化 + Semaphore 并发控制 |
| 上下文窗口膨胀导致费用失控 | Token 消耗不可预期 | 85% 阈值告警 + 自动压缩 + Token 计数器 |
| 依赖库版本漂移 | 构建产物不可复现 | 全量精确锁定版本号 + 提交 lock 文件 |

## 决策记录

- **SQLite + numpy**：零配置优先，Schema 预留 VECTOR 注释
- **reveal.js iframe**：样式隔离，避免 Tailwind/shadcn CSS 冲突
- **不引入独立意图分类模型**：主模型 few-shot 足够
- **embedding 用 all-MiniLM-L6-v2（384 维）**：本地运行，零外部依赖
- **纵切优先**：先通 PPT 全链路，再补横切能力
- **Zustand**：轻量（~1KB），适合 WebSocket 消息流驱动的复杂状态机
- **Playwright 池化**：复用实例降低冷启动延迟 60%+，Semaphore 限制内存上界
- **Token 监控用日志+阈值告警**：不引入 Prometheus/Grafana 重基础设施
