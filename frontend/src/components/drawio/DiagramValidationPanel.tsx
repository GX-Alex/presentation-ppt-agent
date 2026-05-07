"use client";

import { useState } from "react";

import { useDiagramSession } from "@/hooks/useDiagramSession";
import { useDiagramStore } from "@/stores/diagramStore";


export function DiagramValidationPanel({ compact = false }: { compact?: boolean }) {
  const validation = useDiagramStore((s) => s.validationState);
  const syncStatus = useDiagramStore((s) => s.syncStatus);
  const { revalidateCurrentDiagram, requestAiRetry } = useDiagramSession();
  const [isRevalidating, setIsRevalidating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const issues = validation?.issues || [];
  const suggestions = validation?.suggestions || [];
  const sectionPadding = compact ? "px-3 py-3" : "px-4 py-4";
  const metricPadding = compact ? "px-2.5 py-2" : "px-3 py-2";
  const buttonClass = compact
    ? "rounded-full border px-3 py-1.5 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-50"
    : "rounded-full border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50";

  const handleRevalidate = async () => {
    setIsRevalidating(true);
    setError(null);
    try {
      await revalidateCurrentDiagram();
    } catch (revalidateError) {
      setError(revalidateError instanceof Error ? revalidateError.message : "重新校验失败");
    } finally {
      setIsRevalidating(false);
    }
  };

  return (
    <section className={`flex h-full min-h-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-sm ${sectionPadding}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">质量审稿</h3>
          <p className="mt-1 text-[11px] leading-5 text-slate-500">
            当前模型不看图片，反馈来自 XML 几何规则和会话快照。
          </p>
        </div>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600">
          {validation?.review_mode || "structural"}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs text-slate-600">
        <div className={`rounded-2xl bg-slate-50 ${metricPadding}`}>
          <p className="text-slate-400">Critical</p>
          <p className="mt-1 text-base font-semibold text-slate-900">{validation?.critical_count || 0}</p>
        </div>
        <div className={`rounded-2xl bg-slate-50 ${metricPadding}`}>
          <p className="text-slate-400">Warning</p>
          <p className="mt-1 text-base font-semibold text-slate-900">{validation?.warning_count || issues.length}</p>
        </div>
        <div className={`rounded-2xl bg-slate-50 ${metricPadding}`}>
          <p className="text-slate-400">Score</p>
          <p className="mt-1 text-base font-semibold text-slate-900">{validation?.score ?? "-"}</p>
        </div>
      </div>

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
        <div className="space-y-3">
          {validation?.error && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-700">
              {validation.error}
            </div>
          )}
          {error && (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-3 py-3 text-sm text-rose-700">
              {error}
            </div>
          )}

          {issues.length > 0 ? (
            issues.map((issue, index) => (
              <article
                key={`${issue.code}-${issue.cell_id || "na"}-${index}`}
                className={`rounded-2xl border px-3 py-3 text-sm ${
                  issue.level === "critical"
                    ? "border-rose-200 bg-rose-50 text-rose-800"
                    : "border-amber-200 bg-amber-50 text-amber-900"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium leading-5">{issue.message}</p>
                  <span className="text-[10px] uppercase tracking-wide">{issue.level}</span>
                </div>
                {issue.cell_id && <p className="mt-1 text-[11px] opacity-80">Cell: {issue.cell_id}</p>}
                {issue.suggestion && <p className="mt-2 text-[11px] leading-5 opacity-90">建议：{issue.suggestion}</p>}
              </article>
            ))
          ) : (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
              当前版本没有检测到结构化问题。
            </div>
          )}

          {suggestions.length > 0 && (
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
              <p className="font-medium text-slate-900">优先建议</p>
              <ul className="mt-2 space-y-1.5 text-[11px] leading-5 text-slate-600">
                {suggestions.map((suggestion) => (
                  <li key={suggestion}>- {suggestion}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 flex shrink-0 flex-wrap gap-2">
        <button
          type="button"
          onClick={handleRevalidate}
          disabled={isRevalidating}
          className={`${buttonClass} border-slate-300 bg-white text-slate-700 hover:bg-slate-50`}
        >
          {isRevalidating ? "重新校验中..." : syncStatus === "dirty" ? "校验当前草稿" : "重新校验"}
        </button>
        <button
          type="button"
          onClick={() => requestAiRetry()}
          disabled={!validation}
          className={`${buttonClass} border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100`}
        >
          让 AI 按审稿结果修正
        </button>
      </div>
    </section>
  );
}
