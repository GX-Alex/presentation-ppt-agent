"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Download, FileOutput, Loader2, PlayCircle, RefreshCw } from "lucide-react";

import {
  type ArtifactVariantRecord,
  type PackageExecutionLogRecord,
  getPackageArtifactVariants,
  getPackageExecutionLogs,
  normalizePackageFileUrl,
} from "@/lib/packages";

interface PackageActivityPanelProps {
  packageId: string;
  compact?: boolean;
  defaultOpen?: boolean;
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDuration(durationMs?: number | null): string {
  if (durationMs == null || Number.isNaN(durationMs)) return "耗时未知";
  if (durationMs < 1000) return `${durationMs}ms`;
  return `${(durationMs / 1000).toFixed(durationMs >= 10000 ? 0 : 1)}s`;
}

function getExecutionKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    import: "导入",
    install: "安装",
    upgrade: "升级",
    rollback: "回滚",
    toggle: "启停",
    workflow: "工作流",
    render: "渲染",
  };
  return labels[kind] || kind;
}

function getStatusTone(status: string): string {
  if (status === "failed") return "bg-red-50 text-red-700 ring-red-100";
  if (status === "running") return "bg-amber-50 text-amber-700 ring-amber-100";
  return "bg-emerald-50 text-emerald-700 ring-emerald-100";
}

function getStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    succeeded: "成功",
    failed: "失败",
    running: "运行中",
  };
  return labels[status] || status;
}

export default function PackageActivityPanel({
  packageId,
  compact = false,
  defaultOpen,
}: PackageActivityPanelProps) {
  const [open, setOpen] = useState(defaultOpen ?? !compact);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [logs, setLogs] = useState<PackageExecutionLogRecord[]>([]);
  const [variants, setVariants] = useState<ArtifactVariantRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadActivity = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [logItems, variantItems] = await Promise.all([
        getPackageExecutionLogs(packageId, { limit: compact ? 4 : 8 }),
        getPackageArtifactVariants(packageId),
      ]);
      setLogs(logItems || []);
      setVariants((variantItems || []).slice(0, compact ? 4 : 8));
      setLoaded(true);
    } catch (loadError) {
      console.error("[Packages] 加载活动记录失败:", loadError);
      setError(loadError instanceof Error ? loadError.message : "加载活动记录失败");
    } finally {
      setLoading(false);
    }
  }, [compact, packageId]);

  useEffect(() => {
    if (open && !loaded) {
      void loadActivity();
    }
  }, [loadActivity, loaded, open]);

  const visibleLogs = useMemo(() => logs.slice(0, compact ? 3 : 6), [compact, logs]);
  const visibleVariants = useMemo(() => variants.slice(0, compact ? 3 : 6), [compact, variants]);

  return (
    <div className="mt-4 rounded-xl border border-slate-100 bg-slate-50/70 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Activity</p>
          <p className="mt-1 text-xs text-slate-500">
            导出历史 {variants.length} 条，运行记录 {logs.length} 条。
          </p>
        </div>
        <div className="flex items-center gap-2">
          {open ? (
            <button
              onClick={() => void loadActivity()}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100"
              disabled={loading}
            >
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              刷新
            </button>
          ) : null}
          <button
            onClick={() => setOpen((current) => !current)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-100"
          >
            {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            {open ? "收起" : "展开"}
          </button>
        </div>
      </div>

      {open ? (
        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-white/80 bg-white p-3 shadow-sm shadow-slate-100/40">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
              <FileOutput className="h-3.5 w-3.5 text-blue-600" />
              导出历史
            </div>
            <div className="mt-3 space-y-2">
              {visibleVariants.length > 0 ? (
                visibleVariants.map((variant) => {
                  const downloadUrl = normalizePackageFileUrl(variant.file_url);
                  return (
                    <div key={variant.id} className="rounded-lg border border-slate-100 bg-slate-50/70 p-2.5">
                      <div className="flex items-center justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium text-slate-800">{variant.variant_type}</p>
                          <p className="mt-1 text-[11px] text-slate-500">
                            {variant.package_version ? `v${variant.package_version}` : "版本未知"}
                            {variant.presentation_id ? ` · ${variant.presentation_id}` : ""}
                          </p>
                        </div>
                        {downloadUrl ? (
                          <a
                            href={downloadUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 rounded-lg bg-blue-50 px-2 py-1 text-[11px] font-medium text-blue-700 hover:bg-blue-100"
                          >
                            <Download className="h-3.5 w-3.5" />
                            下载
                          </a>
                        ) : null}
                      </div>
                      <p className="mt-2 text-[11px] text-slate-500">{formatTimestamp(variant.updated_at || variant.created_at)}</p>
                    </div>
                  );
                })
              ) : loading ? (
                <p className="text-xs text-slate-400">正在加载导出历史...</p>
              ) : (
                <p className="text-xs text-slate-400">暂无导出历史。</p>
              )}
            </div>
          </div>

          <div className="rounded-xl border border-white/80 bg-white p-3 shadow-sm shadow-slate-100/40">
            <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
              <PlayCircle className="h-3.5 w-3.5 text-emerald-600" />
              Workflow 运行记录
            </div>
            <div className="mt-3 space-y-2">
              {visibleLogs.length > 0 ? (
                visibleLogs.map((log) => (
                  <div key={log.id} className="rounded-lg border border-slate-100 bg-slate-50/70 p-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-slate-800">
                          {getExecutionKindLabel(log.execution_kind)}
                          {log.target_id ? ` · ${log.target_id}` : ""}
                        </p>
                        <p className="mt-1 text-[11px] text-slate-500">
                          {formatTimestamp(log.started_at)} · {formatDuration(log.duration_ms)}
                        </p>
                      </div>
                      <span className={`rounded-full px-2 py-1 text-[11px] ring-1 ${getStatusTone(log.status)}`}>
                        {getStatusLabel(log.status)}
                      </span>
                    </div>
                    {log.error_message ? (
                      <p className="mt-2 text-[11px] text-red-600">{log.error_message}</p>
                    ) : log.package_version ? (
                      <p className="mt-2 text-[11px] text-slate-500">运行版本: v{log.package_version}</p>
                    ) : null}
                  </div>
                ))
              ) : loading ? (
                <p className="text-xs text-slate-400">正在加载运行记录...</p>
              ) : (
                <p className="text-xs text-slate-400">暂无运行记录。</p>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {open && error ? <p className="mt-3 text-xs text-red-600">{error}</p> : null}
    </div>
  );
}