/**
 * Deck 页面预览 — 中央区域展示当前页面 HTML。
 * 对齐 high.md §5.3.5 / §8.3。
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, FileText, Layers3 } from "lucide-react";
import { useDeckStore } from "@/stores/deckStore";
import type { DeckPageData } from "@/stores/deckStore";
import { useToast } from "@/components/ui/Toast";

function ensureHtmlDocument(content: string, title: string): string {
  if (/<html[\s>]/i.test(content) || /<!doctype/i.test(content)) {
    return content;
  }

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${title}</title>
  <style>
    html, body {
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #0f172a;
    }

    body {
      display: flex;
      align-items: stretch;
      justify-content: stretch;
    }
  </style>
</head>
<body>
${content}
</body>
</html>`;
}

function getHtmlFilename(baseName: string): string {
  const trimmed = baseName.trim();
  const normalized = trimmed
    .replace(/[\\/:*?"<>|]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return `${normalized || "webdeck"}.html`;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function composeDeckDocumentFromPages(title: string, pages: DeckPageData[]): string | null {
  const readyPages = pages.filter((page) => Boolean(page.html?.trim()));
  if (readyPages.length === 0) {
    return null;
  }

  const totalPages = readyPages.length;

  // P0: 每页包裹在 .deck-slide 中，第一页加 active 类
  const slidesHtml = readyPages
    .map(
      (page, index) =>
        `<div class="deck-slide${index === 0 ? " active" : ""}">` +
        `<div class="deck-stage">${page.html || ""}</div>` +
        `</div>`
    )
    .join("\n");

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>${escapeHtml(title)}</title>
  <style>
    /* ── Reset ── */
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html, body {
      width: 100%; height: 100%;
      overflow: hidden;
      background: #0f172a;
      color: #e2e8f0;
      font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
    }
    @page { size: 1280px 720px; margin: 0; }

    /* ── P0: 全屏幻灯片容器 ── */
    #slides-container { position: fixed; inset: 0; }

    .deck-slide {
      position: absolute; inset: 0;
      display: none;
      overflow: hidden;
    }
    .deck-slide.active { display: block; }

    /* P2: 固定 1280×720 画布，通过 JS scale+translate 居中适配视口 */
    .deck-stage {
      width: 1280px; height: 720px;
      position: absolute; top: 0; left: 0;
      transform-origin: 0 0;
      overflow: hidden;
    }
    .deck-stage > *,
    .deck-stage > section,
    .deck-stage > [data-page-id] {
      width: 100% !important; height: 100% !important;
      max-height: 100% !important; min-height: 0 !important;
      overflow: hidden !important; box-sizing: border-box !important;
    }

    /* ── 顶部进度条 ── */
    #deck-progress { position: fixed; top: 0; left: 0; right: 0; height: 3px; background: rgba(255,255,255,0.08); z-index: 1000; }
    #deck-progress-bar { height: 100%; background: #3b82f6; transition: width 0.3s ease; width: 0%; }

    /* ── P0: 右下角幽灵导航覆层 ── */
    #deck-nav-overlay {
      position: fixed; bottom: 24px; right: 24px;
      display: flex; align-items: center; gap: 8px;
      z-index: 1000; opacity: 0.25; transition: opacity 0.2s;
    }
    #deck-nav-overlay:hover { opacity: 1; }
    .deck-nav-btn {
      display: flex; align-items: center; justify-content: center;
      width: 36px; height: 36px; border-radius: 50%;
      border: 1px solid rgba(255,255,255,0.25);
      background: rgba(0,0,0,0.55); color: rgba(255,255,255,0.85);
      cursor: pointer; transition: all 0.15s;
      backdrop-filter: blur(8px); font-size: 18px;
    }
    .deck-nav-btn:hover { background: rgba(255,255,255,0.15); color: white; }
    .deck-nav-btn:disabled { opacity: 0.3; cursor: not-allowed; }
    #deck-page-indicator { font-size: 11px; color: rgba(255,255,255,0.65); min-width: 40px; text-align: center; }

    /* ── P1: CSS 变量 + shadcn/ui 风格组件类 (.s- 前缀) ── */
    :root { --accent: #3b82f6; --s-card-bg: rgba(255,255,255,0.04); --s-card-border: rgba(255,255,255,0.1); --s-radius: 12px; }
    .s-card { background: var(--s-card-bg); border: 1px solid var(--s-card-border); border-radius: var(--s-radius); padding: 1rem 1.25rem; }
    .s-card-hover { transition: all 0.2s; }
    .s-card-hover:hover { background: rgba(255,255,255,0.07); transform: translateY(-2px); }
    .s-grid-2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; }
    .s-grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; }
    .s-grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; }
    .s-flex { display: flex; align-items: center; gap: 0.75rem; }
    .s-flex-col { display: flex; flex-direction: column; gap: 0.75rem; }
    .s-alert { border-left: 4px solid var(--accent); background: rgba(59,130,246,0.08); border-radius: 0 var(--s-radius) var(--s-radius) 0; padding: 0.75rem 1rem; }
    .s-alert-warn { border-color: #f59e0b; background: rgba(245,158,11,0.08); }
    .s-alert-error { border-color: #ef4444; background: rgba(239,68,68,0.08); }
    .s-alert-success { border-color: #22c55e; background: rgba(34,197,94,0.08); }
    .s-badge { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: 0.75rem; font-weight: 600; background: rgba(59,130,246,0.15); color: #93c5fd; border: 1px solid rgba(59,130,246,0.3); }
    .s-code { font-family: "JetBrains Mono","Fira Code",monospace; background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 0.2em 0.5em; font-size: 0.85em; }
    .s-stat { text-align: center; }
    .s-stat-value { font-size: 2.5rem; font-weight: 800; color: var(--accent); line-height: 1; }
    .s-stat-label { font-size: 0.8rem; color: rgba(255,255,255,0.55); margin-top: 0.25rem; }
    .s-table { width: 100%; border-collapse: collapse; }
    .s-table th { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.5); border-bottom: 1px solid rgba(255,255,255,0.1); padding: 0.5rem 0.75rem; text-align: left; }
    .s-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 0.875rem; }
    .s-table tr:last-child td { border-bottom: none; }
    .s-divider { height: 1px; background: rgba(255,255,255,0.1); margin: 0.75rem 0; }

    /* ── 打印：每页独立输出 ── */
    @media print {
      * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
      #deck-nav-overlay, #deck-progress { display: none !important; }
      html, body { overflow: visible !important; background: #0f172a !important; }
      #slides-container { position: static !important; }
      .deck-slide {
        display: block !important; position: static !important;
        page-break-after: always; break-after: page;
        width: 100vw !important; height: 56.25vw !important;
      }
      .deck-slide:last-child { page-break-after: auto; break-after: auto; }
      .deck-stage { transform: none !important; width: 100% !important; height: auto !important; overflow: visible !important; max-height: none !important; }
      .deck-stage > *,
      .deck-stage > section,
      .deck-stage > [data-page-id] {
        overflow: visible !important;
        max-height: none !important;
        height: auto !important;
      }
      iconify-icon { display: none !important; }
    }
  </style>
</head>
<body>
  <div id="deck-progress"><div id="deck-progress-bar"></div></div>

  <div id="slides-container">
${slidesHtml}
  </div>

  <div id="deck-nav-overlay">
    <button class="deck-nav-btn" id="prevBtn" onclick="prevPage()" aria-label="上一页" title="上一页 (←)">
      <iconify-icon icon="mdi:chevron-left"></iconify-icon>
    </button>
    <span id="deck-page-indicator">1 / ${totalPages}</span>
    <button class="deck-nav-btn" id="nextBtn" onclick="nextPage()" aria-label="下一页" title="下一页 (→)">
      <iconify-icon icon="mdi:chevron-right"></iconify-icon>
    </button>
  </div>

  <script>
    var totalPages = ${totalPages};
    var currentPage = 0;
    var slides = document.querySelectorAll('.deck-slide');

    function scaleSlide(slide) {
      var stage = slide.querySelector('.deck-stage');
      if (!stage) return;
      var vw = slide.offsetWidth || window.innerWidth;
      var vh = slide.offsetHeight || window.innerHeight;
      var scale = Math.min(vw / 1280, vh / 720);
      var ox = (vw - 1280 * scale) / 2;
      var oy = (vh - 720 * scale) / 2;
      stage.style.transform = 'translate(' + ox + 'px, ' + oy + 'px) scale(' + scale + ')';
    }

    function scaleAllSlides() { slides.forEach(function(s) { scaleSlide(s); }); }

    function goToPage(index) {
      if (index < 0 || index >= totalPages) return;
      slides[currentPage].classList.remove('active');
      currentPage = index;
      slides[currentPage].classList.add('active');
      scaleSlide(slides[currentPage]);
      updateUI();
    }

    function nextPage() { goToPage(currentPage + 1); }
    function prevPage() { goToPage(currentPage - 1); }

    function updateUI() {
      document.getElementById('deck-progress-bar').style.width = ((currentPage + 1) / totalPages * 100) + '%';
      document.getElementById('deck-page-indicator').textContent = (currentPage + 1) + ' / ' + totalPages;
      document.getElementById('prevBtn').disabled = currentPage === 0;
      document.getElementById('nextBtn').disabled = currentPage === totalPages - 1;
    }

    document.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault(); nextPage();
      } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
        e.preventDefault(); prevPage();
      }
    });

    window.addEventListener('load', function() { scaleAllSlides(); updateUI(); });
    window.addEventListener('resize', scaleAllSlides);
    // 两步初始化：立即尝试 + RAF 推迟确保布局完成后再缩放
    scaleAllSlides();
    requestAnimationFrame(function() { scaleAllSlides(); });
    updateUI();

    window.addEventListener('beforeprint', function() {
      // Disable dynamic scaling in print mode
      var stages = document.querySelectorAll('.deck-stage');
      stages.forEach(function(stage) {
        stage.style.transform = '';
        stage.style.transformOrigin = '';
        stage.style.width = '';
        stage.style.height = '';
      });
      var printSlides = document.querySelectorAll('[data-page-id], section.slide');
      printSlides.forEach(function(slide) {
        slide.style.transform = '';
        slide.style.transformOrigin = '';
        slide.style.width = '100%';
        slide.style.height = 'auto';
      });
    });
    window.addEventListener('afterprint', function() {
      // Restore scaling after print dialog closes
      if (typeof scaleAllSlides === 'function') {
        scaleAllSlides();
      }
    });
  <\/script>
