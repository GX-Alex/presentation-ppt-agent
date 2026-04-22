/**
 * Deck 目录面板 — 左侧 TOC，展示页面列表和状态。
 * 对齐 high.md §5.3.5 / §8.3。
 */
"use client";

import { PanelLeftClose, PanelLeftOpen, RotateCcw } from "lucide-react";
import { useDeckStore, type DeckPageData, type PageStatus } from "@/stores/deckStore";
import { useWebSocket } from "@/hooks/useWebSocket";

/** 页面状态指示器颜色 */
function statusBadge(status: PageStatus): { color: string; label: string } {
  switch (status) {
    case "pending":
      return { color: "bg-gray-300", label: "等待" };
    case "running":
      return { color: "bg-blue-400 animate-pulse", label: "生成中" };
    case "done":
      return { color: "bg-green-500", label: "完成" };
    case "failed":
      return { color: "bg-red-500", label: "失败" };
    default:
      return { color: "bg-gray-300", label: "" };
  }
}

export function DeckTocPanel() {
  const pages = useDeckStore((s) => s.pages);
  const currentPageIndex = useDeckStore((s) => s.currentPageIndex);
  const isTocCollapsed = useDeckStore((s) => s.isTocCollapsed);
  const setCurrentPageIndex = useDeckStore((s) => s.setCurrentPageIndex);
  const toggleTocCollapsed = useDeckStore((s) => s.toggleTocCollapsed);
  const projectId = useDeckStore((s) => s.projectId);
  const { sendWebDeckRetryPage } = useWebSocket();

  if (pages.length === 0) return null;

  const renderRetryButton = (pageId: string, pageTitle: string) => {
    if (!projectId) return null;

    return (
      <button
        onClick={(event) => {
          event.stopPropagation();
          sendWebDeckRetryPage(projectId, pageId);
        }}
        className="flex h-7 w-7 items-center justify-center rounded-lg border border-red-200 bg-white text-red-500 transition-colors hover:bg-red-50 hover:text-red-700"
        title={`重试页面: ${pageTitle}`}
      >
        <RotateCcw className="h-3.5 w-3.5" />
      </button>
    );
  };

  return (
    <div
      className={`${isTocCollapsed ? "w-14" : "w-56"} h-full min-h-0 flex-shrink-0 border-r border-gray-100 bg-gray-50/50 flex flex-col transition-[width] duration-200 relative z-10`}
    >
      <div className={`${isTocCollapsed ? "px-2" : "px-3"} flex-1 min-h-0 py-3 flex flex-col`}>
        <div className={`mb-2 flex items-center ${isTocCollapsed ? "justify-center" : "justify-between gap-2"}`}>
          {!isTocCollapsed && (
            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">
              页面目录
            </h4>
          )}
          <button
            onClick={toggleTocCollapsed}
            className="flex h-8 w-8 items-center justify-center rounded-xl border border-gray-200 bg-white text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-700"
            title={isTocCollapsed ? "展开目录" : "收起目录"}
          >
            {isTocCollapsed ? (
              <PanelLeftOpen className="h-4 w-4" />
            ) : (
              <PanelLeftClose className="h-4 w-4" />
            )}
          </button>
        </div>
        <ul className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-1">
          {pages.map((page: DeckPageData, idx: number) => {
            const badge = statusBadge(page.status);
            const isActive = idx === currentPageIndex;

            if (isTocCollapsed) {
              return (
                <li key={page.id} className="flex flex-col items-center gap-1">
                  <button
                    onClick={() => setCurrentPageIndex(idx)}
                    className={`relative flex h-10 w-10 items-center justify-center rounded-xl border text-sm font-medium transition-colors ${
                      isActive
                        ? "border-blue-200 bg-blue-50 text-blue-700"
                        : "border-transparent bg-white text-gray-600 hover:border-gray-200 hover:bg-gray-100"
                    }`}
                    title={`${idx + 1}. ${page.title} · ${badge.label}`}
                  >
                    <span className={`absolute right-1.5 top-1.5 h-2 w-2 rounded-full ${badge.color}`} />
                    {idx + 1}
                  </button>
                  {page.status === "failed" && renderRetryButton(page.id, page.title)}
                </li>
              );
            }

            return (
              <li key={page.id}>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCurrentPageIndex(idx)}
                    className={`flex-1 text-left px-2.5 py-2 rounded-lg text-sm transition-colors flex items-center gap-2 ${
                      isActive
                        ? "bg-blue-50 text-blue-700 font-medium"
                        : "text-gray-600 hover:bg-gray-100"
                    }`}
                  >
                    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${badge.color}`} />
                    <span className="truncate flex-1">
                      {idx + 1}. {page.title}
                    </span>
                  </button>
                  {page.status === "failed" && renderRetryButton(page.id, page.title)}
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
