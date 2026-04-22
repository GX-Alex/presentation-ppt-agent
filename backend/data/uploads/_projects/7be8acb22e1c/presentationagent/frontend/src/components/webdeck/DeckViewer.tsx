/**
 * Web Deck 主查看器 — 整合 TOC、预览、Lane 面板。
 * 对齐 high.md §5.3.5 / §8.3。
 * 根据 Deck 状态动态切换界面：
 *   - null       → 工作台待命
 *   - plan_ready → Manifest 确认
 *   - generating → TOC + 预览 + 进度
 *   - completed  → TOC + 最终预览
 */
"use client";

import { useDeckStore } from "@/stores/deckStore";
import { useChatStore } from "@/stores/chatStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import { DeckTocPanel } from "./DeckTocPanel";
import { DeckPagePreview } from "./DeckPagePreview";
import { DeckLanePanel } from "./DeckLanePanel";

function DeckIdlePanel() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-white px-8">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-5 flex h-20 w-20 items-center justify-center rounded-3xl border border-sky-100 bg-sky-50 text-4xl text-sky-600 shadow-sm">
          <span>▣</span>
        </div>
        <h3 className="text-lg font-semibold text-slate-900">Web Deck 工作台已就绪</h3>
        <p className="mt-3 text-sm leading-6 text-slate-500">
          请在左侧通过高质量生成入口提交主题、受众和参考材料。系统会先完成研究与大纲规划，再在这里展示可确认结果。
        </p>
      </div>
    </div>
  );
}

/** Manifest 确认面板 */
function ManifestConfirmPanel() {
  const manifest = useDeckStore((s) => s.manifest);
  const projectId = useDeckStore((s) => s.projectId);
  const { sendWebDeckApprove } = useWebSocket();
  const isProcessing = useChatStore((s) => s.isProcessing);

  if (!manifest) return null;

  return (
    <div className="flex-1 min-h-0 p-6 flex items-stretch justify-center">
      <div className="max-w-lg w-full max-h-full bg-white rounded-2xl border border-gray-200 shadow-sm p-6 flex flex-col overflow-hidden">
        <h3 className="text-lg font-semibold text-gray-800 mb-1">
          {manifest.topic}
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          受众: {manifest.audienceLevel} · {manifest.totalPages} 页
        </p>

        <div className="flex-1 min-h-0 overflow-y-auto pr-1 space-y-2 mb-6">
          {manifest.pages.map((page, idx) => (
            <div
              key={page.id}
              className="flex items-center gap-2 text-sm text-gray-700"
            >
              <span className="w-6 h-6 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center text-xs font-medium flex-shrink-0">
                {idx + 1}
              </span>
              <span className="font-medium">{page.title}</span>
              <span className="text-gray-400 text-xs">({page.kind})</span>
            </div>
          ))}
        </div>

        <div className="flex gap-3 pt-1 border-t border-gray-100">
          <button
            onClick={() => {
              if (projectId) sendWebDeckApprove(projectId);
            }}
            disabled={!projectId || isProcessing}
            className="flex-1 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            确认并开始生成
          </button>
          <button
            onClick={() => {
              useDeckStore.getState().resetDeck();
            }}
            disabled={isProcessing}
            className="px-4 py-2.5 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
          >
            重新规划
          </button>
        </div>
      </div>
    </div>
  );
}

/** 生成进度条 */
function ProgressBar() {
  const current = useDeckStore((s) => s.generatingCurrent);
  const total = useDeckStore((s) => s.generatingTotal);
  const deckStatus = useDeckStore((s) => s.deckStatus);

  if (!["generating", "reviewing"].includes(deckStatus || "") || total === 0) return null;

  const pct = deckStatus === "reviewing" ? 100 : Math.round((current / total) * 100);

  return (
    <div className="h-8 flex-shrink-0 bg-white border-t border-gray-100 px-4 flex items-center gap-3">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-500 rounded-full transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs text-gray-500 w-16 text-right">
        {deckStatus === "reviewing" ? "审稿中" : `${current}/${total} 页`}
      </span>
    </div>
  );
}

export function DeckViewer() {
  const deckStatus = useDeckStore((s) => s.deckStatus);

  // 未开始 → 显示工作台待命态
  if (!deckStatus) {
    return (
      <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white flex items-center justify-center">
        <DeckIdlePanel />
      </div>
    );
  }

  // 规划中 → 等待状态
  if (deckStatus === "planning") {
    return (
      <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white flex items-center justify-center">
        <div className="text-center text-gray-500">
          <div className="w-10 h-10 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm">正在规划 Deck 结构...</p>
        </div>
      </div>
    );
  }

  // 规划完成 → 确认面板  
  if (deckStatus === "plan_ready") {
    return (
      <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white">
        <ManifestConfirmPanel />
      </div>
    );
  }

  // 生成中 / 完成 / 审阅 / 失败 → 三栏布局
  return (
    <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white flex flex-col">
      <div className="flex-1 flex min-h-0">
        <DeckTocPanel />
        <DeckPagePreview />
      </div>
      <DeckLanePanel />
      <ProgressBar />
    </div>
  );
}
