# GeneralAgent 重构计划

## 问题诊断

### 问题1: 上下文工程差 — 对话分析结果在 web-deck 中未体现
- `collect_task_context_layers` 仅抓最近16条消息，分类粗糙（user_goals/assistant_findings/open_questions）
- 对话中的深度分析（市场研究、数据分析结论）被简化为短文本片段
- Planner prompt 将 context_layers 标记为 "framing only, not evidence"，对话洞察被排除在内容之外
- 无机制将对话中的结构化洞察标记为 "可用于deck内容"

### 问题2.1: 附件与高质量生成流程脱节
- chat 流中 `_inject_attachment_context()` 自动解析附件
- web-deck 流中 `brief["attachments"]` 仅包含用户在表单中显式添加的附件
- `chat_handler.py` 的 `webdeck_generate` 直接传递客户端brief，不会自动补充早期对话中上传的附件
- 用户上传PDF→讨论→触发web-deck时，PDF内容可能不会传递到规划阶段

### 问题2.2: 附件解析结果在演示正文中体现少
- `MATERIAL_EXCERPT_LIMIT = 360` 字符，截断过于严重
- 页面级别的 evidence_details 只有短摘要
- lane_runner 收到的证据信息更少
- 没有充分利用附件中的数据、图表、关键发现

### 问题3: 主智能体能力差距
- 无流式输出（llm_client.py 无 streaming）
- 页内 lane 串行执行（page_orchestrator 注释标注"当前串行，后续改并行"）
- MiniMax system role 转 user role 的脆弱 workaround
- 硬编码的金融模型逻辑（lane_runner）
- 单一大字符串 system prompt，非模块化组装
- 无中间件模式处理 agent 动作
- 50条消息限制
- tool result 截断过于激进（200字符）

## 参考项目关键学习

### deer-flow 最佳实践
1. **模块化 prompt 组装**: ~12个XML段（role, soul, memory, skills, subagent instructions等）动态组合
2. **多源工具组装**: 从 config/MCP/built-in/subagent/ACP 5个来源合并工具
3. **中间件模式**: loop_detection_middleware, subagent_limit_middleware
4. **协作式取消**: 子agent可协作取消
5. **延迟工具加载**: 工具按需加载而非全部预加载

## 重构方案

### Phase 1: 上下文工程重构 (context_service.py, presentation_briefing_service.py)

**1.1 增强对话上下文采集**
- 改进 `collect_task_context_layers`: 增加到32条消息，增加 `key_insights`/`data_findings`/`analysis_conclusions` 分类
- 新增 `collect_task_attachments`: 从 TaskMessage 中自动提取所有已解析的附件

**1.2 对话洞察可用于deck内容**
- 移除 "framing only" 限制，assistant_findings 和 key_insights 可作为 evidence
- 将对话中的结构化分析结果（数据、结论、建议）转化为 evidence_catalog 条目

**1.3 模块化系统 prompt 组装**
- 将 agent_loop.py 的大字符串 SYSTEM_PROMPT 拆分为独立模块
- 借鉴 deer-flow 的 XML section 模式动态组装

### Phase 2: 附件自动注入 web-deck (chat_handler.py, director.py, briefing_service.py)

**2.1 自动收集任务附件**
- 在 `chat_handler.py` 的 `webdeck_generate` 处理中，自动从任务历史中收集所有附件 Asset
- 将收集到的附件自动合并到 brief["attachments"]

**2.2 增加证据深度**
- 将 `MATERIAL_EXCERPT_LIMIT` 从 360 提升到 1500
- 为高价值页面提供完整附件内容（最高 6000 字符）
- 在 page 级别的 prompt 中更深入地引用证据内容

### Phase 3: Agent Loop 优化 (agent_loop.py, llm_client.py, tool_dispatch.py)

**3.1 流式输出支持**
- llm_client.py 增加 `chat_stream()` 方法
- agent_loop.py 支持增量推送 assistant content

**3.2 并行 lane 执行**
- page_orchestrator.py 中将 lane 执行改为 asyncio.gather 并行

**3.3 工具系统增强**
- 增加工具中间件机制（pre/post hooks）
- 增加工具执行超时和重试
- context_service 中 tool_result 截断提升到 500 字符

**3.4 上下文窗口优化**
- 消息限制从 50 提升到 80
- 智能截断策略（根据消息重要性决定截断程度）

## 实施顺序
1. Phase 1.1-1.2 (上下文工程) -- ✅ 已完成
2. Phase 2.1-2.2 (附件自动注入) -- ✅ 已完成
3. Phase 1.3 (模块化prompt) -- ✅ 已完成
4. Phase 3.1 (流式输出) -- ✅ 已完成
5. Phase 3.2 (并行lane) -- ✅ 已完成
6. Phase 3.3-3.4 (工具和上下文优化) -- ✅ 已完成
7. Phase 5 (Lead Agent Factory + Middleware) -- ✅ 已完成