</body>
</html>`;
}

export function DeckPagePreview() {
  const pages = useDeckStore((s) => s.pages);
  const currentPageIndex = useDeckStore((s) => s.currentPageIndex);
  const setCurrentPageIndex = useDeckStore((s) => s.setCurrentPageIndex);
  const finalHtml = useDeckStore((s) => s.finalHtml);
  const deckStatus = useDeckStore((s) => s.deckStatus);
  const manifest = useDeckStore((s) => s.manifest);
  const projectId = useDeckStore((s) => s.projectId);

  const toast = useToast();
  const fullscreenRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const lastPageIndexRef = useRef(currentPageIndex);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isExportingPptx, setIsExportingPptx] = useState(false);
  const [viewMode, setViewMode] = useState<"page" | "deck">("page");

  const currentPage = pages[currentPageIndex] || null;
  const totalPages = pages.length;
  const previewTitle = currentPage?.title || manifest?.topic || "Web Deck 预览";
  const exportTitle = manifest?.topic || previewTitle;
  const isDeckViewAvailable = deckStatus === "completed" && Boolean(finalHtml);
  const isDeckView = isDeckViewAvailable && viewMode === "deck";
  const canGoPrevious = currentPageIndex > 0;
  const canGoNext = currentPageIndex < totalPages - 1;

  const displayHtml = useMemo(() => {
    if (isDeckView && finalHtml) {
      return finalHtml;
    }
    return currentPage?.html || (isDeckViewAvailable ? finalHtml : null);
  }, [currentPage?.html, finalHtml, isDeckView, isDeckViewAvailable]);

  const previewDocument = useMemo(() => {
    if (!displayHtml) return null;
    return ensureHtmlDocument(displayHtml, previewTitle);
  }, [displayHtml, previewTitle]);

  const combinedDocument = useMemo(() => {
    const combinedHtml = finalHtml || composeDeckDocumentFromPages(exportTitle, pages);
    if (!combinedHtml) return null;
    return ensureHtmlDocument(combinedHtml, exportTitle);
  }, [exportTitle, finalHtml, pages]);

  // printDocument 专用于 PDF 打印：始终使用 composeDeckDocumentFromPages，
  // 不使用 finalHtml（finalHtml 是 Reveal-style 演示文稿，打印时只显示当前页）。
  const printDocument = useMemo(
    () => composeDeckDocumentFromPages(exportTitle, pages),
    [exportTitle, pages],
  );

  const exportDocument = combinedDocument || previewDocument;
  const iframeDocument = isFullscreen ? exportDocument : previewDocument;

  const canPersist = Boolean(exportDocument);
  const canPrint = Boolean(printDocument);
  const canExportPptx = Boolean(projectId) && pages.some((p) => Boolean(p.html));

  const handlePreviousPage = useCallback(() => {
    if (!canGoPrevious) return;
    setCurrentPageIndex(currentPageIndex - 1);
  }, [canGoPrevious, currentPageIndex, setCurrentPageIndex]);

  const handleNextPage = useCallback(() => {
    if (!canGoNext) return;
    setCurrentPageIndex(currentPageIndex + 1);
  }, [canGoNext, currentPageIndex, setCurrentPageIndex]);

  const handleDownload = useCallback(() => {
    if (!exportDocument) {
      toast.warning("当前没有可下载的整稿内容");
      return;
    }

    const fileName = getHtmlFilename(`${exportTitle}-${projectId?.slice(0, 8) || "deck"}`);
    const blob = new Blob([exportDocument], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    toast.success("HTML 下载完成");
  }, [exportDocument, exportTitle, projectId, toast]);

  const handleSaveToAssets = useCallback(async () => {
    if (!exportDocument) {
      toast.warning("当前没有可保存的整稿内容");
      return;
    }

    setIsSaving(true);
    try {
      const fileName = getHtmlFilename(`${exportTitle}-${projectId?.slice(0, 8) || "deck"}`);
      const file = new File([exportDocument], fileName, { type: "text/html" });
      const formData = new FormData();
      formData.append("files", file);

      const response = await fetch("/api/files/upload", {
        method: "POST",
        body: formData,
      });
      const data = await response.json();

      if (!response.ok || data.errors?.length > 0) {
        throw new Error(data.errors?.[0]?.error || data.detail || "保存失败");
      }

      toast.success("已保存至资产");
    } catch (error: unknown) {
      toast.error(`保存失败: ${error instanceof Error ? error.message : "内部错误"}`);
    } finally {
      setIsSaving(false);
    }
  }, [exportDocument, exportTitle, projectId, toast]);

  const handlePrint = useCallback(() => {
    if (!printDocument) {
      toast.warning("当前没有可打印的整稿内容");
      return;
    }

    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      toast.error("打印窗口被浏览器拦截，请允许弹窗后重试");
      return;
    }

    let hasPrinted = false;
    const triggerPrint = () => {
      if (hasPrinted) return;
      hasPrinted = true;
      printWindow.focus();
      window.setTimeout(() => {
        printWindow.print();
      }, 300);
    };

    printWindow.document.open();
    printWindow.document.write(printDocument);
    printWindow.document.close();
    printWindow.onafterprint = () => {
      printWindow.close();
    };
    printWindow.addEventListener("load", () => {
      window.setTimeout(triggerPrint, 600);
    }, { once: true });
    window.setTimeout(triggerPrint, 1400);
  }, [printDocument, toast]);

  const handleExportPptx = useCallback(async () => {
    if (!projectId) {
      toast.warning("项目 ID 不可用");
      return;
    }
    const hasDonePages = pages.some((p) => Boolean(p.html));
    if (!hasDonePages) {
      toast.warning("没有已完成的页面可导出");
      return;
    }

    setIsExportingPptx(true);
    try {
      const response = await fetch(`/api/webdeck/projects/${projectId}/export/pptx`, {
        method: "POST",
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "导出失败");
      }
      const downloadUrl = data.download_url as string;
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = `${exportTitle.replace(/[\\/:*?"<>|]+/g, "-")}.pptx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      toast.success("PPTX 导出完成，下载已开始");
    } catch (error: unknown) {
      toast.error(`PPTX 导出失败: ${error instanceof Error ? error.message : "内部错误"}`);
    } finally {
      setIsExportingPptx(false);
    }
  }, [projectId, pages, exportTitle, toast]);

  const toggleFullscreen = useCallback(() => {
    if (!fullscreenRef.current) return;
    if (document.fullscreenElement === fullscreenRef.current) {
      void document.exitFullscreen();
      return;
    }
    void fullscreenRef.current.requestFullscreen();
  }, []);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === fullscreenRef.current);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (deckStatus !== "completed") {
      setViewMode("page");
    }
  }, [deckStatus]);

  useEffect(() => {
    if (lastPageIndexRef.current !== currentPageIndex) {
      lastPageIndexRef.current = currentPageIndex;
      if (!isDeckView && !isFullscreen) {
        setViewMode("page");
      }
    }
  }, [currentPageIndex, isDeckView, isFullscreen]);

  // Sync currentPageIndex → iframe goToPage when showing combined document
  useEffect(() => {
    const showingCombined = isFullscreen || isDeckView;
    if (!showingCombined || !iframeRef.current) return;
    try {
      const win = iframeRef.current.contentWindow as (Window & { goToPage?: (i: number) => void }) | null;
      win?.goToPage?.(currentPageIndex);
    } catch {
      // ignore cross-origin or not-yet-loaded
    }
  }, [currentPageIndex, isFullscreen, isDeckView]);

  // Keyboard arrow navigation when fullscreen
  useEffect(() => {
    if (!isFullscreen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowRight" || event.key === "ArrowDown") {
        event.preventDefault();
        handleNextPage();
      } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
        event.preventDefault();
        handlePreviousPage();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isFullscreen, handleNextPage, handlePreviousPage]);

  const handleIframeLoad = useCallback(() => {
    const showingCombined = isFullscreen || isDeckView;
    if (!showingCombined || currentPageIndex === 0 || !iframeRef.current) return;
    try {
      const win = iframeRef.current.contentWindow as (Window & { goToPage?: (i: number) => void }) | null;
      win?.goToPage?.(currentPageIndex);
    } catch {
      // ignore
    }
  }, [isFullscreen, isDeckView, currentPageIndex]);

  if (!displayHtml) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        <div className="text-center">
          <div className="text-4xl mb-3">📄</div>
          <p className="text-sm">
            {currentPage?.status === "running"
              ? "页面生成中..."
              : currentPage?.status === "failed"
                ? "页面生成失败，可点击目录中的重试按钮"
                : "选择页面或等待生成"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={fullscreenRef}
      className="flex-1 relative overflow-hidden bg-[radial-gradient(circle_at_top,rgba(15,23,42,0.08),transparent_55%),linear-gradient(180deg,#f8fafc_0%,#e2e8f0_100%)]"
    >
      <div className="absolute inset-x-4 top-4 z-20 flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-2 rounded-2xl border border-gray-200 bg-white/90 px-3 py-2 text-xs text-gray-600 shadow-sm backdrop-blur-sm">
            <span className="font-semibold text-gray-800">
              {isDeckView ? "整稿预览" : `页面 ${currentPageIndex + 1}/${Math.max(totalPages, 1)}`}
            </span>
            {!isDeckView && currentPage && (
              <span className="max-w-48 truncate text-gray-500">{currentPage.title}</span>
            )}
          </div>

          {!isDeckView && totalPages > 1 && (
            <div className="flex items-center gap-1 rounded-2xl border border-gray-200 bg-white/90 p-1 shadow-sm backdrop-blur-sm">
              <button
                onClick={handlePreviousPage}
                disabled={!canGoPrevious}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                title="上一页"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                onClick={handleNextPage}
                disabled={!canGoNext}
                className="flex h-9 w-9 items-center justify-center rounded-xl text-gray-600 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-40"
                title="下一页"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {isDeckViewAvailable && currentPage?.html && (
            <div className="flex items-center gap-1 rounded-2xl border border-gray-200 bg-white/90 p-1 shadow-sm backdrop-blur-sm">
              <button
                onClick={() => setViewMode("page")}
                className={`flex items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors ${
                  !isDeckView
                    ? "bg-slate-900 text-white"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
                title="查看当前页"
              >
                <FileText className="h-3.5 w-3.5" />
                当前页
              </button>
              <button
                onClick={() => setViewMode("deck")}
                className={`flex items-center gap-1 rounded-xl px-3 py-1.5 text-xs font-medium transition-colors ${
                  isDeckView
                    ? "bg-slate-900 text-white"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
                title="查看整稿"
              >
                <Layers3 className="h-3.5 w-3.5" />
                整稿
              </button>
            </div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={handleSaveToAssets}
            disabled={isSaving || !canPersist}
            className="px-3 py-1.5 text-[11px] bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="将整份 Web Deck 保存到资产"
          >
            {isSaving ? "⏳ 保存中..." : "💾 保存至资产"}
          </button>
          <button
            onClick={handleDownload}
            disabled={!canPersist}
            className="px-3 py-1.5 text-[11px] bg-white/90 hover:bg-white text-gray-700 border border-gray-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="下载整份 Web Deck HTML"
          >
            ⬇️ 下载 HTML
          </button>
          <button
            onClick={handlePrint}
            disabled={!canPrint}
            className="px-3 py-1.5 text-[11px] bg-white/90 hover:bg-white text-gray-700 border border-gray-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="将整份 Web Deck 打印或导出为 PDF"
          >
            🖨 PDF/打印
          </button>
          <button
            onClick={handleExportPptx}
            disabled={isExportingPptx || !canExportPptx}
            className="px-3 py-1.5 text-[11px] bg-orange-50 hover:bg-orange-100 text-orange-700 border border-orange-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="导出为 PPTX 可编辑格式"
          >
            {isExportingPptx ? "⏳ 导出中..." : "📊 导出 PPTX"}
          </button>
          <button
            onClick={toggleFullscreen}
            disabled={!canPersist}
            className="px-3 py-1.5 text-[11px] bg-white/90 hover:bg-white text-gray-700 border border-gray-200 shadow-sm rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="全屏展示整份 Web Deck"
          >
            {isFullscreen ? "退出全屏" : "全屏"}
          </button>
        </div>
      </div>

      <div className="h-full w-full pt-24 md:pt-16">
        <iframe
          ref={iframeRef}
          srcDoc={iframeDocument || undefined}
          onLoad={handleIframeLoad}
          sandbox="allow-scripts allow-same-origin"
          className="w-full h-full border-0 bg-white"
          title={
            isFullscreen
              ? "Web Deck 全屏整稿展示"
              : isDeckView
              ? "Web Deck 预览"
              : `页面 ${currentPageIndex + 1} 预览`
          }
        />
      </div>
    </div>
  );
}
