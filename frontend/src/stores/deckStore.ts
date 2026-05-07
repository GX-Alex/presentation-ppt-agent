/**
 * Web Deck 状态管理 — Zustand Store。
 * 独立于 chatStore，专门管理 Web Deck 项目生成流程。
 * 对齐 high.md §8.3：前端 Store 层拆分。
 */
import { create } from "zustand";

// ── 类型定义 ──

/** Deck 项目状态枚举 */
export type DeckStatus =
  | "planning"
  | "plan_ready"
  | "generating"
  | "reviewing"
  | "completed"
  | "failed";

/** 页面状态枚举 */
export type PageStatus = "pending" | "running" | "done" | "failed";

/** Lane 状态枚举 */
export type LaneStatus = "pending" | "running" | "done" | "failed";

/** 页面类型 */
export type PageKind =
  | "cover"
  | "toc"
  | "summary"
  | "content"
  | "architecture"
  | "chart_analysis"
  | "roadmap"
  | "comparison"
  | "closing"
  | "appendix";

/** Lane 类型 */
export type LaneKind = "narrative" | "chart" | "diagram" | "asset" | "layout" | "review";

/** 页面规格条目 */
export interface PageSpecEntry {
  id: string;
  pageIndex: number;
  title: string;
  kind: PageKind;
  keyPoints: string[];
  narrativeHint: string;
}

/** Deck Manifest（规划结果） */
export interface DeckManifest {
  topic: string;
  audienceLevel: string;
  totalPages: number;
  pages: PageSpecEntry[];
}

/** Lane 运行记录 */
export interface LaneRunInfo {
  id: string;
  laneKind: LaneKind;
  status: LaneStatus;
  output?: string;
  error?: string;
}

export interface DeckBundleArtifact {
  assetId: string;
  kind: string;
  content?: string;
  metadata?: Record<string, unknown>;
}

export interface DeckEditableNode {
  nodeId: string;
  nodeKind: string;
  tagName: string;
  text: string;
  selectorHint: string;
  layoutScopeId?: string;
  editable: boolean;
}

export interface DeckLayoutScope {
  scopeId: string;
  scopeKind: string;
  tagName: string;
  label: string;
  moduleNodeIds: string[];
  allowedOps: string[];
  parameters?: Record<string, unknown>;
}

export interface DeckAssetManifestItem {
  assetId: string;
  kind: string;
  label: string;
  editableVia: string;
  bindingNodeId?: string;
  metadata?: Record<string, unknown>;
}

export interface DeckPageBundle {
  pageId?: string;
  status?: string;
  html?: string;
  cssTokens?: Record<string, unknown>;
  jsModules?: string[];
  artifacts?: DeckBundleArtifact[];
  editorSchemaVersion?: string;
  editableModel?: DeckEditableNode[];
  layoutModel?: DeckLayoutScope[];
  assetManifest?: DeckAssetManifestItem[];
  renderHints?: Record<string, unknown>;
  review?: Record<string, unknown> | null;
}

/** 页面数据 */
export interface DeckPageData {
  id: string;
  pageIndex: number;
  title: string;
  kind: PageKind;
  status: PageStatus;
  html?: string;
  pageBundle?: DeckPageBundle;
  lanes: LaneRunInfo[];
}

/** 审阅报告 */
export interface ReviewReport {
  level: "page" | "deck";
  targetId: string;
  passed: boolean;
  score: number;
  issues: Array<{
    level: string;
    message: string;
    suggestion?: string;
  }>;
  suggestions: string[];
  retrying?: boolean;
}

/** 页面版本快照 */
export interface DeckPageVersion {
  version: number;
  source: string;
  changeSummary?: string;
  createdAt?: string;
}

// ── Store 接口 ──