## Phase 4: 多维度深度优化 (基于 deer-flow/opencode 最佳实践对标)

### 4.1 上下文智能截断 -- ✅ 已完成
- 按工具类型区分 tool_result 保留长度 (`TOOL_RESULT_CHAR_LIMITS`)
- web_search/fetch_url/parse_document 保留 1500-2000 字符，低价值工具仅 200-400
- 消息重要性评分 (`_score_message_importance`)：角色基础分 + 工具价值加分 + 位置衰减
- 低重要性消息额外缩减（仅保留 200 字符）
- 画像记忆选取从固定3条升级为按 confidence 排序的最多6条

### 4.2 循环检测中间件 -- ✅ 已完成
- `LoopDetector` 类：检测连续相同工具调用 + A↔B 交替模式
- 连续检测阈值 `LOOP_DETECT_THRESHOLD=3`，滑动窗口 `LOOP_DETECT_WINDOW=6`
- 首次触发注入 LLM 提示消息，第二次强制终止主循环
- 白名单机制：web_search↔fetch_url 等研究类组合不触发交替检测

### 4.3 协作式取消机制 -- ✅ 已完成
- 新增 `app/core/cancellation.py`：`CancellationToken` + `CooperativeCancelledError`
- 支持父子级联取消、超时自动取消、cleanup 资源清理
- page_orchestrator 的 `generate_page` / `_generate_simple` / `_generate_with_lanes` 均接受 token
- Per-lane 超时配置 (`LANE_TIMEOUT_DEFAULTS`)：narrative 90s, chart/diagram 60s, asset 45s

### 4.4 工具分类与过滤 -- ✅ 已完成
- `ToolCategory` 枚举: research/ppt/code/memory/media/utility/universal
- `TOOL_CATEGORIES` 映射每个工具到类别列表
- `INTENT_ALLOWED_CATEGORIES` 按意图限制可用工具类别
- `filter_tools_by_intent()` 在 agent_loop 主循环中按 task.intent 过滤

### 4.5 记忆系统增强 -- ✅ 已完成
- `search_memories` 新增时间衰减权重 (`time_decay=True`)
- 综合评分公式: similarity*0.7 + recency*0.2 + confidence*0.1
- 时间衰减半衰期 30 天，越新的记忆排名越靠前

### 4.6 动态 Prompt 组装 -- ✅ 已完成
- `build_base_system_prompt(intent=...)` 根据意图排除不相关 section
- research 意图跳过 ppt_rules，ppt 意图跳过 research_rules，chat 跳过两者
- agent_loop 主循环使用 `task.intent` 动态选择 prompt

## 已完成变更清单

### 修改的文件 (7个 → 8个)

| 文件 | 变更内容 |
|------|---------|
| `backend/app/services/presentation_briefing_service.py` | 上下文采集增强(32条消息, key_insights, data_findings), 证据深度提升(1200字符), 附件自动收集, evidence catalog增加content字段 |
| `backend/app/ws/chat_handler.py` | webdeck_generate自动注入任务附件 |
| `backend/app/core/agent_loop.py` | 模块化XML-section系统prompt, LoopDetector循环检测, 意图过滤工具列表, 动态prompt组装 |
| `backend/app/core/llm_client.py` | 新增chat_stream()流式输出异步生成器 |
| `backend/app/services/webdeck_runtime/page_orchestrator.py` | lane并行执行, CancellationToken集成, per-lane超时, asyncio.wait_for |
| `backend/app/core/tool_dispatch.py` | 工具中间件(pre/post hooks), 60秒超时, ToolCategory分类系统, filter_tools_by_intent |
| `backend/app/services/context_service.py` | 消息限制50→80, 智能截断(工具类型+重要性评分), 画像记忆选取增强 |
| `backend/app/services/memory_service.py` | search_memories 时间衰减加权 |
| `backend/app/core/cancellation.py` | **新增** CancellationToken + CooperativeCancelledError |

### 代码审查发现并修复的关键问题
- **C1**: chat_stream() 中 LLMResponse 字段传 None 而非空值 → 已修复为空字符串/空列表
- **C2**: asyncio.gather 共享 AsyncSession 并发安全问题 → 已修复为独立 session per lane
- **C3**: CancelledError 命名与 asyncio.CancelledError 冲突 → 已重命名为 CooperativeCancelledError
- **C4**: 循环检测器每轮重复触发未重置 → 已修复: 检测后清空历史 + 第二次强制终止
- **C5**: _generate_simple 未接收 cancellation_token → 已修复: 签名和调用均补充

