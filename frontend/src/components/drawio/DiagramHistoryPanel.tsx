"use client";

import { useEffect, useState } from "react";

import { useDiagramSession } from "@/hooks/useDiagramSession";
import { useDiagramStore } from "@/stores/diagramStore";


export function DiagramHistoryPanel({ compact = false }: { compact?: boolean }) {
  const taskId = useDiagramStore((s) => s.taskId);
  const history = useDiagramStore((s) => s.history);
  const currentVersion = useDiagramStore((s) => s.version);
  const { refreshHistory, restoreVersion } = useDiagramSession();
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [restoringVersion, setRestoringVersion] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sectionPadding = compact ? "px-3 py-3" : "px-4 py-4";

  useEffect(() => {
    if (!taskId) {
      return;
    }
    let cancelled = false;
    const load = async () => {
      setIsRefreshing(true);
      setError(null);
      try {
        await refreshHistory();
      } catch (refreshError) {
        if (!cancelled) {
          setError(refreshError instanceof Error ? refreshError.message : "历史记录加载失败");
        }
      } finally {
        if (!cancelled) {
          setIsRefreshing(false);
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshHistory, taskId]);

  const handleRestore = async (version: number) => {
    setRestoringVersion(version);
    setError(null);
    try {
      await restoreVersion(version);
    } catch (restoreError) {
      setError(restoreError instanceof Error ? restoreError.message : "恢复历史版本失败");
    } finally {
      setRestoringVersion(null);
    }
  };

  return (
    <section className={`flex h-full min-h-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm ${sectionPadding}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">版本历史</h3>
          <p className="mt-1 text-[11px] leading-5 text-slate-500">恢复历史版本会生成一个新的当前版本，旧记录仍保留。</p>
        </div>
        <button
          type="button"
          onClick={() => void refreshHistory()}
          className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50"
        >
          刷新
        </button>
      </div>

      {error && (
        <div className="mt-4 rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      <div className="mt-4 min-h-0 flex-1 overflow-y-auto pr-1">
        {isRefreshing && history.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
            历史版本加载中...
          </div>
        ) : history.length === 0 ? (
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-500">
            当前任务还没有历史版本。
          </div>
        ) : (
          <div className="space-y-3">
            {history.map((entry) => {
              const isCurrent = entry.version === currentVersion;
              return (
                <article
                  key={entry.version}
                  className={`rounded-2xl border px-3 py-3 ${
                    isCurrent ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-slate-50"
                  }`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">v{entry.version}</p>
                      <p className="mt-1 text-[11px] text-slate-500">{entry.source}</p>
                    </div>
                    {isCurrent ? (
                      <span className="rounded-full border border-blue-200 bg-white px-2.5 py-1 text-xs font-medium text-blue-700">
                        当前
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void handleRestore(entry.version)}
                        disabled={restoringVersion === entry.version}
                        className="rounded-full border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {restoringVersion === entry.version ? "恢复中..." : "恢复"}
                      </button>
                    )}
                  </div>
                  <p className="mt-3 text-sm leading-5 text-slate-700">{entry.summary}</p>
                  <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span>{new Date(entry.createdAt).toLocaleString()}</span>
                    {entry.validation?.review_passed === false && (
                      <span>仍有审稿问题</span>
                    )}
                    {entry.validation?.retry_recommended && <span>建议继续修图</span>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}
