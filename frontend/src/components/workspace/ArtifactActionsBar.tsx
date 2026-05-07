"use client";

import { useChatStore } from "@/stores/chatStore";
import { useDiagramStore } from "@/stores/diagramStore";
import { useState } from "react";
import { useToast } from "@/components/ui/Toast";

export function ArtifactActionsBar() {
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);
  const artifactContent = useChatStore((s) => s.artifactContent);
  const htmlArtifactContent = useChatStore((s) => s.htmlArtifactContent);
  const diagramXml = useDiagramStore((s) => s.xml);
  const latestSvg = useDiagramStore((s) => s.latestSvg);
  const latestPng = useDiagramStore((s) => s.latestPng);
  const version = useDiagramStore((s) => s.version);
  const syncStatus = useDiagramStore((s) => s.syncStatus);
  const [isSaving, setIsSaving] = useState(false);
  const toast = useToast();

  // PPT has its own PreviewPanel action bar.
  if (currentArtifactType === "none" || currentArtifactType === "ppt") {
    return null;
  }

  // Webdeck has its own viewer — only show HTML download button if we also have an HTML artifact
  if (currentArtifactType === "webdeck") {
    if (!htmlArtifactContent) return null;
    const handleDownloadHtml = () => {
      const blob = new Blob([htmlArtifactContent], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sandbox.html";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast.success("下载完成");
    };
    return (
      <div className="absolute top-4 right-4 z-[100]">
        <button
          onClick={handleDownloadHtml}
          className="px-3 py-1.5 text-[12px] bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all flex items-center gap-1 font-medium"
          title="下载 HTML 文件"
        >
          ⬇️ 下载 HTML
        </button>
      </div>
    );
  }

  // Get File Extension & Blob Configuration Based On Type
  const getFileConfig = () => {
    switch (currentArtifactType) {
      case "document":
        return { filename: "document.md", type: "text/markdown" };
      case "drawio":
        return { filename: "diagram.drawio", type: "application/xml" };
      case "code":
        return { filename: "artifact.txt", type: "text/plain" };
      case "webpage":
        return { filename: "sandbox.html", type: "text/html" };
      default:
        return { filename: "artifact.txt", type: "text/plain" };
    }
  };

  const effectiveArtifactContent = currentArtifactType === "drawio" ? (diagramXml || artifactContent) : artifactContent;

  const downloadBlob = (filename: string, content: string, mimeType: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const downloadDirectUrl = (filename: string, url: string) => {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };

  const handleDownload = async () => {
    if (!effectiveArtifactContent) {
      toast.warning("没有可供下载的内容");
      return;
    }
    const config = getFileConfig();
    downloadBlob(config.filename, effectiveArtifactContent, config.type);
    toast.success("下载完成");
  };

  const handleSaveToAssets = async () => {
    if (!effectiveArtifactContent) {
      toast.warning("没有可供保存的内容");
      return;
    }
    
    setIsSaving(true);
    try {
      const config = getFileConfig();
      const blob = new Blob([effectiveArtifactContent], { type: config.type });
      const file = new File([blob], config.filename, { type: config.type });

      // Build formData for /api/files/upload
      const formData = new FormData();
      formData.append("files", file);

      const res = await fetch("/api/files/upload", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        throw new Error("上传请求失败");
      }

      const data = await res.json();
      if (data.errors && data.errors.length > 0) {
        toast.error(`保存失败: ${data.errors[0].error}`);
      } else if (data.uploaded && data.uploaded.length > 0) {
        toast.success("已成功保存至资产");
      } else {
        toast.warning("服务器未返回结果");
      }
    } catch (error: unknown) {
      console.error("Save to assets error:", error);
      toast.error(`保存失败: ${error instanceof Error ? error.message : "内部错误"}`);
    } finally {
      setIsSaving(false);
    }
  };

  const actionButtons = (
    <>
      <button
        onClick={handleSaveToAssets}
        disabled={isSaving || !effectiveArtifactContent}
        className="px-3 py-1.5 text-[12px] bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
        title="保存至资产并持久化"
      >
        {isSaving ? "⏳ 保存中..." : "💾 保存至资产"}
      </button>

      <button
        onClick={handleDownload}
        disabled={!effectiveArtifactContent}
        className="px-3 py-1.5 text-[12px] bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
        title="将产物下载到本地"
      >
        ⬇️ 下载
      </button>
    </>
  );

  if (currentArtifactType === "drawio") {
    return (
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-gray-200/80 bg-white/95 px-4 py-3 backdrop-blur-sm">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-800">Draw.io 工作台</p>
          <p className="text-xs text-gray-500">
            当前版本 v{version || 0} · 状态 {syncStatus}。手动编辑会保留在当前任务中；通过对话继续修改时将以当前版本为基准。
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {latestSvg && (
            <button
              onClick={() => {
                if (latestSvg.startsWith("data:")) {
                  downloadDirectUrl("diagram.svg", latestSvg);
                } else {
                  downloadBlob("diagram.svg", latestSvg, "image/svg+xml");
                }
                toast.success("SVG 导出完成");
              }}
              className="px-3 py-1.5 text-[12px] bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all flex items-center gap-1 font-medium"
              title="下载 SVG 版本"
            >
              ⬇️ SVG
            </button>
          )}
          {latestPng && (
            <button
              onClick={() => {
                if (latestPng.startsWith("data:")) {
                  downloadDirectUrl("diagram.png", latestPng);
                } else {
                  downloadBlob("diagram.png", latestPng, "image/png");
                }
                toast.success("PNG 导出完成");
              }}
              className="px-3 py-1.5 text-[12px] bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all flex items-center gap-1 font-medium"
              title="下载 PNG 版本"
            >
              ⬇️ PNG
            </button>
          )}
          {actionButtons}
        </div>
      </div>
    );
  }

  return (
    <div className="absolute top-4 right-4 z-[100] flex flex-wrap items-center justify-end gap-2">
      {actionButtons}
    </div>
  );
}
