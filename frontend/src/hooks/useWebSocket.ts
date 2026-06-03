/**
 * useWebSocket Hook — 管理 WebSocket 连接生命周期。
 * 特性:
 *   - 全局单例 WebSocket（不因页面导航断开）
 *   - 自动重连（指数退避: 1s → 2s → 4s，上限 30s）
 *   - 消息分发到 Zustand 全局 store
 *   - 心跳保活（每 25 秒发送 ping）
 *   - 连接状态追踪
 */
"use client";

import { useEffect, useCallback } from "react";
import { useChatStore, type ChatMessage } from "@/stores/chatStore";
import { useDiagramStore } from "@/stores/diagramStore";
import {
  useDeckStore,
} from "@/stores/deckStore";
import { parseWorkspaceArtifact } from "@/lib/artifacts";
import type { DiagramSessionPayload } from "@/lib/diagramWsProtocol";
import {
  type WebDeckGenerateBrief,
} from "@/lib/qualityGeneration";
import {
  buildShellPagesFromManifest,
  formatWebDeckManifestSummary,
  mapManifest,
  normalizePageBundle,
  normalizeDeckStatus,
  normalizeLaneKind,
  normalizeLaneStatus,
  normalizePageKind,
  normalizePageStatus,
  type BackendWebDeckManifest,
} from "@/lib/webdeck";