interface DeckStore {
  projectId: string | null;
  deckStatus: DeckStatus | null;
  manifest: DeckManifest | null;
  isTocCollapsed: boolean;
  pages: DeckPageData[];
  currentPageIndex: number;
  isEditorMode: boolean;
  draftHtmlByPageId: Record<string, string>;
  pageVersionsByPageId: Record<string, DeckPageVersion[]>;
  selectedNodeIdByPageId: Record<string, string | null>;
  hoveredNodeIdByPageId: Record<string, string | null>;
  isSavingPage: boolean;
  isLoadingVersions: boolean;
  finalHtml: string | null;
  reviews: ReviewReport[];
  generatingCurrent: number;
  generatingTotal: number;

  setProjectId: (id: string) => void;
  setDeckStatus: (status: DeckStatus) => void;
  setManifest: (manifest: DeckManifest) => void;
  initPages: (pages: DeckPageData[]) => void;
  updatePageStatus: (pageId: string, status: PageStatus) => void;
  updatePageHtml: (pageId: string, html: string, pageBundle?: DeckPageBundle) => void;
  updatePageBundle: (pageId: string, pageBundle: DeckPageBundle) => void;
  updateLaneStatus: (pageId: string, laneId: string, status: LaneStatus, laneKind?: LaneKind, output?: string, error?: string) => void;
  setCurrentPageIndex: (index: number) => void;
  setTocCollapsed: (collapsed: boolean) => void;
  toggleTocCollapsed: () => void;
  setEditorMode: (enabled: boolean) => void;
  setPageDraft: (pageId: string, html: string) => void;
  clearPageDraft: (pageId: string) => void;
  setPageVersions: (pageId: string, versions: DeckPageVersion[]) => void;
  setSelectedNodeId: (pageId: string, nodeId: string | null) => void;
  setHoveredNodeId: (pageId: string, nodeId: string | null) => void;
  setSavingPage: (saving: boolean) => void;
  setLoadingVersions: (loading: boolean) => void;
  setFinalHtml: (html: string) => void;
  addReview: (review: ReviewReport) => void;
  setGeneratingProgress: (current: number, total: number) => void;
  resetDeck: () => void;
}

