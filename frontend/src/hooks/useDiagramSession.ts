"use client";

import { useCallback } from "react";

import { useWebSocket } from "@/hooks/useWebSocket";
import { useChatStore } from "@/stores/chatStore";
import { useDiagramStore } from "@/stores/diagramStore";


function buildRetryPrompt(): string | null {
  const validation = useDiagramStore.getState().validationState;
  if (!validation) {
    return null;
  }

  const issues = (validation.issues || [])
    .slice(0, 5)
    .map((issue, index) => {
      const cellRef = issue.cell_id ? ` [cell:${issue.cell_id}]` : "";
      const suggestion = issue.suggestion ? `；建议：${issue.suggestion}` : "";
      return `${index + 1}. ${issue.level.toUpperCase()} ${issue.message}${cellRef}${suggestion}`;
    })
    .join("\n");
  const suggestions = (validation.suggestions || []).slice(0, 3).join("；");
  return [
    "请基于当前任务的 diagram session 修正 draw.io 图。",
    "先调用 get_current_diagram，再优先用 edit_diagram；只有图明显不完整时才用 append_diagram。",
    "不要无关重建，也不要声称看过图片；当前模型只能依据结构化审稿结果修图。",
    issues ? `当前问题:\n${issues}` : "当前存在布局或可读性问题，请先读取 validation。",
    suggestions ? `优先建议：${suggestions}` : "请修复重叠、截断、缺失连线或拥挤布局。",
    "如果修正后 validation.retry_recommended 仍为 true，可以继续重试，但总次数不要超过 3 次。",
  ].join("\n\n");
}


export function useDiagramSession() {
  const { sendChat } = useWebSocket();
  const taskId = useChatStore((s) => s.taskId);
  const setCurrentArtifactType = useChatStore((s) => s.setCurrentArtifactType);
  const setArtifactContent = useChatStore((s) => s.setArtifactContent);
  const xml = useDiagramStore((s) => s.xml);
  const hydrateSession = useDiagramStore((s) => s.hydrateSession);
  const setHistory = useDiagramStore((s) => s.setHistory);
  const setValidationState = useDiagramStore((s) => s.setValidationState);
  const applyPendingRemoteSession = useDiagramStore((s) => s.applyPendingRemoteSession);
  const dismissConflict = useDiagramStore((s) => s.dismissConflict);

  const refreshHistory = useCallback(async () => {
    if (!taskId || taskId === "new") {
      return [];
    }
    const response = await fetch(`/api/diagram-sessions/task/${taskId}/history`);
    if (!response.ok) {
      throw new Error("拉取 diagram 历史失败");
    }
    const payload = await response.json();
    if (Array.isArray(payload.history)) {
      setHistory(payload.history);
      return payload.history;
    }
    return [];
  }, [setHistory, taskId]);

  const restoreVersion = useCallback(
    async (version: number) => {
      if (!taskId || taskId === "new") {
        throw new Error("当前没有可恢复的任务");
      }
      const response = await fetch(`/api/diagram-sessions/task/${taskId}/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ version }),
      });
      if (!response.ok) {
        throw new Error("恢复历史版本失败");
      }
      const payload = await response.json();
      if (payload.session) {
        hydrateSession(payload.session, { force: true });
        setCurrentArtifactType("drawio");
        setArtifactContent(payload.session.xml || null);
      }
      await refreshHistory();
      return payload;
    },
    [hydrateSession, refreshHistory, setArtifactContent, setCurrentArtifactType, taskId]
  );

  const revalidateCurrentDiagram = useCallback(async () => {
    if (!taskId && !xml) {
      throw new Error("当前没有可校验的图");
    }
    const response = await fetch("/api/diagram/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: taskId || undefined, xml: xml || undefined }),
    });
    if (!response.ok) {
      throw new Error("diagram 校验失败");
    }
    const payload = await response.json();
    if (payload.validation) {
      setValidationState(payload.validation);
    }
    return payload;
  }, [setValidationState, taskId, xml]);

  const requestAiRetry = useCallback(() => {
    const prompt = buildRetryPrompt();
    if (!prompt) {
      return false;
    }
    sendChat(prompt, taskId || undefined);
    return true;
  }, [sendChat, taskId]);

  return {
    refreshHistory,
    restoreVersion,
    revalidateCurrentDiagram,
    requestAiRetry,
    acceptRemoteVersion: applyPendingRemoteSession,
    keepLocalVersion: dismissConflict,
  };
}
