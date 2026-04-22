/**
 * WebSocket 客户端 — 与后端通信的底层工厂。
 * 主要逻辑已移至 useWebSocket Hook（含自动重连）。
 */

const WS_URL =
  typeof window !== "undefined"
    ? `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/chat`
    : "";

export function createWebSocket(): WebSocket | null {
  if (typeof window === "undefined") return null;
  return new WebSocket(WS_URL);
}

export type ServerMessageType =
  | "message"
  | "thinking"
  | "status"
  | "clarification"
  | "intent_detected"
  | "plan"
  | "progress"
  | "file_parsed"
  | "project_tree"
  | "search_start"
  | "search_result"
  | "skill_loaded"
  | "preview_mode"
  | "export_ready"
  | "error";

export interface ServerMessage {
  type: ServerMessageType;
  [key: string]: unknown;
}
