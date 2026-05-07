/**
 * ExportPanel 组件 — 导出按钮面板。
 * 支持四种导出格式: HTML / PDF / PPTX保真 / PPTX可编辑。
 * 导出操作通过 REST API 调用后端服务。
 */
"use client";

import { useCallback, useEffect, useState, type FC } from "react";
import { useChatStore } from "@/stores/chatStore";
import type { ExportCapabilitiesResponse } from "@/lib/packages";

/** 导出格式配置 */
const EXPORT_FORMATS = [
  {
    id: "html",
    label: "HTML",
    icon: "🌐",
    desc: "独立网页，浏览器直接打开",
  },
  {
    id: "pdf",
    label: "PDF",
    icon: "📄",
    desc: "高质量 PDF，Playwright 渲染",
  },
  {
    id: "pptx-faithful",
    label: "PPTX 保真",
    icon: "📊",
    desc: "截图方式，视觉完全一致",
  },
  {
    id: "pptx-editable",
    label: "PPTX 编辑",
    icon: "📝",
    desc: "文本方式，内容可继续编辑",
  },
] as const;

interface ExportPanelProps {
  /** 面板是否可见 */
  visible: boolean;
  /** 关闭面板 */
  onClose: () => void;
}

export const ExportPanel: FC<ExportPanelProps> = ({ visible, onClose }) => {
  const presentationId = useChatStore((s) => s.presentationId);
  const exportStatus = useChatStore((s) => s.exportStatus);
  const exportFormat = useChatStore((s) => s.exportFormat);
  const setExportStatus = useChatStore((s) => s.setExportStatus);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<ExportCapabilitiesResponse["formats"]>({});

  useEffect(() => {
    if (!visible) return;

    let active = true;
    const loadCapabilities = async () => {
      try {
        const res = await fetch("/api/presentations/export-capabilities");
        const data = (await res.json()) as ExportCapabilitiesResponse;
        if (!res.ok || !active) return;
        setCapabilities(data.formats || {});
      } catch {
        if (active) {
          setCapabilities({});
        }
      }
    };

    void loadCapabilities();
    return () => {
      active = false;
    };
  }, [visible]);

  const handleExport = useCallback(
    async (format: string) => {
      if (!presentationId) return;
      const capability = capabilities[format];
      if (capability && !capability.available) {
        setExportStatus("error", format);
        setErrorMsg(capability.reason || "当前环境暂不可用");
        return;
      }

      setExportStatus("exporting", format);
      setErrorMsg(null);

      try {
        const res = await fetch(
          `/api/presentations/${presentationId}/export/${format}`,
          { method: "POST" }
        );
        const data = await res.json();

        if (!res.ok || data.error) {
          setExportStatus("error", format);
          setErrorMsg(data.detail || data.error || "导出失败");
          return;
        }

        if (data.download_url) {
          setExportStatus("done", format);
          // 触发浏览器下载
          const a = document.createElement("a");
          a.href = data.download_url;
          a.download = "";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);

          // 3 秒后重置状态
          setTimeout(() => setExportStatus("idle"), 3000);
        }
      } catch (err) {
        setExportStatus("error", format);
        setErrorMsg(`导出失败: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
    [capabilities, presentationId, setExportStatus]
  );

  if (!visible) return null;

  return (
    <div className="absolute right-0 top-12 z-50 w-72 bg-white rounded-lg shadow-xl border border-gray-200 overflow-hidden">
      {/* 标题 */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">📥 导出演示文稿</h3>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none"
        >
          ×
        </button>
      </div>

      {/* 格式按钮列表 */}
      <div className="p-3 space-y-2">
        {EXPORT_FORMATS.map((fmt) => {
          const capability = capabilities[fmt.id];
          const isExporting =
            exportStatus === "exporting" && exportFormat === fmt.id;
          const isDone = exportStatus === "done" && exportFormat === fmt.id;
          const isError = exportStatus === "error" && exportFormat === fmt.id;
          const isUnavailable = capability ? !capability.available : false;
          const desc = isUnavailable && capability.reason ? capability.reason : fmt.desc;

          return (
            <button
              key={fmt.id}
              onClick={() => handleExport(fmt.id)}
              disabled={exportStatus === "exporting" || !presentationId || isUnavailable}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all text-left ${
                isExporting
                  ? "border-blue-200 bg-blue-50"
                  : isDone
                  ? "border-green-200 bg-green-50"
                  : isError
                  ? "border-red-200 bg-red-50"
                  : "border-gray-100 hover:border-gray-200 hover:bg-gray-50"
              } disabled:opacity-50`}
            >
              <span className="text-xl">{fmt.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-gray-800">
                  {fmt.label}
                </div>
                <div className={`text-xs truncate ${isUnavailable ? "text-amber-600" : "text-gray-400"}`}>
                  {desc}
                </div>
              </div>
              {isExporting && (
                <span className="text-xs text-blue-500 animate-pulse">
                  导出中...
                </span>
              )}
              {isUnavailable && !isExporting && !isDone && !isError && (
                <span className="text-xs text-amber-600">不可用</span>
              )}
              {isDone && (
                <span className="text-xs text-green-600">✅</span>
              )}
              {isError && (
                <span className="text-xs text-red-500">❌</span>
              )}
            </button>
          );
        })}
      </div>

      {/* 错误信息 */}
      {errorMsg && (
        <div className="px-4 py-2 text-xs text-red-500 bg-red-50 border-t border-red-100">
          {errorMsg}
        </div>
      )}
    </div>
  );
};