// WebSocket 地址（Next.js rewrites 会代理到后端）
function getWsUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/ws/chat`;
}

// 重连配置
const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 30000;
const RECONNECT_MULTIPLIER = 2;
const HEARTBEAT_INTERVAL = 25000;
function normalizeWebDeckBrief(brief: WebDeckGenerateBrief): WebDeckGenerateBrief {
  return {
    ...brief,
    page_count: brief.page_count,
    extra: brief.extra,
  };
}

function _getScopedTaskId(data: Record<string, unknown>): string | undefined {
  const taskId = data.task_id;
  return typeof taskId === "string" && taskId.trim() ? taskId : undefined;
}

function _matchesCurrentTask(
  store: ReturnType<typeof useChatStore.getState>,
  taskId?: string,
): boolean {
  if (!taskId) return true;
  if (!store.taskId) return false;  // 未确认任务（"new" 页面）时拒绝所有带 task_id 的事件，避免跨会话污染
  return store.taskId === taskId;
}

function _markTaskProcessing(taskId?: string): void {
  const store = useChatStore.getState();
  if (taskId && taskId !== "new") {
    store.startTaskProcessing(taskId);
    return;
  }
  store.setIsProcessing(true);
}

function _finishTaskProcessing(taskId?: string): void {
  const store = useChatStore.getState();
  if (taskId) {
    store.finishTaskProcessing(taskId);
    return;
  }
  store.setIsProcessing(false);
}

function _readDiagramSession(data: Record<string, unknown>): DiagramSessionPayload | null {
  const session = data.session;
  if (!session || typeof session !== "object") {
    return null;
  }
  const payload = session as Record<string, unknown>;
  if (typeof payload.xml !== "string" || typeof payload.task_id !== "string") {
    return null;
  }
  return payload as unknown as DiagramSessionPayload;
}

// ── 模块级单例状态（不随组件卸载而销毁） ──
let _ws: WebSocket | null = null;
let _reconnectDelay = RECONNECT_BASE_DELAY;
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let _heartbeatTimer: ReturnType<typeof setInterval> | null = null;
let _isInitialized = false;
let _reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 10;

// ── 流式内容缓冲 — 合并高频 content_delta 为每帧一次更新，防止 React 超过 25 层嵌套渲染 ──
let _streamContentBuffer = "";
let _streamContentRafId: number | null = null;

function _flushStreamBuffer(): void {
  _streamContentRafId = null;
  if (_streamContentBuffer) {
    useChatStore.getState().appendStreamContent(_streamContentBuffer);
    _streamContentBuffer = "";
  }
}

function _cancelStreamBuffer(): void {
  if (_streamContentRafId !== null) {
    cancelAnimationFrame(_streamContentRafId);
    _streamContentRafId = null;
  }
  _streamContentBuffer = "";
}

// ── 子 Agent 流式内容缓冲 ──
const _subagentContentBuffers = new Map<string, string>();
const _subagentContentRafIds = new Map<string, number>();

// ── 断线消息保护 — 待发送消息队列 ──
type PendingMessage = { payload: string; addedAt: number };
const _pendingQueue: PendingMessage[] = [];
const PENDING_QUEUE_MAX = 20;
const PENDING_QUEUE_TTL = 5 * 60 * 1000; // 5 分钟过期

function _enqueuePending(payload: string): void {
  // 清理过期消息
  const now = Date.now();
  while (_pendingQueue.length > 0 && now - _pendingQueue[0].addedAt > PENDING_QUEUE_TTL) {
    _pendingQueue.shift();
  }
  if (_pendingQueue.length >= PENDING_QUEUE_MAX) {
    _pendingQueue.shift(); // 队列满则丢弃最旧的
  }
  _pendingQueue.push({ payload, addedAt: now });
}

function _flushPending(): void {
  if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
  const now = Date.now();
  while (_pendingQueue.length > 0) {
    const item = _pendingQueue.shift()!;
    if (now - item.addedAt > PENDING_QUEUE_TTL) continue; // 跳过过期
    _ws.send(item.payload);
  }
}

// ── 心跳管理 (含 pong 超时检测) ──
let _pongReceived = true;

// ── 心跳管理 ──
function _startHeartbeat(): void {
  _stopHeartbeat();
  _pongReceived = true;
  _heartbeatTimer = setInterval(() => {
    if (_ws?.readyState === WebSocket.OPEN) {
      if (!_pongReceived) {
        // 上一次 ping 未收到 pong，连接可能已死
        console.warn("[WS] Pong 超时，强制重连");
        _ws?.close(4000, "pong timeout");
        return;
      }
      _pongReceived = false;
      _ws.send(JSON.stringify({ type: "ping" }));
    }
  }, HEARTBEAT_INTERVAL);
}

function _stopHeartbeat(): void {
  if (_heartbeatTimer) {
    clearInterval(_heartbeatTimer);
    _heartbeatTimer = null;
  }
}

function _isWebDeckReviewRelatedMessage(message: string): boolean {
  return /审稿|review|修改方向|自动重试|max_words|字数|任务终止|未完成页面已停止/.test(message);
}

// ── webdeck_brief 自动触发 ──
const WEBDECK_BRIEF_REGEX = /<general-artifact\s+type="webdeck_brief">([\s\S]*?)<\/general-artifact>/i;

function _autoTriggerWebDeckGenerate(brief: WebDeckGenerateBrief, taskId?: string): void {
  if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
  const store = useChatStore.getState();
  const deckStore = useDeckStore.getState();
  deckStore.resetDeck();
  deckStore.setDeckStatus("planning");
  store.setCurrentArtifactType("webdeck");
  _markTaskProcessing(taskId || store.taskId || undefined);
  _ws.send(JSON.stringify({
    type: "webdeck_generate",
    brief: normalizeWebDeckBrief(brief),
    task_id: taskId || store.taskId || "new",
  }));
}

/** 检测 webdeck_brief artifact，自动触发生成流程，返回清理后的内容 */
function _detectAndTriggerWebDeckBrief(content: string, scopedTaskId?: string): string {
  const match = content.match(WEBDECK_BRIEF_REGEX);
  if (!match) return content;
  const raw = match[1].trim();
  try {
    const brief = JSON.parse(raw) as WebDeckGenerateBrief;
    _autoTriggerWebDeckGenerate(brief, scopedTaskId);
  } catch (e) {
    // JSON 非法时（通常是 pre_research.content 含未转义引号），后端 json_repair 会修复并完整触发。
    // 不做降级触发，避免以缺少 pre_research 的不完整 brief 抢先占位，阻断后端完整修复路径。
    console.warn("[WS] webdeck_brief JSON 解析失败，等待后端 json_repair 修复:", (e as Error).message);
  }
  return content.replace(WEBDECK_BRIEF_REGEX, "\n> 🎯 *正在启动 Web Deck 生成流程...*\n");
}

// ── 消息处理（使用 useChatStore.getState() 获取最新 store 引用） ──
function _handleMessage(event: MessageEvent): void {
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(event.data);
  } catch {
    console.error("[WS] 无法解析消息:", event.data);
    return;
  }

  const store = useChatStore.getState();
  const msgType = data.type as string;
  const scopedTaskId = _getScopedTaskId(data);
  const matchesCurrentTask = _matchesCurrentTask(store, scopedTaskId);

  switch (msgType) {
    case "stream_start": {
      if (!matchesCurrentTask) break;
      _cancelStreamBuffer();
      store.startStream(scopedTaskId || store.taskId || "unknown");
      break;
    }

    case "content_delta": {
      if (!matchesCurrentTask) break;
      _streamContentBuffer += (data.content as string) || "";
      if (_streamContentRafId === null) {
        _streamContentRafId = requestAnimationFrame(_flushStreamBuffer);
      }
      break;
    }

    case "stream_end": {
      if (!matchesCurrentTask) break;
      _cancelStreamBuffer();
      const messageId = (data.message_id as string) || "";
      let fullContent = (data.content as string) || "";
      const error = data.error as boolean | undefined;
      if (error) {
        // 流式出错，取消流
        store.cancelStream();
      } else {
        // 检测 webdeck_brief — 自动触发 Web Deck 生成流程
        fullContent = _detectAndTriggerWebDeckBrief(fullContent, scopedTaskId);
        // 检测并提取工作区 artifact，自动展示到右侧面板
        const parsedArtifact = parseWorkspaceArtifact(fullContent);
        if (parsedArtifact) {
          store.setCurrentArtifactType(parsedArtifact.artifactType);
          store.setArtifactContent(parsedArtifact.artifactContent);
          if (parsedArtifact.artifactType === "webpage") {
            store.setHtmlArtifactContent(parsedArtifact.artifactContent);
          }
          fullContent = parsedArtifact.cleanedContent;
        }
        store.finalizeStream(messageId, fullContent, undefined, parsedArtifact?.artifactType);
      }
      break;
    }

    case "message": {
      if (!matchesCurrentTask) break;
      let rawContent = (data.content as string) || "";

      // 检测 webdeck_brief — 自动触发 Web Deck 生成流程
      rawContent = _detectAndTriggerWebDeckBrief(rawContent, scopedTaskId);

      const parsedArtifact = parseWorkspaceArtifact(rawContent);
      if (parsedArtifact) {
        store.setCurrentArtifactType(parsedArtifact.artifactType);
        store.setArtifactContent(parsedArtifact.artifactContent);
        if (parsedArtifact.artifactType === "webpage") {
          store.setHtmlArtifactContent(parsedArtifact.artifactContent);
        }
        rawContent = parsedArtifact.cleanedContent;
      }

      const msg: ChatMessage = {
        id: (data.message_id as string) || crypto.randomUUID(),
        role: (data.role as ChatMessage["role"]) || "assistant",
        content: rawContent,
        type: (data.message_type as string) || "text",
        artifactType: parsedArtifact?.artifactType,
        timestamp: Date.now(),
      };
      store.addMessage(msg);
      break;
    }

    case "diagram_load":
    case "diagram_session_synced": {
      console.log("[DEBUG diagram_load]", {
        type: data.type,
        scopedTaskId,
        storeTaskId: store.taskId,
        matchesCurrentTask,
        hasSession: !!data.session,
        sessionXmlLen: typeof (data.session as Record<string, unknown>)?.xml === "string"
          ? ((data.session as Record<string, unknown>).xml as string).length
          : "N/A",
      });
      if (!matchesCurrentTask) break;
      const session = _readDiagramSession(data);
      if (!session) {
        console.log("[DEBUG diagram_load] _readDiagramSession returned null", data.session);
        break;
      }
      useDiagramStore.getState().hydrateSession(session);
      store.setCurrentArtifactType("drawio");
      store.setArtifactContent(session.xml);
      break;
    }

    case "thinking": {
      if (!matchesCurrentTask) break;
      store.addMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: (data.content as string) || "",
        type: "thinking",
        timestamp: Date.now(),
      });
      break;
    }

    case "status": {
      if (!matchesCurrentTask) break;
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: (data.text as string) || "",
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    case "task_info": {
      const taskId = data.task_id as string;
      if (taskId && (!store.taskId || store.taskId === taskId)) {
        store.startTaskProcessing(taskId);
        store.setTask(taskId, data.intent as string | undefined);
        store.clearExecutionSteps();
      }
      break;
    }

    case "intent_detected": {
      const intent = data.intent as string;
      const taskId = data.task_id as string;
      if (!matchesCurrentTask) break;
      if (taskId) store.setTask(taskId, intent);

      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `检测到意图: ${intent}`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    case "progress": {
      if (!matchesCurrentTask) break;
      const current = data.current as number;
      const total = data.total as number;
      if (current !== undefined && total !== undefined) {
        store.setGeneratingProgress(current, total);
      }
      break;
    }

    case "webdeck_status": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const projectId = data.project_id as string | undefined;
      const rawStatus = (data.status as string) || "failed";
      const message = (data.message as string) || "";

      if (projectId) {
        deckStore.setProjectId(projectId);
      }
      deckStore.setDeckStatus(normalizeDeckStatus(rawStatus));
      store.setCurrentArtifactType("webdeck");

      const shouldSurfaceStatus = !(rawStatus === "failed" && _isWebDeckReviewRelatedMessage(message));
      if (shouldSurfaceStatus) {
        store.addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: message ? `Web Deck 状态: ${rawStatus}\n${message}` : `Web Deck 状态: ${rawStatus}`,
          type: "status",
          timestamp: Date.now(),
        });
      }

      break;
    }

    case "webdeck_manifest": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const projectId = data.project_id as string | undefined;
      const manifest = mapManifest((data.manifest as BackendWebDeckManifest) || {});

      if (projectId) {
        deckStore.setProjectId(projectId);
      }
      deckStore.setManifest(manifest);
      deckStore.initPages(buildShellPagesFromManifest(manifest));
      store.setCurrentArtifactType("webdeck");
      store.addMessage({
        id: crypto.randomUUID(),
        role: "assistant",
        content: `Web Deck 大纲已生成 (${manifest.totalPages} 页)\n\n${formatWebDeckManifestSummary(manifest)}`,
        type: "outline",
        timestamp: Date.now(),
      });
      break;
    }

    case "webdeck_pages_init": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const projectId = data.project_id as string | undefined;
      const pages = Array.isArray(data.pages) ? (data.pages as Array<Record<string, unknown>>) : [];

      if (projectId) {
        deckStore.setProjectId(projectId);
      }
      deckStore.initPages(
        pages.map((page, index) => ({
          id: (page.id as string) || `page_${index + 1}`,
          pageIndex: typeof page.pageIndex === "number" ? (page.pageIndex as number) : index,
          title: (page.title as string) || `第 ${index + 1} 页`,
          kind: normalizePageKind(page.kind as string | undefined),
          status: normalizePageStatus(page.status as string | undefined),
          pageBundle: normalizePageBundle(page.page_bundle as Record<string, unknown> | undefined),
          lanes: [],
        }))
      );
      store.setCurrentArtifactType("webdeck");
      break;
    }

    case "webdeck_progress": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const current = data.current as number;
      const total = data.total as number;
      const pageId = data.page_id as string | undefined;

      if (current !== undefined && total !== undefined) {
        deckStore.setGeneratingProgress(current, total);
      }
      if (pageId) {
        deckStore.updatePageStatus(pageId, "running");
      }
      break;
    }

    case "webdeck_page_ready": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const pageId = data.page_id as string | undefined;
      const status = normalizePageStatus(data.status as string | undefined);
      const html = (data.html as string) || "";
      const title = (data.title as string) || "页面";
      const error = (data.error as string) || "";

      if (pageId) {
        if (status === "failed") {
          deckStore.updatePageStatus(pageId, "failed");
        } else {
          deckStore.updatePageHtml(
            pageId,
            html,
            normalizePageBundle(data.page_bundle as Record<string, unknown> | undefined),
          );
        }
      }

      if (status === "failed" && !_isWebDeckReviewRelatedMessage(error)) {
        store.addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: `Web Deck 页面生成失败: ${title}${error ? `\n${error}` : ""}`,
          type: "error",
          timestamp: Date.now(),
        });
      }
      break;
    }

    case "webdeck_lane_status": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const pageId = data.page_id as string | undefined;
      const laneId = data.lane_id as string | undefined;

      if (pageId && laneId) {
        deckStore.updateLaneStatus(
          pageId,
          laneId,
          normalizeLaneStatus(data.status as string | undefined),
          normalizeLaneKind(data.kind as string | undefined),
          undefined,
          data.error as string | undefined,
        );
      }
      break;
    }

    case "webdeck_complete": {
      _finishTaskProcessing(scopedTaskId);
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const html = (data.html as string) || "";
      const pageCount = (data.page_count as number) || deckStore.pages.length;

      deckStore.setFinalHtml(html);
      deckStore.setGeneratingProgress(pageCount, pageCount);
      store.setCurrentArtifactType("webdeck");
      break;
    }

    case "webdeck_review": {
      if (!matchesCurrentTask) break;
      const deckStore = useDeckStore.getState();
      const level = data.level === "deck" ? "deck" : "page";
      const targetId = (data.target_id as string)
        || (level === "deck" ? deckStore.projectId || "deck" : "unknown_page");
      const issues = Array.isArray(data.issues)
        ? (data.issues as Array<Record<string, unknown>>).map((issue) => ({
            level: String(issue.level || "warning"),
            message: String(issue.message || "审稿发现问题"),
            suggestion: issue.suggestion ? String(issue.suggestion) : undefined,
          }))
        : [];
      const suggestions = Array.isArray(data.suggestions)
        ? (data.suggestions as string[]).map((item) => String(item))
        : [];
      const passed = Boolean(data.passed);
      const retrying = Boolean(data.retrying);

      deckStore.addReview({
        level,
        targetId,
        passed,
        score: Number(data.score || 0),
        issues,
        suggestions,
        retrying,
      });
      break;
    }

    case "processing_done": {
      _finishTaskProcessing(scopedTaskId);
      if (matchesCurrentTask) {
        store.bulkCompleteExecutionSteps();
      }
      break;
    }

    case "error": {
      _finishTaskProcessing(scopedTaskId);
      if (!matchesCurrentTask) break;
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `❌ ${(data.message as string) || "未知错误"}`,
        type: "error",
        timestamp: Date.now(),
      });
      break;
    }

    case "pong":
      _pongReceived = true;
      break;

    // ──── Sprint 4: Skill/记忆/Token 事件处理 ────

    case "skill_loaded": {
      if (!matchesCurrentTask) break;
      const skillName = data.skill_name as string;
      const displayName = data.display_name as string;
      if (skillName) store.addActiveSkill(skillName);
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `🔌 已加载 Skill: ${displayName || skillName}`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    case "memory_captured": {
      if (!matchesCurrentTask) break;
      const category = data.category as string;
      const action = data.action as string;
      const memContent = data.content as string;
      store.addMemoryCaptured({
        category,
        action,
        content: memContent || "",
        timestamp: Date.now(),
      });
      if (action === "created") {
        store.setMemoryCount(store.memoryCount + 1);
      }
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `🧠 ${action === "updated" ? "更新" : "捕获"}记忆: [${category}] ${(memContent || "").slice(0, 60)}`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    case "token_usage": {
      if (!matchesCurrentTask) break;
      store.setTokenUsage({
        promptTokens: (data.prompt_tokens as number) || 0,
        completionTokens: (data.completion_tokens as number) || 0,
        totalTokens: (data.total_tokens as number) || 0,
        contextWindow: (data.context_window as number) || 128000,
        usageRatio: (data.usage_ratio as number) || 0,
        alert: (data.alert as boolean) || false,
        alertMessage: (data.alert_message as string) || "",
      });
      break;
    }

    case "token_alert": {
      if (!matchesCurrentTask) break;
      const alertMsg = data.message as string;
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: alertMsg || "⚠️ Token 用量接近上限",
        type: "error",
        timestamp: Date.now(),
      });
      break;
    }

    case "compact_done": {
      if (!matchesCurrentTask) break;
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `📦 上下文已压缩: ${data.compressed_count || 0} 条消息已归档`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    // ──── SubAgent 事件处理 ────

    case "subagent_start": {
      if (!matchesCurrentTask) break;
      store.addSubAgentToStep(`dispatch-auto`, {
        agentId: (data.agent_id as string) || "",
        agentType: (data.agent_type as string) || "",
        task: (data.task as string) || "",
        status: "running",
        currentRound: 0,
        maxRounds: 10,
        steps: [],
      });
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `子 Agent 已启动: ${data.agent_type}`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    case "subagent_progress": {
      if (!matchesCurrentTask) break;
      const agentId = data.agent_id as string;
      const detail = (data.detail as string) || "";
      store.updateSubAgent(agentId, {
        currentRound: (data.round as number) || 0,
      });
      // 添加迷你步骤到子 agent
      if (detail) {
        const existing = store.executionSteps
          .flatMap((s) => s.subAgents || [])
          .find((sa) => sa.agentId === agentId);
        if (existing) {
          store.updateSubAgent(agentId, {
            steps: [...existing.steps, {
              id: `${agentId}-${Date.now()}`,
              type: "status",
              status: "completed",
              title: detail,
            }],
          });
        }
      }
      break;
    }

    case "subagent_content_delta": {
      if (!matchesCurrentTask) break;
      const saId = data.agent_id as string;
      _subagentContentBuffers.set(saId, (_subagentContentBuffers.get(saId) || "") + ((data.content as string) || ""));
      if (!_subagentContentRafIds.has(saId)) {
        _subagentContentRafIds.set(saId, requestAnimationFrame(() => {
          const buffered = _subagentContentBuffers.get(saId) || "";
          _subagentContentBuffers.delete(saId);
          _subagentContentRafIds.delete(saId);
          if (!buffered) return;
          const s = useChatStore.getState();
          const existing = s.executionSteps
            .flatMap((step) => step.subAgents || [])
            .find((sa) => sa.agentId === saId);
          if (existing) {
            s.updateSubAgent(saId, { result: (existing.result || "") + buffered });
          }
        }));
      }
      break;
    }

    case "subagent_complete": {
      if (!matchesCurrentTask) break;
      const saIdComplete = data.agent_id as string;
      const saStatus = (data.status as string) === "completed" ? "completed" : "failed";

      // 取消该 agent 的待处理 rAF，防止旧 delta 在 summary 写入后追加
      const pendingRafId = _subagentContentRafIds.get(saIdComplete);
      if (pendingRafId !== undefined) {
        cancelAnimationFrame(pendingRafId);
        _subagentContentRafIds.delete(saIdComplete);
      }
      _subagentContentBuffers.delete(saIdComplete);

      store.updateSubAgent(saIdComplete, {
        status: saStatus as "completed" | "failed",
        duration: (data.duration_ms as number) || 0,
        result: (data.summary as string) || "",
      });
      // 如果所有子 agent 都完成了，更新 dispatch 步骤状态
      const freshState = useChatStore.getState();
      const allDone = freshState.executionSteps.every((step) => {
        if (step.type !== "subagent_dispatch") return true;
        return step.subAgents?.every((sa) => sa.status === "completed" || sa.status === "failed");
      });
      if (allDone) {
        const now = Date.now();
        useChatStore.setState((state) => ({
          executionSteps: state.executionSteps.map((step) =>
            step.type === "subagent_dispatch" && step.status === "running"
              ? { ...step, status: "completed" as const, duration: now - (step.startTime || now) }
              : step
          ),
        }));
      }
      store.addMessage({
        id: crypto.randomUUID(),
        role: "system",
        content: `子 Agent ${data.agent_type} ${saStatus === "completed" ? "完成" : "失败"} (${((data.duration_ms as number) || 0) / 1000}s)`,
        type: "status",
        timestamp: Date.now(),
      });
      break;
    }

    default:
      console.log("[WS] 未处理的消息类型:", msgType, data);
  }
}

// ── WebSocket 连接管理（模块级） ──
function _connect(): void {
  if (typeof window === "undefined") return;

  const url = getWsUrl();
  if (!url) return;

  useChatStore.getState().setConnectionStatus("connecting");

  const ws = new WebSocket(url);
  _ws = ws;

  ws.onopen = () => {
    console.log("[WS] 连接已建立");
    useChatStore.getState().setConnectionStatus("connected");
    _reconnectDelay = RECONNECT_BASE_DELAY;
    _reconnectAttempts = 0;
    _startHeartbeat();
    _flushPending();
  };

  ws.onmessage = _handleMessage;

  ws.onclose = (event) => {
    console.log(`[WS] 连接关闭: code=${event.code} reason=${event.reason}`);
    const store = useChatStore.getState();
    store.setConnectionStatus("disconnected");
    // 断线时重置处理状态，避免 UI 永远卡在 "处理中"
    store.setIsProcessing(false);
    // 取消流式输出
    if (store.streamingMessage) {
      store.cancelStream();
    }
    _cancelStreamBuffer();
    // 清理所有子 Agent 的待处理 rAF 和缓冲区
    _subagentContentRafIds.forEach((rafId) => cancelAnimationFrame(rafId));
    _subagentContentRafIds.clear();
    _subagentContentBuffers.clear();
    _stopHeartbeat();
    _ws = null;

    // 自动重连
    if (_isInitialized) {
      _reconnectAttempts++;
      if (_reconnectAttempts > MAX_RECONNECT_ATTEMPTS) {
        console.error(`[WS] 已超过最大重连次数 (${MAX_RECONNECT_ATTEMPTS})，停止重连`);
        store.addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: "网络连接已断开且多次重连失败，请检查网络后手动刷新页面。",
          type: "error",
          timestamp: Date.now(),
        });
        return;
      }
      console.log(`[WS] 将在 ${_reconnectDelay}ms 后重连 (第 ${_reconnectAttempts} 次)`);
      _reconnectTimer = setTimeout(() => {
        _reconnectDelay = Math.min(
          _reconnectDelay * RECONNECT_MULTIPLIER,
          RECONNECT_MAX_DELAY
        );
        _connect();
      }, _reconnectDelay);
    }
  };

  ws.onerror = (error) => {
    console.error("[WS] 连接错误:", error);
  };
}

function _initWebSocket(): void {
  if (_isInitialized) return;
  _isInitialized = true;
  _connect();
}

// ── 公开的 Hook ──

interface UseWebSocketReturn {
  sendChat: (content: string, taskId?: string) => void;
  sendDiagramAutosave: (xml: string, taskId?: string, extras?: { svg?: string | null; png?: string | null }) => void;
  sendWebDeckGenerate: (brief: WebDeckGenerateBrief, taskId?: string) => void;
  sendWebDeckApprove: (projectId: string, taskId?: string) => void;
  sendWebDeckRetryPage: (projectId: string, pageId: string, taskId?: string) => void;
  sendWebDeckRetryLane: (projectId: string, pageId: string, laneId: string, taskId?: string) => void;
  sendMode: (mode: "direct" | "discuss") => void;
  sendAbort: (taskId?: string) => void;
  disconnect: () => void;
}

export function useWebSocket(): UseWebSocketReturn {
  // 首次调用时初始化全局 WebSocket（组件卸载不关闭连接）
  useEffect(() => {
    _initWebSocket();
  }, []);

  const sendChat = useCallback(
    (content: string, taskId?: string) => {
      const payload = JSON.stringify({
        type: "chat",
        content,
        task_id: taskId || useChatStore.getState().taskId || "new",
      });

      useChatStore.getState().addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content,
        type: "text",
        timestamp: Date.now(),
      });
      _markTaskProcessing(taskId || useChatStore.getState().taskId || undefined);

      if (!_ws || _ws.readyState !== WebSocket.OPEN) {
        console.warn("[WS] 连接未就绪，消息已暂存");
        _enqueuePending(payload);
        useChatStore.getState().addMessage({
          id: crypto.randomUUID(),
          role: "system",
          content: "消息已暂存，恢复连接后自动发送",
          type: "status",
          timestamp: Date.now(),
        });
        return;
      }

      _ws.send(payload);
    },
    []
  );

  const sendDiagramAutosave = useCallback(
    (xml: string, taskId?: string, extras?: { svg?: string | null; png?: string | null }) => {
      const scopedTaskId = taskId || useChatStore.getState().taskId || undefined;
      useDiagramStore.getState().updateXml(xml, { syncStatus: _ws?.readyState === WebSocket.OPEN ? "dirty" : "error" });
      if (!_ws || _ws.readyState !== WebSocket.OPEN) {
        console.warn("[WS] 连接未就绪，diagram autosave 仅保留在本地状态");
        return;
      }

      _ws.send(
        JSON.stringify({
          type: "diagram_autosave",
          task_id: scopedTaskId || "new",
          xml,
          svg: extras?.svg || undefined,
          png: extras?.png || undefined,
        })
      );
    },
    []
  );

  const sendMode = useCallback((mode: "direct" | "discuss") => {
    if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
    _ws.send(JSON.stringify({ type: "mode", value: mode }));
  }, []);

  const sendAbort = useCallback((taskId?: string) => {
    const scopedTaskId = taskId || useChatStore.getState().taskId || undefined;
    if (!_ws || _ws.readyState !== WebSocket.OPEN) {
      _finishTaskProcessing(scopedTaskId);
      return;
    }
    _ws.send(JSON.stringify({ type: "abort", task_id: scopedTaskId }));
    _finishTaskProcessing(scopedTaskId);
  }, []);

  const disconnect = useCallback(() => {
    _isInitialized = false;
    if (_reconnectTimer) {
      clearTimeout(_reconnectTimer);
      _reconnectTimer = null;
    }
    _stopHeartbeat();
    _ws?.close(1000, "手动断开");
    _ws = null;
  }, []);

  // ── Web Deck 操作 ──

  const sendWebDeckGenerate = useCallback(
    (brief: WebDeckGenerateBrief, taskId?: string) => {
      if (!_ws || _ws.readyState !== WebSocket.OPEN) {
        console.warn("[WS] 连接未就绪，无法发送 WebDeck 生成请求");
        return;
      }

      const normalizedBrief = normalizeWebDeckBrief(brief);
      const store = useChatStore.getState();
      const deckStore = useDeckStore.getState();
      deckStore.resetDeck();
      store.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: `🎯 生成 Web Deck\n主题: ${normalizedBrief.topic}\n受众: ${normalizedBrief.audience || "通用"}\n页数: ${normalizedBrief.page_count || "自动"}`,
        type: "text",
        timestamp: Date.now(),
      });
      _markTaskProcessing(taskId || store.taskId || undefined);
      deckStore.setDeckStatus("planning");
      store.setCurrentArtifactType("webdeck");

      _ws.send(
        JSON.stringify({
          type: "webdeck_generate",
          brief: normalizedBrief,
          task_id: taskId || store.taskId || "new",
        })
      );
    },
    []
  );

  const sendWebDeckApprove = useCallback(
    (projectId: string, taskId?: string) => {
      if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
      const store = useChatStore.getState();
      store.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: "✅ 确认大纲，开始生成 Web Deck",
        type: "text",
        timestamp: Date.now(),
      });
      _markTaskProcessing(taskId || store.taskId || undefined);

      _ws.send(
        JSON.stringify({
          type: "webdeck_approve_plan",
          project_id: projectId,
          task_id: taskId || store.taskId || undefined,
        })
      );
    },
    []
  );

  const sendWebDeckRetryPage = useCallback(
    (projectId: string, pageId: string, taskId?: string) => {
      if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
      _markTaskProcessing(taskId || useChatStore.getState().taskId || undefined);
      _ws.send(
        JSON.stringify({
          type: "webdeck_retry_page",
          project_id: projectId,
          page_id: pageId,
          task_id: taskId || useChatStore.getState().taskId || undefined,
        })
      );
    },
    []
  );

  const sendWebDeckRetryLane = useCallback(
    (projectId: string, pageId: string, laneId: string, taskId?: string) => {
      if (!_ws || _ws.readyState !== WebSocket.OPEN) return;
      _markTaskProcessing(taskId || useChatStore.getState().taskId || undefined);
      _ws.send(
        JSON.stringify({
          type: "webdeck_retry_lane",
          project_id: projectId,
          page_id: pageId,
          lane_id: laneId,
          task_id: taskId || useChatStore.getState().taskId || undefined,
        })
      );
    },
    []
  );

  return {
    sendChat,
    sendDiagramAutosave,
    sendWebDeckGenerate,
    sendWebDeckApprove,
    sendWebDeckRetryPage,
    sendWebDeckRetryLane,
    sendMode,
    sendAbort,
    disconnect,
  };
}
