"use client";

import { useEffect, useMemo, useState } from "react";
import AppImage from "@/components/ui/AppImage";
import { getDrawIoViewerUrl } from "@/lib/drawio";
import { getAssetKindLabel } from "@/lib/assetTypes";
import { useRouter } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Download,
  ExternalLink,
  FileText,
  Loader2,
  MessageSquare,
  Presentation,
  X,
} from "lucide-react";

export interface PreviewAssetItem {
  id: string;
  title: string;
  fileType: string;
  mimeType?: string | null;
  fileUrl?: string | null;
  thumbnailUrl?: string | null;
  taskId?: string | null;
  description?: string | null;
  sourceLabel?: string | null;
}

interface AssetPreviewModalProps {
  open: boolean;
  item: PreviewAssetItem | null;
  onClose: () => void;
}

type PreviewKind = "image" | "markdown" | "text" | "html" | "pdf" | "office" | "ppt" | "drawio" | "unsupported" | "unsupported-strictly";

function normalizeAssetUrl(url?: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/")) return url;
  return `/${url}`;
}

function getExtension(url?: string | null): string {
  if (!url) return "";
  const cleanUrl = url.split("?")[0] || url;
  const parts = cleanUrl.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function getPreviewKind(item: PreviewAssetItem | null): PreviewKind {
  if (!item) return "unsupported";

  const fileType = item.fileType?.toLowerCase() || "";
  const mimeType = item.mimeType?.toLowerCase() || "";
  const ext = getExtension(item.fileUrl);

  if (fileType === "image" || mimeType.startsWith("image/")) return "image";
  if (mimeType.includes("markdown") || ext === "md" || ext === "markdown") return "markdown";
  if (mimeType === "application/pdf" || ext === "pdf") return "pdf";
  if (mimeType.includes("html") || ext === "html" || ext === "htm") return "html";
  if (fileType === "drawio" || ext === "drawio") return "drawio";
  if (["zip", "rar", "7z", "tar", "gz"].includes(ext)) return "unsupported-strictly";
  if (
    fileType === "document" ||
    fileType === "code" ||
    mimeType.startsWith("text/") ||
    ["txt", "json", "csv", "xml", "js", "ts", "tsx", "jsx", "py", "java", "sql", "yaml", "yml", "css"].includes(ext)
  ) {
    return "text";
  }
  if (
    fileType === "ppt" ||
    ["ppt", "pptx"].includes(ext) ||
    mimeType.includes("ms-powerpoint") ||
    mimeType.includes("presentation")
  ) {
    return "ppt";
  }
  if (
    ["doc", "docx", "xls", "xlsx"].includes(ext) ||
    mimeType.includes("officedocument")
  ) {
    return "office";
  }
  return "unsupported";
}

export default function AssetPreviewModal({ open, item, onClose }: AssetPreviewModalProps) {
  const router = useRouter();
  const [textContent, setTextContent] = useState<string>("");
  const [isLoadingText, setIsLoadingText] = useState(false);
  const [textError, setTextError] = useState<string | null>(null);

  const fileUrl = useMemo(() => normalizeAssetUrl(item?.fileUrl), [item?.fileUrl]);
  const thumbnailUrl = useMemo(() => normalizeAssetUrl(item?.thumbnailUrl), [item?.thumbnailUrl]);
  const previewKind = useMemo(() => getPreviewKind(item), [item]);

  useEffect(() => {
    if (!open || !item || previewKind !== "text" && previewKind !== "markdown") {
      setTextContent("");
      setTextError(null);
      setIsLoadingText(false);
      return;
    }

    if (!fileUrl) {
      setTextError("该文件没有可读取的地址");
      return;
    }

    const controller = new AbortController();

    const loadText = async () => {
      setIsLoadingText(true);
      setTextError(null);
      try {
        const res = await fetch(fileUrl, { signal: controller.signal });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const text = await res.text();
        setTextContent(text);
      } catch (error) {
        if ((error as Error).name === "AbortError") return;
        console.error("[AssetPreviewModal] 加载文本预览失败:", error);
        setTextError("加载预览失败，请尝试在新标签页中打开");
      } finally {
        setIsLoadingText(false);
      }
    };

    loadText();
    return () => controller.abort();
  }, [open, item, fileUrl, previewKind]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open || !item) return null;

  const renderPreview = () => {
    if (!fileUrl && !thumbnailUrl) {
      return (
        <div className="flex h-full items-center justify-center rounded-2xl border border-dashed border-gray-200 bg-gray-50 text-sm text-gray-500">
          当前文件缺少可预览内容
        </div>
      );
    }

    if (previewKind === "image" && fileUrl) {
      return (
        <div className="flex h-full items-center justify-center overflow-auto rounded-2xl bg-gray-50 p-4">
          <div className="relative h-full w-full">
            <AppImage
              src={fileUrl}
              alt={item.title}
              fill
              sizes="(max-width: 1280px) 100vw, 1280px"
              className="rounded-xl object-contain shadow-sm"
            />
          </div>
        </div>
      );
    }

    if ((previewKind === "markdown" || previewKind === "text") && isLoadingText) {
      return (
        <div className="flex h-full items-center justify-center gap-3 rounded-2xl bg-gray-50 text-sm text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在加载预览...
        </div>
      );
    }

    if ((previewKind === "markdown" || previewKind === "text") && textError) {
      return (
        <div className="flex h-full items-center justify-center rounded-2xl bg-gray-50 px-6 text-sm text-gray-500">
          {textError}
        </div>
      );
    }

    if (previewKind === "markdown") {
      return (
        <div className="h-full overflow-auto rounded-2xl bg-white p-6">
          <div className="prose prose-slate max-w-none prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-a:text-blue-600 prose-img:rounded-xl">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{textContent}</ReactMarkdown>
          </div>
        </div>
      );
    }

    if (previewKind === "text") {
      return (
        <div className="h-full overflow-auto rounded-2xl bg-[#0b1020] p-0">
          <pre className="min-h-full whitespace-pre-wrap break-words p-6 font-mono text-sm leading-6 text-slate-100">
            {textContent}
          </pre>
        </div>
      );
    }

    if (previewKind === "drawio" && fileUrl) {
      const fullUrl = fileUrl.startsWith('http') ? fileUrl : window.location.origin + fileUrl;
      const viewerUrl = getDrawIoViewerUrl(fullUrl, item.title);
      return (
        <iframe
          title={`${item.title}-drawio-preview`}
          src={viewerUrl}
          className="h-full w-full rounded-2xl border border-gray-200 bg-white"
        />
      );
    }

    if (previewKind === "ppt" && fileUrl) {
      if (fileUrl.endsWith('.html') || fileUrl.endsWith('.htm')) {
        return (
          <iframe
            title={`${item.title}-preview`}
            src={fileUrl}
            className="h-full w-full rounded-2xl border border-gray-200 bg-white"
          />
        );
      }
      
      // 检查是否为本地环境，Office Web Viewer 无法读取 localhost 的文件
      if (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')) {
        return (
          <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl bg-gradient-to-br from-amber-50 via-white to-orange-50 p-8 text-center">
            {thumbnailUrl ? (
              <AppImage
                src={thumbnailUrl}
                alt={item.title}
                width={1280}
                height={720}
                className="max-h-64 h-auto w-auto rounded-xl border border-gray-200 object-contain shadow-sm"
              />
            ) : (
              <Presentation className="h-16 w-16 text-orange-500" />
            )}
            <div>
              <p className="text-base font-medium text-gray-900">本地环境无法直接渲染 PPTX</p>
              <p className="mt-1 text-sm text-gray-500">微软预览服务需要公网地址。您可点击下方按钮下载</p>
            </div>
          </div>
        );
      }

      const fullUrl = fileUrl.startsWith('http') ? fileUrl : window.location.origin + fileUrl;
      const viewerUrl = `https://view.officeapps.live.com/op/embed.aspx?src=${encodeURIComponent(fullUrl)}`;
      return (
        <iframe
          title={`${item.title}-ppt-preview`}
          src={viewerUrl}
          className="h-full w-full rounded-2xl border border-gray-200 bg-white"
        />
      );
    }

    if (previewKind === "unsupported-strictly") {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl bg-gray-50 p-8 text-center">
          <FileText className="h-14 w-14 text-gray-400" />
          <div>
            <p className="text-base font-medium text-gray-900">此类文件无法在线预览</p>
            <p className="mt-1 text-sm text-gray-500">请使用下方按钮下载后查看</p>
          </div>
        </div>
      );
    }

    if ((previewKind === "html" || previewKind === "pdf") && fileUrl) {
      return (
        <iframe
          title={`${item.title}-preview`}
          src={fileUrl}
          className="h-full w-full rounded-2xl border border-gray-200 bg-white"
        />
      );
    }

    if (previewKind === "office") {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl bg-gradient-to-br from-amber-50 via-white to-orange-50 p-8 text-center">
          {thumbnailUrl ? (
            <AppImage
              src={thumbnailUrl}
              alt={item.title}
              width={1280}
              height={720}
              className="max-h-64 h-auto w-auto rounded-xl border border-gray-200 object-contain shadow-sm"
            />
          ) : (
            <Presentation className="h-16 w-16 text-orange-500" />
          )}
          <div>
            <p className="text-base font-medium text-gray-900">此类型不适合直接内嵌预览</p>
            <p className="mt-1 text-sm text-gray-500">可使用下方按钮在新标签页打开或下载文件</p>
          </div>
        </div>
      );
    }

    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 rounded-2xl bg-gray-50 p-8 text-center">
        {thumbnailUrl ? (
          <AppImage
            src={thumbnailUrl}
            alt={item.title}
            width={1280}
            height={720}
            className="max-h-64 h-auto w-auto rounded-xl border border-gray-200 object-contain shadow-sm"
          />
        ) : (
          <FileText className="h-14 w-14 text-gray-400" />
        )}
        <div>
          <p className="text-base font-medium text-gray-900">暂不支持直接预览此类型</p>
          <p className="mt-1 text-sm text-gray-500">可在新标签页中打开或直接下载</p>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" onClick={onClose} />
      <div className="relative flex h-[85vh] w-full max-w-6xl flex-col overflow-hidden rounded-[28px] border border-white/60 bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-5">
          <div className="min-w-0">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-400">公共空间预览</p>
            <h2 className="mt-1 truncate text-xl font-semibold text-gray-900">{item.title}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span className="rounded-full bg-gray-100 px-2.5 py-1">{getAssetKindLabel(item)}</span>
              {item.sourceLabel ? <span className="rounded-full bg-gray-100 px-2.5 py-1">{item.sourceLabel}</span> : null}
              {item.description ? <span className="truncate">{item.description}</span> : null}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
            title="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="min-h-0 flex-1 p-6">{renderPreview()}</div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 bg-gray-50/70 px-6 py-4">
          <div className="flex flex-wrap items-center gap-2">
            {item.taskId ? (
              <button
                onClick={() => router.push(`/chat/${item.taskId}`)}
                className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm ring-1 ring-gray-200 transition-colors hover:bg-gray-100"
              >
                <MessageSquare className="h-4 w-4" />
                查看对话
              </button>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {fileUrl ? (
              <a
                href={fileUrl}
                download
                className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm ring-1 ring-gray-200 transition-colors hover:bg-gray-100"
              >
                <Download className="h-4 w-4" />
                下载
              </a>
            ) : null}
            {fileUrl ? (
              <a
                href={fileUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-2 rounded-xl bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-black"
              >
                <ExternalLink className="h-4 w-4" />
                新标签打开
              </a>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}