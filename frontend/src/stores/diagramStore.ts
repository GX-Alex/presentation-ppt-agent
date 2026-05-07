import { create } from "zustand";

import type { DiagramSessionPayload, DiagramValidationPayload } from "@/lib/diagramWsProtocol";

export type DiagramSyncStatus = "idle" | "loading" | "synced" | "dirty" | "error";

export interface DiagramHistoryEntry {
  version: number;
  summary: string;
  source: string;
  createdAt: string;
  validation?: DiagramValidationPayload | null;
}

export interface DiagramConflictState {
  type: "remote_update_conflict";
  message: string;
  remoteVersion: number;
  localVersion: number;
  detectedAt: string;
  remoteSource?: string;
}

interface DiagramStore {
  sessionId: string | null;
  taskId: string | null;
  xml: string | null;
  latestSvg: string | null;
  latestPng: string | null;
  version: number;
  serverVersion: number;
  baseVersion: number;
  history: DiagramHistoryEntry[];
  isReady: boolean;
  syncStatus: DiagramSyncStatus;
  validationState: DiagramValidationPayload | null;
  pendingServerCommand: string | null;
  lastAppliedToolCallId: string | null;
  lastSyncedAt: string | null;
  lastLocalEditAt: string | null;
  conflict: DiagramConflictState | null;
  pendingRemoteSession: DiagramSessionPayload | null;
  shapeLibraryCache: Record<string, unknown>;
  hydrateSession: (session: DiagramSessionPayload, options?: { force?: boolean }) => void;
  setHistory: (history: DiagramSessionPayload[]) => void;
  updateXml: (xml: string, options?: { syncStatus?: DiagramSyncStatus; validation?: DiagramValidationPayload | null }) => void;
  setValidationState: (validation: DiagramValidationPayload | null) => void;
  setSyncStatus: (status: DiagramSyncStatus) => void;
  applyPendingRemoteSession: () => void;
  dismissConflict: () => void;
  cacheShapeLibrary: (library: string, payload: unknown) => void;
  resetDiagram: () => void;
}

const initialState = {
  sessionId: null,
  taskId: null,
  xml: null,
  latestSvg: null,
  latestPng: null,
  version: 0,
  serverVersion: 0,
  baseVersion: 0,
  history: [] as DiagramHistoryEntry[],
  isReady: false,
  syncStatus: "idle" as DiagramSyncStatus,
  validationState: null as DiagramValidationPayload | null,
  pendingServerCommand: null,
  lastAppliedToolCallId: null,
  lastSyncedAt: null as string | null,
  lastLocalEditAt: null as string | null,
  conflict: null as DiagramConflictState | null,
  pendingRemoteSession: null as DiagramSessionPayload | null,
  shapeLibraryCache: {},
};

function toHistoryEntry(session: DiagramSessionPayload): DiagramHistoryEntry {
  return {
    version: session.version,
    summary: session.summary,
    source: session.source,
    createdAt: session.created_at,
    validation: session.validation || null,
  };
}

function mergeHistoryEntries(
  existing: DiagramHistoryEntry[],
  incoming: DiagramHistoryEntry[],
): DiagramHistoryEntry[] {
  const merged = new Map<number, DiagramHistoryEntry>();
  for (const entry of existing) {
    merged.set(entry.version, entry);
  }
  for (const entry of incoming) {
    merged.set(entry.version, entry);
  }
  return [...merged.values()].sort((a, b) => b.version - a.version).slice(0, 30);
}

export const useDiagramStore = create<DiagramStore>((set, get) => ({
  ...initialState,
  hydrateSession: (session, options) =>
    set((state) => {
      const nextEntry = toHistoryEntry(session);
      const history = mergeHistoryEntries(state.history, [nextEntry]);
      const hasUnsyncedLocalDraft =
        !options?.force
        && state.syncStatus === "dirty"
        && Boolean(state.xml)
        && session.version > (state.serverVersion || state.version)
        && session.xml !== state.xml;

      if (hasUnsyncedLocalDraft) {
        return {
          history,
          pendingRemoteSession: session,
          conflict: {
            type: "remote_update_conflict",
            message: `远端版本 v${session.version} 已更新，但当前工作区还有未同步的本地修改。`,
            remoteVersion: session.version,
            localVersion: state.serverVersion || state.version,
            detectedAt: new Date().toISOString(),
            remoteSource: session.source,
          },
        };
      }

      return {
        sessionId: session.session_id,
        taskId: session.task_id,
        xml: session.xml,
        latestSvg: session.svg || null,
        latestPng: session.png || null,
        version: session.version,
        serverVersion: session.version,
        baseVersion: session.version,
        history,
        isReady: true,
        syncStatus: "synced",
        validationState: session.validation || null,
        lastSyncedAt: session.created_at,
        conflict: null,
        pendingRemoteSession: null,
      };
    }),
  setHistory: (history) =>
    set((state) => ({
      history: mergeHistoryEntries(state.history, history.map(toHistoryEntry)),
    })),
  updateXml: (xml, options) =>
    set((state) => ({
      xml,
      isReady: true,
      syncStatus: options?.syncStatus || state.syncStatus,
      validationState: options?.validation === undefined ? state.validationState : options.validation,
      baseVersion: state.baseVersion || state.serverVersion || state.version,
      lastLocalEditAt: new Date().toISOString(),
    })),
  setValidationState: (validation) => set({ validationState: validation }),
  setSyncStatus: (status) => set({ syncStatus: status }),
  applyPendingRemoteSession: () => {
    const pending = get().pendingRemoteSession;
    if (!pending) {
      return;
    }
    get().hydrateSession(pending, { force: true });
  },
  dismissConflict: () =>
    set((state) => ({
      conflict: null,
      pendingRemoteSession: null,
      syncStatus: state.syncStatus === "synced" ? "dirty" : state.syncStatus,
    })),
  cacheShapeLibrary: (library, payload) =>
    set((state) => ({
      shapeLibraryCache: {
        ...state.shapeLibraryCache,
        [library]: payload,
      },
    })),
  resetDiagram: () => set(initialState),
}));