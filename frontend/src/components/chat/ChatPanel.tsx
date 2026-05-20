/**
 * ChatPanel 组件 — 对话面板，包含消息列表 + 输入框。
 * 位于聊天页面左侧 (~40%)。
 * 支持页面刷新后从 DB 恢复对话历史。
 */
"use client";

import { useEffect, useState } from "react";
import { useChatStore, type ChatMessage } from "@/stores/chatStore";
import { useDeckStore } from "@/stores/deckStore";
import { useDiagramStore } from "@/stores/diagramStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import { findLatestWorkspaceArtifact, parseWorkspaceArtifact } from "@/lib/artifacts";
import {
  toWebDeckGenerateBrief,
  type QualityGenerateBrief,
} from "@/lib/qualityGeneration";
import {
  buildShellPagesFromManifest,
  formatWebDeckManifestSummary,
  mapManifest,
  mapSummaryPages,
  normalizePageBundle,
  normalizeDeckStatus,
} from "@/lib/webdeck";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";

interface ChatPanelProps {
  /** 任务 ID（来自路由参数） */
  taskId: string;
}

export function ChatPanel({ taskId }: ChatPanelProps) {
  const { sendChat, sendWebDeckGenerate, sendAbort } = useWebSocket();
  const [showQualityDialog, setShowQualityDialog] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const connectionStatus = useChatStore((s) => s.connectionStatus);
  const currentTaskId = useChatStore((s) => s.taskId);
  const loadMessages = useChatStore((s) => s.loadMessages);
  const setTask = useChatStore((s) => s.setTask);
  const setCurrentArtifactType = useChatStore((s) => s.setCurrentArtifactType);
  const setArtifactContent = useChatStore((s) => s.setArtifactContent);
  const setHtmlArtifactContent = useChatStore((s) => s.setHtmlArtifactContent);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const resetPpt = useChatStore((s) => s.resetPpt);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const resetDeck = useDeckStore((s) => s.resetDeck);
  const hydrateDiagramSession = useDiagramStore((s) => s.hydrateSession);
  const resetDiagram = useDiagramStore((s) => s.resetDiagram);
  const setProjectId = useDeckStore((s) => s.setProjectId);
  const setDeckStatus = useDeckStore((s) => s.setDeckStatus);
  const setManifest = useDeckStore((s) => s.setManifest);
  const initPages = useDeckStore((s) => s.initPages);
  const setFinalHtml = useDeckStore((s) => s.setFinalHtml);
  const setGeneratingProgress = useDeckStore((s) => s.setGeneratingProgress);
  const addReview = useDeckStore((s) => s.addReview);

  // 当 taskId 变化时，清空旧消息并重新加载对应任务的历史
  useEffect(() => {
    // 先清空旧状态（包括取消流式输出和清除处理状态，防止跨会话残留）
    clearMessages();
    resetPpt();
    resetDeck();
    resetDiagram();
    setCurrentArtifactType("none");
    setArtifactContent(null);
    setLoadError(false);
    setIsHistoryLoading(taskId !== "new");
    useChatStore.setState((state) => ({
      isProcessing: state.processingTaskIds.includes(taskId),
    }));
    useChatStore.getState().cancelStream();
    // 清除上一个任务残留的子 Agent 执行步骤，防止跨会话内容污染
    useChatStore.getState().clearExecutionSteps();

    if (taskId === "new") {
      useChatStore.setState({ taskId: null, intent: null, isProcessing: false });
      return;
    }

    // 立即锁定目标 taskId，防止异步加载历史期间来自其他任务的 WS 事件写入当前会话
    useChatStore.setState({ taskId, intent: null });

    // 从 DB 加载该任务的历史消息
    (async () => {
      try {
        const taskResp = await fetch(`/api/tasks/${taskId}`);

        if (!taskResp.ok) {
          setLoadError(true);
          return;
        }
        const data = await taskResp.json();
        if (data.error) {
          setLoadError(true);
          return;
        }

        // 设置任务信息
        setTask(data.task_id, data.intent || undefined);

        // 将历史消息加载到 store
        let restored: ChatMessage[] = [];
        if (data.messages && data.messages.length > 0) {
          restored = data.messages.map(
            (m: { id: string; role: string; content: string; type?: string; created_at?: string }) => {
              const rawContent = m.content || "";
              let cleanedContent = rawContent;
              let artifactType: string | undefined;
              try {
                const parsedArtifact = parseWorkspaceArtifact(rawContent);
                if (parsedArtifact) {
                  cleanedContent = parsedArtifact.cleanedContent;
                  artifactType = parsedArtifact.artifactType;
                }
              } catch {
                // artifact 解析失败，使用原始内容
              }
              return {
                id: m.id,
                role: m.role as ChatMessage["role"],
                content: cleanedContent,
                type: m.type || "text",
                artifactType,
                timestamp: m.created_at ? new Date(m.created_at).getTime() : Date.now(),
              };
            }
          );
          loadMessages(restored);
        }

        const latestArtifact = findLatestWorkspaceArtifact(
          (data.messages || []).filter((m: { type?: string }) => !m.type || m.type === "text")
        );

        const webDeckResp = await fetch(`/api/webdeck/task/${taskId}`);
        const webDeckProject = webDeckResp.ok ? await webDeckResp.json() : null;

        if (webDeckProject?.project_id) {
          const projectId = webDeckProject.project_id as string;
          const [manifestResp, pagesResp, htmlResp, reviewsResp] = await Promise.all([
            fetch(`/api/webdeck/projects/${projectId}/manifest`),
            fetch(`/api/webdeck/projects/${projectId}/pages`),
            fetch(`/api/webdeck/projects/${projectId}/html`),
            fetch(`/api/webdeck/projects/${projectId}/reviews`),
          ]);

          const manifestPayload = manifestResp.ok ? await manifestResp.json() : null;
          const pagesPayload = pagesResp.ok ? await pagesResp.json() : [];
          const htmlPayload = htmlResp.ok ? await htmlResp.json() : null;
          const reviewsPayload: Array<{ level: "page" | "deck"; targetId: string; passed: boolean; score: number; issues: Array<{ level: string; message: string; suggestion?: string }>; suggestions: string[] }> = reviewsResp.ok ? await reviewsResp.json() : [];

          setProjectId(projectId);
          setDeckStatus(normalizeDeckStatus(webDeckProject.status));
          setGeneratingProgress(
            Number(webDeckProject.completed_pages || 0),
            Number(webDeckProject.total_pages || 0),
          );

          const pageDetailsByPageId = Array.isArray(pagesPayload)
            ? Object.fromEntries(
                pagesPayload
                  .filter((page: { page_id?: string; html?: string | null }) => page.page_id)
                  .map((page: { page_id: string; html?: string | null; page_bundle?: Record<string, unknown> | null }) => [
                    page.page_id,
                    {
                      html: page.html || "",
                      pageBundle: normalizePageBundle(page.page_bundle),
                    },
                  ])
              )
            : {};

          if (manifestPayload?.manifest) {
            const manifest = mapManifest(manifestPayload.manifest);
            setManifest(manifest);
            initPages(buildShellPagesFromManifest(manifest));

            const hasPersistedWebDeckOutline = restored.some(
              (message) => message.type === "outline" || message.content.includes("Web Deck 大纲已生成")
            );

            if (!hasPersistedWebDeckOutline) {
              loadMessages([
                ...restored,
                {
                  id: `restored-webdeck-outline-${projectId}`,
                  role: "assistant",
                  content: `Web Deck 大纲已生成 (${manifest.totalPages} 页)\n\n${formatWebDeckManifestSummary(manifest)}`,
                  type: "outline",
                  timestamp: Date.now(),
                },
              ]);
            }
          }

          if (Array.isArray(webDeckProject.pages) && webDeckProject.pages.length > 0) {
            initPages(mapSummaryPages(webDeckProject.pages, pageDetailsByPageId));
          }

          if (htmlPayload?.html) {
            setFinalHtml(htmlPayload.html);
          }

          // 恢复审稿记录
          if (Array.isArray(reviewsPayload) && reviewsPayload.length > 0) {
            for (const r of reviewsPayload) {
              addReview(r);
            }
          }

          setCurrentArtifactType("webdeck");
          setArtifactContent(null);
          return;
        }

        const diagramResp = await fetch(`/api/diagram-sessions/task/${taskId}`);
        const diagramPayload = diagramResp.ok ? await diagramResp.json() : null;
        if (diagramPayload?.exists && diagramPayload.session?.xml) {
          hydrateDiagramSession(diagramPayload.session);
          setCurrentArtifactType("drawio");
          setArtifactContent(diagramPayload.session.xml);
          return;
        }

        if (latestArtifact) {
          setCurrentArtifactType(latestArtifact.artifactType);
          setArtifactContent(latestArtifact.artifactContent);
          if (latestArtifact.artifactType === "webpage") {
            setHtmlArtifactContent(latestArtifact.artifactContent);
          }
        } else {
          setCurrentArtifactType("none");
          setArtifactContent(null);
        }
      } catch (err) {
        console.error("[ChatPanel] 恢复历史消息失败:", err);
        setLoadError(true);
      } finally {
        setIsHistoryLoading(false);
      }
    })();
  }, [taskId, clearMessages, resetPpt, resetDeck, resetDiagram, setTask, loadMessages, setCurrentArtifactType, setArtifactContent, setHtmlArtifactContent, hydrateDiagramSession, setProjectId, setDeckStatus, setManifest, initPages, setFinalHtml, setGeneratingProgress, addReview]);

  // 连接状态颜色
  const statusColor =
    connectionStatus === "connected"
      ? "bg-green-400"
      : connectionStatus === "connecting"
      ? "bg-yellow-400 animate-pulse"
      : "bg-red-400";

  const handleSend = (content: string) => {
    sendChat(content, currentTaskId || taskId);
  };

  const handleQualityGenerate = (brief: QualityGenerateBrief) => {
    if (connectionStatus !== "connected") {
      return false;
    }

    sendWebDeckGenerate(toWebDeckGenerateBrief(brief), currentTaskId || taskId);
    return true;
  };

  return (
    <div className="flex flex-col h-full relative">
      {/* 头部: Zen 极简标题 + 连接状态 */}
      <div className="px-5 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-gray-700">对话</h2>
          <span className="text-[11px] text-gray-400 font-medium">
            {currentTaskId
              ? `#${currentTaskId.slice(0, 8)}`
              : taskId === "new"
              ? "新任务"
              : `#${taskId.slice(0, 8)}`}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {isProcessing && (
            <button
              onClick={() => sendAbort(currentTaskId || undefined)}
              className="px-2.5 py-1.5 bg-red-50 hover:bg-red-100 text-red-600 text-xs rounded-lg transition-colors flex items-center gap-1 border border-red-200/60"
              title="终止当前任务"
            >
              <span>⏹</span> 终止
            </button>
          )}
          <span className={`w-2 h-2 rounded-full ${statusColor}`} />
          <span className="text-[11px] text-gray-400">
            {connectionStatus === "connected"
              ? "已连接"
              : connectionStatus === "connecting"
              ? "连接中"
              : "断开"}
          </span>
        </div>
      </div>

      {/* P1-5: 历史加载失败提示 */}
      {loadError && (
        <div className="mx-4 mb-2 px-4 py-3 bg-red-50 border border-red-200/60 rounded-xl flex items-center justify-between">
          <span className="text-sm text-red-600">历史消息加载失败</span>
          <button
            onClick={() => {
              setLoadError(false);
              // 触发重新加载 — 用一个小的状态翻转即可
              clearMessages();
              resetPpt();
              resetDeck();
              // 重走 useEffect 逻辑：手动 re-call
              window.location.reload();
            }}
            className="px-3 py-1 text-xs bg-white border border-red-200 text-red-600 rounded-lg hover:bg-red-100 transition-colors"
          >
            重试
          </button>
        </div>
      )}

      {/* 消息列表 */}
      <MessageList onSend={handleSend} onOpenQualityDialog={() => setShowQualityDialog(true)} isLoading={isHistoryLoading} />

      {/* 悬浮输入区域 */}
      <ChatInput
        onSend={handleSend}
        onQualityGenerate={handleQualityGenerate}
        showQualityDialog={showQualityDialog}
        onCloseQualityDialog={() => setShowQualityDialog(false)}
      />
    </div>
  );
}
