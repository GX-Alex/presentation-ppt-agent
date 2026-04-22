/**
 * Web Deck 状态管理 — Zustand Store。
 * 独立于 chatStore，专门管理 Web Deck 项目生成流程。
 * 对齐 high.md §8.3：前端 Store 层拆分。
 */
import { create } from "zustand";

// ── 类型定义 ──

/** Deck 项目状态枚举 */
export type DeckStatus =
  | "planning"     // 规划中
  | "plan_ready"   // 规划完成，等待用户确认
  | "generating"   // 生成中
  | "reviewing"    // 审阅中
  | "completed"    // 完成
  | "failed";      // 失败

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

/** 页面数据 */
export interface DeckPageData {
  id: string;
  pageIndex: number;
  title: string;
  kind: PageKind;
  status: PageStatus;
  html?: string;
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

// ── Store 接口 ──

interface DeckStore {
  // 项目信息
  projectId: string | null;
  deckStatus: DeckStatus | null;
  manifest: DeckManifest | null;

  // 视图状态
  isTocCollapsed: boolean;

  // 页面列表
  pages: DeckPageData[];
  currentPageIndex: number;

  // 最终 HTML
  finalHtml: string | null;

  // 审阅报告
  reviews: ReviewReport[];

  // 进度
  generatingCurrent: number;
  generatingTotal: number;

  // ── Actions ──

  /** 设置项目 ID */
  setProjectId: (id: string) => void;
  /** 设置 Deck 状态 */
  setDeckStatus: (status: DeckStatus) => void;
  /** 设置 manifest（规划结果） */
  setManifest: (manifest: DeckManifest) => void;

  /** 初始化页面列表（从 manifest 创建空页面） */
  initPages: (pages: DeckPageData[]) => void;
  /** 更新单页状态 */
  updatePageStatus: (pageId: string, status: PageStatus) => void;
  /** 更新单页 HTML */
  updatePageHtml: (pageId: string, html: string) => void;
  /** 更新 lane 状态 */
  updateLaneStatus: (pageId: string, laneId: string, status: LaneStatus, laneKind?: LaneKind, output?: string, error?: string) => void;
  /** 设置当前预览页 */
  setCurrentPageIndex: (index: number) => void;
  /** 设置 TOC 是否收起 */
  setTocCollapsed: (collapsed: boolean) => void;
  /** 切换 TOC 收起状态 */
  toggleTocCollapsed: () => void;

  /** 设置最终 HTML */
  setFinalHtml: (html: string) => void;

  /** 添加审阅报告 */
  addReview: (review: ReviewReport) => void;

  /** 设置生成进度 */
  setGeneratingProgress: (current: number, total: number) => void;

  /** 重置所有状态（新项目时调用） */
  resetDeck: () => void;
}

export const useDeckStore = create<DeckStore>((set) => ({
  // 初始状态
  projectId: null,
  deckStatus: null,
  manifest: null,
  isTocCollapsed: false,
  pages: [],
  currentPageIndex: 0,
  finalHtml: null,
  reviews: [],
  generatingCurrent: 0,
  generatingTotal: 0,

  // Actions
  setProjectId: (id) => set({ projectId: id }),

  setDeckStatus: (status) => set({ deckStatus: status }),

  setManifest: (manifest) => set({ manifest }),

  initPages: (pages) =>
    set((state) => {
      const mergedPages = pages
        .map((page) => {
          const existing = state.pages.find((item) => item.id === page.id);
          if (!existing) return page;

          return {
            ...page,
            status: existing.status === "pending" ? page.status : existing.status,
            html: existing.html || page.html,
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
      pages: state.pages.map((p) =>
        p.id === pageId ? { ...p, status } : p
      ),
    })),

  updatePageHtml: (pageId, html) =>
    set((state) => ({
      pages: state.pages.map((p) =>
        p.id === pageId ? { ...p, html, status: "done" as PageStatus } : p
      ),
    })),

  updateLaneStatus: (pageId, laneId, status, laneKind, output, error) =>
    set((state) => ({
      pages: state.pages.map((p) => {
        if (p.id !== pageId) return p;

        const existingLane = p.lanes.find((lane) => lane.id === laneId);
        const lanes = existingLane
          ? p.lanes.map((lane) =>
              lane.id === laneId
                ? { ...lane, status, laneKind: laneKind || lane.laneKind, output, error }
                : lane
            )
          : [
              ...p.lanes,
              {
                id: laneId,
                laneKind: laneKind || "narrative",
                status,
                output,
                error,
              },
            ];

        return {
          ...p,
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
      finalHtml: null,
      reviews: [],
      generatingCurrent: 0,
      generatingTotal: 0,
    }),
}));