export const useDeckStore = create<DeckStore>((set) => ({
  projectId: null,
  deckStatus: null,
  manifest: null,
  isTocCollapsed: false,
  pages: [],
  currentPageIndex: 0,
  isEditorMode: false,
  draftHtmlByPageId: {},
  pageVersionsByPageId: {},
  selectedNodeIdByPageId: {},
  hoveredNodeIdByPageId: {},
  isSavingPage: false,
  isLoadingVersions: false,
  finalHtml: null,
  reviews: [],
  generatingCurrent: 0,
  generatingTotal: 0,

  setProjectId: (id) => set({ projectId: id }),

  setDeckStatus: (status) => set({ deckStatus: status }),

  setManifest: (manifest) => set({ manifest }),

  initPages: (pages) =>
    set((state) => {
      const mergedPages = pages
        .map((page) => {
          const existing = state.pages.find((item) => item.id === page.id);
          if (!existing) {
            return page;
          }

          return {
            ...page,
            status: existing.status === "pending" ? page.status : existing.status,
            html: existing.html || page.html,
            pageBundle: page.pageBundle || existing.pageBundle,
            lanes: existing.lanes.length > 0 ? existing.lanes : page.lanes,
          };
        })
        .sort((left, right) => left.pageIndex - right.pageIndex);

      return {
        pages: mergedPages,
        currentPageIndex: mergedPages.length === 0
          ? 0
          : Math.min(state.currentPageIndex, mergedPages.length - 1),
      };
    }),

  updatePageStatus: (pageId, status) =>
    set((state) => ({
      pages: state.pages.map((page) =>
        page.id === pageId ? { ...page, status } : page
      ),
    })),

  updatePageHtml: (pageId, html, pageBundle) =>
    set((state) => ({
      pages: state.pages.map((page) =>
        page.id === pageId
          ? {
              ...page,
              html,
              pageBundle: pageBundle || page.pageBundle,
              status: "done" as PageStatus,
            }
          : page
      ),
      draftHtmlByPageId: {
        ...state.draftHtmlByPageId,
        [pageId]: html,
      },
    })),

  updatePageBundle: (pageId, pageBundle) =>
    set((state) => ({
      pages: state.pages.map((page) =>
        page.id === pageId ? { ...page, pageBundle } : page
      ),
    })),

  updateLaneStatus: (pageId, laneId, status, laneKind, output, error) =>
    set((state) => ({
      pages: state.pages.map((page) => {
        if (page.id !== pageId) {
          return page;
        }

        const existingLane = page.lanes.find((lane) => lane.id === laneId);
        const lanes = existingLane
          ? page.lanes.map((lane) =>
              lane.id === laneId
                ? { ...lane, status, laneKind: laneKind || lane.laneKind, output, error }
                : lane
            )
          : [
              ...page.lanes,
              {
                id: laneId,
                laneKind: laneKind || "narrative",
                status,
                output,
                error,
              },
            ];

        return {
          ...page,
          lanes,
        };
      }),
    })),

  setCurrentPageIndex: (index) =>
    set((state) => ({
      currentPageIndex: state.pages.length === 0
        ? 0
        : Math.max(0, Math.min(index, state.pages.length - 1)),
    })),

  setTocCollapsed: (collapsed) => set({ isTocCollapsed: collapsed }),

  toggleTocCollapsed: () =>
    set((state) => ({ isTocCollapsed: !state.isTocCollapsed })),

  setEditorMode: (enabled) => set({ isEditorMode: enabled }),

  setPageDraft: (pageId, html) =>
    set((state) => ({
      draftHtmlByPageId: {
        ...state.draftHtmlByPageId,
        [pageId]: html,
      },
    })),

  clearPageDraft: (pageId) =>
    set((state) => {
      const next = { ...state.draftHtmlByPageId };
      delete next[pageId];
      return { draftHtmlByPageId: next };
    }),

  setPageVersions: (pageId, versions) =>
    set((state) => ({
      pageVersionsByPageId: {
        ...state.pageVersionsByPageId,
        [pageId]: versions,
      },
    })),

  setSelectedNodeId: (pageId, nodeId) =>
    set((state) => ({
      selectedNodeIdByPageId: {
        ...state.selectedNodeIdByPageId,
        [pageId]: nodeId,
      },
    })),

  setHoveredNodeId: (pageId, nodeId) =>
    set((state) => ({
      hoveredNodeIdByPageId: {
        ...state.hoveredNodeIdByPageId,
        [pageId]: nodeId,
      },
    })),

  setSavingPage: (saving) => set({ isSavingPage: saving }),

  setLoadingVersions: (loading) => set({ isLoadingVersions: loading }),

  setFinalHtml: (html) => set({ finalHtml: html }),

  addReview: (review) =>
    set((state) => ({
      reviews: state.reviews.some(
        (item) => item.level === review.level && item.targetId === review.targetId,
      )
        ? state.reviews.map((item) =>
            item.level === review.level && item.targetId === review.targetId
              ? review
              : item,
          )
        : [...state.reviews, review],
    })),

  setGeneratingProgress: (current, total) =>
    set({ generatingCurrent: current, generatingTotal: total }),

  resetDeck: () =>
    set({
      projectId: null,
      deckStatus: null,
      manifest: null,
      isTocCollapsed: false,
      pages: [],
      currentPageIndex: 0,
      isEditorMode: false,
      draftHtmlByPageId: {},
      pageVersionsByPageId: {},
      selectedNodeIdByPageId: {},
      hoveredNodeIdByPageId: {},
      isSavingPage: false,
      isLoadingVersions: false,
      finalHtml: null,
      reviews: [],
      generatingCurrent: 0,
      generatingTotal: 0,
    }),
}));