### 已知待后续处理的 Warning 项
- W1: chat_stream() 缺少 retry/fallback 逻辑
- W2: 工具超时无法按工具粒度配置
- W3: pre-hook 返回 None 的歧义
- W5: 消息+截断限制同时增加可能超出token预算
- W6: CancellationToken cleanup 未在 GC 时自动调用 (建议 async context manager)
- W7: Scheduler 尚未传入 cancellation_token (功能已就绪但未接入调度层)
- W8: 动态插件工具始终通过意图过滤 (默认 UNIVERSAL 类别)

## Phase 5: Lead Agent Factory + Middleware 架构 (deer-flow 对标)

### 5.1 AgentMiddleware 协议 -- ✅ 已完成
- `agent_middleware.py`: `AgentContext` 数据类 + `AgentMiddleware` ABC + `MiddlewareChain`
- 7 个钩子点: on_request_start, on_before_llm, on_after_llm, on_tool_start, on_tool_end, on_round_end, on_request_end
- 洋葱模型: before 钩子正序执行, after 钩子反序执行
- insert_before/insert_after 支持动态插入 (对标 deer-flow @Prev/@Next)

### 5.2 Lead Agent Factory -- ✅ 已完成
- `agent_factory.py`: `AgentFactory` 按请求动态构建 Agent
- 根据意图 (intent) 组装不同的 MiddlewareChain
- 基础中间件 (所有意图): memory_capture → attachment_injection → tool_error → intent_detection → token_budget → loop_detection → checkpoint → brief_enrichment
- PPT/composite 意图追加: ppt_event
- 每次请求创建新的中间件实例，无跨请求状态泄漏

### 5.3 九个中间件实现 -- ✅ 已完成
- `agent_middlewares.py` 中实现:
  1. **MemoryCaptureMiddleware** — on_request_start 检测记忆信号 (对标 deer-flow MemoryMiddleware)
  2. **AttachmentInjectionMiddleware** — on_request_start 自动解析附件
  3. **LoopDetectionMiddleware** — on_tool_end 记录 + on_round_end 检测 (对标 deer-flow LoopDetectionMiddleware)
  4. **IntentDetectionMiddleware** — on_after_llm 提取 [INTENT:xxx] 标记
  5. **TokenBudgetMiddleware** — on_after_llm 推送用量 + 85% 阈值告警
  6. **CheckpointMiddleware** — on_round_end 每 5 轮保存检查点
  7. **PPTEventMiddleware** — on_tool_end 处理 generate_ppt_deck/edit_slide 事件
  8. **ToolErrorMiddleware** — on_tool_end 统一错误提示 (对标 deer-flow ToolErrorHandlingMiddleware)
  9. **BriefEnrichmentMiddleware** — on_request_start 从对话历史补充 brief (PPT 专用)

### 5.4 AgentRunner -- ✅ 已完成
- `agent_runner.py`: 重构后的主循环，完全委托横切关注点给中间件
- `agent_loop_v2()` 兼容入口，签名与原 `agent_loop()` 完全一致
- `chat_handler.py` 已切换到 `agent_loop_v2`

### 5.5 Prompt 模块独立 -- ✅ 已完成
- `agent_prompts.py`: PROMPT_SECTIONS + build_base_system_prompt + SYSTEM_PROMPT
- agent_loop.py 通过 re-export 保持向后兼容
- 消除 agent_runner.py → agent_loop.py 的循环依赖

### 已修改/新增的文件 (Phase 5)

| 文件 | 变更内容 |
|------|---------|
| `backend/app/core/agent_middleware.py` | **新增** AgentContext + AgentMiddleware + MiddlewareChain |
| `backend/app/core/agent_middlewares.py` | **新增** 9 个中间件实现 |
| `backend/app/core/agent_factory.py` | **新增** AgentFactory (Lead Agent Factory) |
| `backend/app/core/agent_runner.py` | **新增** AgentRunner + agent_loop_v2 |
| `backend/app/core/agent_prompts.py` | **新增** Prompt sections 独立模块 |
| `backend/app/core/agent_loop.py` | PROMPT_SECTIONS/build_base_system_prompt 改为 re-export |
| `backend/app/ws/chat_handler.py` | import 切换到 agent_runner.agent_loop_v2 |

### 代码审查发现并修复的问题 (Phase 5)
- **C2**: AgentContext.session 类型 `None` 安全性 → 添加注释说明始终由 Runner 提供
- **C3**: BriefEnrichmentMiddleware 仅在已知 PPT 意图时触发 → 改为始终加入基础链, 运行时自检意图
- **W1**: agent_runner.py 未使用的 count_tokens import → 已移除
- **W2**: agent_runner.py → agent_loop.py 循环依赖 → 提取 agent_prompts.py 独立模块
- **W4**: PPTEventMiddleware 未检查 blocked 工具 → 添加 `result.get("blocked")` 判断
- **W7**: ToolErrorMiddleware 无意义的 max_retries 参数 → 已移除
- **W8**: PPTEventMiddleware._handle_generate_ppt 无异常保护 → 添加 try/except 包装
