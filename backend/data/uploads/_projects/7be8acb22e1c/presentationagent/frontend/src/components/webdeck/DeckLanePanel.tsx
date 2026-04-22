/**
 * Deck Lane 面板 — 底部展示当前页面的 Lane 日志和重试操作。
 * 对齐 high.md §8.3：Lane 级别可观测。
 */
"use client";

import { useDeckStore, type LaneRunInfo, type LaneStatus } from "@/stores/deckStore";
import { useWebSocket } from "@/hooks/useWebSocket";

function laneStatusIcon(status: LaneStatus): string {
  switch (status) {
    case "pending": return "⏳";
    case "running": return "⚙️";
    case "done":    return "✅";
    case "failed":  return "❌";
    default:        return "•";
  }
}

function laneKindLabel(kind: string): string {
  switch (kind) {
    case "narrative": return "叙事文案";
    case "chart":     return "ECharts 图表";
    case "diagram":   return "SVG 图示";
    case "asset":     return "素材资源";
    default:          return kind;
  }
}

export function DeckLanePanel() {
  const pages = useDeckStore((s) => s.pages);
  const currentPageIndex = useDeckStore((s) => s.currentPageIndex);
  const projectId = useDeckStore((s) => s.projectId);
  const reviews = useDeckStore((s) => s.reviews);
  const { sendWebDeckRetryLane } = useWebSocket();

  const currentPage = pages[currentPageIndex] || null;
  const pageReview = currentPage
    ? reviews.find((review) => review.level === "page" && review.targetId === currentPage.id)
    : null;
  const deckReview = [...reviews].reverse().find((review) => review.level === "deck") || null;

  if (!currentPage || (currentPage.lanes.length === 0 && !pageReview && !deckReview)) return null;

  return (
    <div className="h-36 flex-shrink-0 border-t border-gray-100 bg-gray-50/50 overflow-y-auto px-4 py-3">
      <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
        Lane 执行日志 — 页面 {currentPageIndex + 1}
      </h4>
      {(pageReview || deckReview) && (
        <div className="space-y-1.5 mb-3">
          {pageReview && (
            <div className="rounded-lg border border-slate-200 bg-white/80 px-3 py-2 text-xs text-slate-600">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium text-slate-700">
                  页级审稿 {pageReview.passed ? "通过" : pageReview.retrying ? "未通过，已自动重试" : "未通过"}
                </span>
                <span>得分 {Math.round(pageReview.score * 100)} / 100</span>
              </div>
              {pageReview.issues[0] && (
                <p className="mt-1 truncate">
                  {pageReview.issues[0].message}
                  {pageReview.issues[0].suggestion ? `；修改方向: ${pageReview.issues[0].suggestion}` : ""}
                </p>
              )}
            </div>
          )}
          {deckReview && (
            <div className="rounded-lg border border-slate-200 bg-slate-900 px-3 py-2 text-xs text-slate-100">
              <div className="flex items-center justify-between gap-3">
                <span className="font-medium">
                  Deck 审稿 {deckReview.passed ? "通过" : "未通过"}
                </span>
                <span>得分 {Math.round(deckReview.score * 100)} / 100</span>
              </div>
              {deckReview.issues[0] && (
                <p className="mt-1 truncate text-slate-300">
                  {deckReview.issues[0].message}
                  {deckReview.issues[0].suggestion ? `；建议: ${deckReview.issues[0].suggestion}` : ""}
                </p>
              )}
            </div>
          )}
        </div>
      )}
      <div className="space-y-1.5">
        {currentPage.lanes.map((lane: LaneRunInfo) => (
          <div
            key={lane.id}
            className="flex items-center gap-2 text-sm"
          >
            <span>{laneStatusIcon(lane.status)}</span>
            <span className="text-gray-700 font-medium w-24 flex-shrink-0">
              {laneKindLabel(lane.laneKind)}
            </span>
            <span className="text-gray-500 truncate flex-1">
              {lane.error
                ? `错误: ${lane.error}`
                : lane.status === "done"
                  ? "已完成"
                  : lane.status === "running"
                    ? "执行中..."
                    : "等待中"}
            </span>
            {/* 失败 lane 重试 */}
            {lane.status === "failed" && projectId && (
              <button
                onClick={() =>
                  sendWebDeckRetryLane(projectId, currentPage.id, lane.id)
                }
                className="text-xs text-red-500 hover:text-red-700 px-1.5 py-0.5 rounded border border-red-200 hover:border-red-400 transition-colors"
              >
                重试
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
