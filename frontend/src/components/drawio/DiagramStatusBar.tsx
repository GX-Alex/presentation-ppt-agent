"use client";

import { useDiagramSession } from "@/hooks/useDiagramSession";
import { useDiagramStore } from "@/stores/diagramStore";


function statusLabel(status: string): string {
  switch (status) {
    case "synced":
      return "已同步";
    case "dirty":
      return "待同步";
    case "loading":
      return "同步中";
    case "error":
      return "同步异常";
    default:
      return "空闲";
  }
}


export function DiagramStatusBar() {
  const version = useDiagramStore((s) => s.version);
  const serverVersion = useDiagramStore((s) => s.serverVersion);
  const syncStatus = useDiagramStore((s) => s.syncStatus);
  const validationState = useDiagramStore((s) => s.validationState);
  const conflict = useDiagramStore((s) => s.conflict);
  const lastSyncedAt = useDiagramStore((s) => s.lastSyncedAt);
  const lastLocalEditAt = useDiagramStore((s) => s.lastLocalEditAt);
  const { acceptRemoteVersion, keepLocalVersion } = useDiagramSession();

  const reviewLabel = validationState?.retry_recommended
    ? "需要继续修图"
    : validationState?.review_passed
    ? "布局通过"
    : validationState?.valid
    ? "结构通过"
    : "待校验";

  return (
    <div className="flex shrink-0 flex-col gap-3 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
        <span className="rounded-full border border-slate-300 bg-white px-3 py-1 font-medium">当前版本 v{version || 0}</span>
        <span className="rounded-full border border-slate-300 bg-white px-3 py-1">服务端 v{serverVersion || 0}</span>
        <span className="rounded-full border border-slate-300 bg-white px-3 py-1">状态：{statusLabel(syncStatus)}</span>
        <span className="rounded-full border border-slate-300 bg-white px-3 py-1">审稿：{reviewLabel}</span>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-slate-500">
        <span>最近同步：{lastSyncedAt ? new Date(lastSyncedAt).toLocaleString() : "尚未同步"}</span>
        <span>最近本地编辑：{lastLocalEditAt ? new Date(lastLocalEditAt).toLocaleString() : "暂无"}</span>
        {typeof validationState?.score === "number" && <span>评分：{validationState.score}</span>}
      </div>

      {conflict && (
        <div className="flex flex-col gap-3 rounded-2xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <div>
            <p className="font-semibold">检测到版本冲突</p>
            <p className="mt-1 text-amber-800">{conflict.message}</p>
            <p className="mt-1 text-xs text-amber-700">
              远端版本 v{conflict.remoteVersion}
              {conflict.remoteSource ? ` · 来源 ${conflict.remoteSource}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={acceptRemoteVersion}
              className="rounded-full border border-amber-400 bg-white px-3 py-1.5 font-medium text-amber-900 transition hover:bg-amber-100"
            >
              加载远端版本
            </button>
            <button
              type="button"
              onClick={keepLocalVersion}
              className="rounded-full border border-amber-200 bg-amber-100 px-3 py-1.5 font-medium text-amber-900 transition hover:bg-amber-200"
            >
              保留本地修改
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
