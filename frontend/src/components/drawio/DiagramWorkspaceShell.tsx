"use client";

import { useState } from "react";

import { DrawIoViewer } from "@/components/drawio/DrawIoViewer";
import { DiagramHistoryPanel } from "@/components/drawio/DiagramHistoryPanel";
import { DiagramStatusBar } from "@/components/drawio/DiagramStatusBar";
import { DiagramValidationPanel } from "@/components/drawio/DiagramValidationPanel";
import { useDiagramStore } from "@/stores/diagramStore";


type DrawerPanel = "validation" | "history" | null;


export function DiagramWorkspaceShell() {
  const [activePanel, setActivePanel] = useState<DrawerPanel>(null);
  const validationState = useDiagramStore((s) => s.validationState);
  const historyCount = useDiagramStore((s) => s.history.length);

  const togglePanel = (panel: Exclude<DrawerPanel, null>) => {
    setActivePanel((current) => (current === panel ? null : panel));
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 p-3 lg:gap-4 lg:p-4">
      <DiagramStatusBar />
      <div className="relative min-h-0 flex-1">
        <div className="h-full min-h-0 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <DrawIoViewer embedded />
        </div>

        <div className="pointer-events-none absolute inset-y-3 right-3 flex justify-end">
          <div className="pointer-events-auto flex h-full items-start gap-2">
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => togglePanel("validation")}
                className={`flex min-w-[84px] items-center justify-between rounded-2xl border px-3 py-2 text-xs font-medium shadow-sm transition ${
                  activePanel === "validation"
                    ? "border-blue-200 bg-blue-50 text-blue-700"
                    : "border-slate-200 bg-white/95 text-slate-700 backdrop-blur hover:bg-white"
                }`}
                title="打开或折叠质量审稿面板"
              >
                <span>审稿</span>
                <span className="ml-2 rounded-full bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-500">
                  {validationState?.critical_count || validationState?.warning_count || 0}
                </span>
              </button>
              <button
                type="button"
                onClick={() => togglePanel("history")}
                className={`flex min-w-[84px] items-center justify-between rounded-2xl border px-3 py-2 text-xs font-medium shadow-sm transition ${
                  activePanel === "history"
                    ? "border-blue-200 bg-blue-50 text-blue-700"
                    : "border-slate-200 bg-white/95 text-slate-700 backdrop-blur hover:bg-white"
                }`}
                title="打开或折叠版本历史面板"
              >
                <span>历史</span>
                <span className="ml-2 rounded-full bg-white/80 px-1.5 py-0.5 text-[10px] text-slate-500">{historyCount}</span>
              </button>
            </div>

            {activePanel && (
              <aside className="flex h-full w-[290px] max-w-[calc(100vw-6rem)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white/95 shadow-xl backdrop-blur">
                <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2.5">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">
                      {activePanel === "validation" ? "质量审稿" : "版本历史"}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {activePanel === "validation"
                        ? "默认折叠，不再挤压主画布。"
                        : "历史版本可恢复为新的当前版本。"}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setActivePanel(null)}
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
                    title="关闭侧边面板"
                  >
                    收起
                  </button>
                </div>

                <div className="min-h-0 flex-1 overflow-hidden p-2.5">
                  {activePanel === "validation" ? <DiagramValidationPanel compact /> : <DiagramHistoryPanel compact />}
                </div>
              </aside>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
