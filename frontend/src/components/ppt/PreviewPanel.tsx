/**
 * PreviewPanel 组件 — PPT 实时预览面板。
 * Sprint 2: iframe + reveal.js + 缩略图导航 + 全屏预览。
 * Sprint 3: 集成 WYSIWYG 编辑器 + 导出面板 + 版本历史。
 */
"use client";

import { useEffect, useRef, useMemo, useCallback, useState } from "react";
import { useChatStore, type SlideMetadata } from "@/stores/chatStore";
import { ExportPanel } from "./ExportPanel";
import { useToast } from "@/components/ui/Toast";

const REVEAL_JS_BASE = process.env.NEXT_PUBLIC_REVEAL_JS_BASE_URL ?? "/vendor/reveal.js";

/** 根据主题配置生成 CSS 变量 */
function getThemeCSS(themeId: string): { bg: string; headingColor: string; textColor: string; slideCSS: string } {
  const themes: Record<string, { bg: string; headingColor: string; textColor: string; slideCSS: string }> = {
    tech_dark: {
      bg: "#0f172a",
      headingColor: "#38bdf8",
      textColor: "#e2e8f0",
      slideCSS: `
        .reveal section { text-align: left; }
        .reveal h1, .reveal h2 { color: #38bdf8; font-weight: 700; }
        .reveal h3 { color: #818cf8; font-weight: 600; }
        .reveal ul { list-style: none; padding-left: 0; }
        .reveal ul li { padding: 8px 0; padding-left: 24px; position: relative; }
        .reveal ul li::before { content: '▸'; position: absolute; left: 0; color: #38bdf8; }
        .reveal code { background: #1e293b; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; }
        .reveal blockquote { border-left: 4px solid #38bdf8; padding-left: 16px; color: #94a3b8; }
      `,
    },
    business_light: {
      bg: "#ffffff",
      headingColor: "#1e40af",
      textColor: "#1e293b",
      slideCSS: `
        .reveal section { text-align: left; }
        .reveal h1, .reveal h2 { color: #1e40af; font-weight: 700; border-bottom: 3px solid #dbeafe; padding-bottom: 12px; }
        .reveal h3 { color: #2563eb; font-weight: 600; }
        .reveal code { background: #f1f5f9; padding: 2px 8px; border-radius: 4px; color: #1e40af; }
        .reveal blockquote { border-left: 4px solid #2563eb; padding-left: 16px; color: #64748b; background: #f8fafc; padding: 12px 16px; }
      `,
    },
    academic: {
      bg: "#fefce8",
      headingColor: "#78350f",
      textColor: "#1c1917",
      slideCSS: `
        .reveal section { text-align: left; }
        .reveal h1, .reveal h2 { color: #78350f; font-weight: 700; }
        .reveal h3 { color: #92400e; font-weight: 600; }
        .reveal code { background: #fef3c7; padding: 2px 8px; border-radius: 3px; }
        .reveal blockquote { border-left: 3px solid #b45309; padding-left: 16px; color: #78350f; font-style: italic; }
      `,
    },
  };
  return themes[themeId] || themes.tech_dark;
}

/** 构建 reveal.js HTML 文档（作为 iframe 的 srcdoc） */
function buildRevealHTML(slidesHtml: string[], themeId: string, title: string): string {
  const theme = getThemeCSS(themeId);
  const sections = slidesHtml.join("\n");

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title}</title>
  <link rel="stylesheet" href="${REVEAL_JS_BASE}/reveal.min.css">
  <link rel="stylesheet" href="${REVEAL_JS_BASE}/theme/black.min.css" id="theme">
  <style>
    :root {
      --r-background-color: ${theme.bg};
      --r-main-color: ${theme.textColor};
      --r-heading-color: ${theme.headingColor};
      --r-link-color: ${theme.headingColor};
      --r-main-font: 'Inter', 'Noto Sans SC', sans-serif;
      --r-heading-font: 'Inter', 'Noto Sans SC', sans-serif;
      --r-code-font: 'Fira Code', 'JetBrains Mono', monospace;
    }
    * { box-sizing: border-box; }
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: ${theme.bg};
    }
    .reveal {
      width: 100%;
      height: 100%;
      position: relative;
      font-size: 16px;
    }
    .reveal .slides {
      width: 100%;
      height: 100%;
      text-align: left;
      position: relative;
    }
    .reveal .slides section {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      padding: 44px 56px;
      box-sizing: border-box;
      overflow: hidden;
    }
    .reveal .slides section .slide-content {
      width: 100%;
      height: 100%;
      transform-origin: top left;
      will-change: transform;
    }
    .reveal .slides section .slide-content > * {
      max-width: 100%;
      overflow-wrap: break-word;
      word-break: break-word;
    }
    .reveal .slides section .slide-content > *:first-child { margin-top: 0; }
    .reveal .slides section .slide-content > *:last-child { margin-bottom: 0; }
    .reveal .slides section h1 { font-size: 2.25em; margin: 0 0 0.32em 0; line-height: 1.14; }
    .reveal .slides section h2 { font-size: 1.7em; margin: 0 0 0.3em 0; line-height: 1.2; }
    .reveal .slides section h3 { font-size: 1.26em; margin: 0.38em 0 0.22em; line-height: 1.28; }
    .reveal .slides section p { font-size: 0.96em; line-height: 1.48; margin: 0.24em 0; }
    .reveal .slides section ul, .reveal .slides section ol { font-size: 0.88em; line-height: 1.55; margin: 0.24em 0; padding-left: 1.3em; }
    .reveal .slides section li { margin: 0.18em 0; }
    .reveal .slides section img { max-width: 100%; max-height: 320px; object-fit: contain; display: block; margin: 0.4em auto; }
    .reveal .slides section video { max-width: 100%; max-height: 320px; object-fit: contain; }
    .reveal .slides section iframe { max-width: 100%; max-height: 320px; }
    .reveal .slides section table { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 0.78em; }
    .reveal .slides section pre { max-width: 100%; white-space: pre-wrap; word-break: break-word; font-size: 0.76em; }
    .reveal .slides section a { color: ${theme.headingColor}; }
    .reveal .slides section button {
      background: ${theme.headingColor};
      color: ${theme.bg};
      border: none;
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 0.8em;
      margin: 4px;
    }
    .reveal .slides section button:hover { opacity: 0.9; }
    .reveal .slides section .tag {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 0.7em;
      margin: 2px;
    }
    .reveal .slides section .card {
      background: rgba(255,255,255,0.1);
      border-radius: 8px;
      padding: 12px;
      margin: 6px 0;
    }
    .reveal .slides section .stats-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 20px;
      margin: 15px 0;
      width: 100%;
    }
    .reveal .slides section .stat-item {
      text-align: center;
      padding: 15px;
    }
    .reveal .slides section .stat-number {
      font-size: 2.5em;
      font-weight: bold;
      color: ${theme.headingColor};
    }
    .reveal .controls { display: none !important; }
    .reveal .progress { display: none !important; }
    .reveal .slide-number { display: none !important; }
    ${theme.slideCSS}
  </style>
</head>
<body>
  <div class="reveal">
    <div class="slides">
      ${sections || '<section><h2>等待内容生成...</h2></section>'}
    </div>
  </div>
  <script src="${REVEAL_JS_BASE}/reveal.min.js"></script>
  <script>
    let revealReady = false;

    function ensureSlideContent(section) {
      const firstElement = section.firstElementChild;
      if (firstElement && firstElement.classList.contains('slide-content')) {
        return firstElement;
      }

      const wrapper = document.createElement('div');
      wrapper.className = 'slide-content';
      while (section.firstChild) {
        wrapper.appendChild(section.firstChild);
      }
      section.appendChild(wrapper);
      return wrapper;
    }

    function fitSection(section) {
      const content = ensureSlideContent(section);
      content.style.transform = 'scale(1)';

      const availableWidth = section.clientWidth;
      const availableHeight = section.clientHeight;
      const requiredWidth = Math.max(content.scrollWidth, availableWidth);
      const requiredHeight = Math.max(content.scrollHeight, availableHeight);
      const scale = Math.min(1, availableWidth / requiredWidth, availableHeight / requiredHeight);

      content.style.transform = 'scale(' + scale + ')';
    }

    function fitAllSlides() {
      document.querySelectorAll('.reveal .slides > section').forEach((section) => {
        fitSection(section);
      });
    }

    Reveal.initialize({
      hash: false,
      slideNumber: false,
      transition: 'none',
      width: 1280,
      height: 720,
      margin: 0,
      center: true,
      embedded: true,
      keyboard: true,
      autoSlide: 0,
      mouseWheel: false,
      touch: false,
      loop: false,
      rtl: false,
      navigationMode: 'linear',
      shuffle: false,
      fragments: false,
      fragmentInURL: false,
      help: false,
      showNotes: false,
      previewLinks: false,
    });

    // 监听初始化完成
    Reveal.on('ready', function() {
      fitAllSlides();
      revealReady = true;
      window.parent.postMessage({
        type: 'revealReady',
        total: Reveal.getTotalSlides(),
        current: Reveal.getIndices().h,
      }, '*');
    });

    // 翻页通知父窗口
    Reveal.on('slidechanged', function(event) {
      fitSection(event.currentSlide);
      window.parent.postMessage({
        type: 'slideChanged',
        current: event.indexh,
        total: Reveal.getTotalSlides(),
      }, '*');
    });

    // 接收父窗口指令
    window.addEventListener('message', function(event) {
      const data = event.data;
      if (!data || !data.type) return;

      if (data.type === 'goToSlide' && revealReady) {
        var indices = data.index || 0;
        Reveal.slide(indices, 0, 0);
        window.parent.postMessage({
          type: 'slideChanged',
          current: indices,
          total: Reveal.getTotalSlides(),
        }, '*');
      }
      if (data.type === 'refitSlides') {
        fitAllSlides();
      }
      if (data.type === 'getState' && revealReady) {
        window.parent.postMessage({
          type: 'slideState',
          current: Reveal.getIndices().h,
          total: Reveal.getTotalSlides(),
        }, '*');
      }
    });

    window.addEventListener('resize', fitAllSlides);
  </script>
</body>
</html>`;
}

function getChartPlanSummary(metadata?: SlideMetadata): string | null {
  if (!metadata?.chart_plan?.needed) {
    return null;
  }
  const fields = metadata.chart_plan.data_fields.join("、") || "待补字段";
  return `${metadata.chart_plan.chart_type || "chart"} · ${fields}`;
}

export function PreviewPanel() {
  const pptState = useChatStore((s) => s.pptState);
  const slides = useChatStore((s) => s.slides);
  const themeId = useChatStore((s) => s.themeId);
  const presentationTitle = useChatStore((s) => s.presentationTitle);
  const outline = useChatStore((s) => s.outline);
  const currentPage = useChatStore((s) => s.currentPage);
  const totalPages = useChatStore((s) => s.totalPages);
  const presentationId = useChatStore((s) => s.presentationId);
  const currentSlideIndex = useChatStore((s) => s.currentSlideIndex);
  const messages = useChatStore((s) => s.messages);

  const toast = useToast();
  const setCurrentSlideIndex = useChatStore((s) => s.setCurrentSlideIndex);

  // Sprint 3 状态
  const isEditing = useChatStore((s) => s.isEditing);
  const setIsEditing = useChatStore((s) => s.setIsEditing);
  const updateSlideHtml = useChatStore((s) => s.updateSlideHtml);
  const pushUndo = useChatStore((s) => s.pushUndo);
  const clearUndoRedo = useChatStore((s) => s.clearUndoRedo);
  const showVersionPanel = useChatStore((s) => s.showVersionPanel);
  const setShowVersionPanel = useChatStore((s) => s.setShowVersionPanel);
  const setPptState = useChatStore((s) => s.setPptState);
  const currentSlide = slides[currentSlideIndex];
  const currentSlideMetadata = currentSlide?.metadata;
  const generationStatusMessages = useMemo(
    () =>
      messages
        .filter((msg) => msg.type === "status")
        .map((msg) => msg.content.replace(/^✅\s*/, "").trim())
        .filter((text) =>
          [
            "已确认大纲，开始生成幻灯片",
            "正在渲染页面结构与版式",
            "页面渲染完成，正在写入工作台",
            "已写入工作台，正在推送预览页面",
            "幻灯片仍在生成中",
          ].some((keyword) => text.includes(keyword))
        )
        .slice(-4),
    [messages]
  );
  const plannedSlides = totalPages || outline.length || 0;
  const waitStageItems = [
    {
      label: "确认大纲",
      description: "锁定页面叙事与结论顺序，避免直接生成低质量初稿。",
      matched: generationStatusMessages.some((text) => text.includes("已确认大纲，开始生成幻灯片")),
    },
    {
      label: "渲染页面结构",
      description: "将已确认的大纲转为每一页的版式结构、卡片与图表占位。",
      matched: generationStatusMessages.some((text) => text.includes("正在渲染页面结构与版式")),
    },
    {
      label: "写入工作台",
      description: "持久化幻灯片与 canonical DeckSpec，确保后续预览和导出一致。",
      matched: generationStatusMessages.some((text) => text.includes("页面渲染完成，正在写入工作台")),
    },
    {
      label: "推送预览页面",
      description: "逐页推送到右侧预览区，首批页面就绪后会立即可见。",
      matched: generationStatusMessages.some((text) => text.includes("已写入工作台，正在推送预览页面")),
    },
  ];
  const activeWaitStage = Math.max(waitStageItems.findIndex((item) => item.matched), 0);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const fullscreenRef = useRef<HTMLDivElement>(null);
  const [iframeReady, setIframeReady] = useState(false);
  const [previewRevision, setPreviewRevision] = useState(0);
  const lastSyncedSlideRef = useRef(-1);

  // 构建 srcdoc HTML
  const srcdoc = useMemo(() => {
    if (slides.length === 0) return "";
    const slidesHtml = slides.map((s) => s.html);
    return buildRevealHTML(slidesHtml, themeId, presentationTitle || "演示文稿");
  }, [slides, themeId, presentationTitle]);

  useEffect(() => {
    if (!presentationId || slides.length === 0) return;
    setIframeReady(false);
    lastSyncedSlideRef.current = -1;
    setPreviewRevision((current) => current + 1);
  }, [presentationId, slides, themeId]);

  // 监听 iframe postMessage
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const data = event.data;
      if (!data || !data.type) return;

      if (data.type === "slideChanged") {
        setCurrentSlideIndex(data.current);
      }
      if (data.type === "revealReady") {
        setIframeReady(true);
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [setCurrentSlideIndex]);

  // 翻页控制
  const goToSlide = useCallback((index: number) => {
    iframeRef.current?.contentWindow?.postMessage(
      { type: "goToSlide", index },
      "*"
    );
  }, []);

  const goPrev = useCallback(() => {
    goToSlide(Math.max(0, currentSlideIndex - 1));
  }, [goToSlide, currentSlideIndex]);

  const goNext = useCallback(() => {
    goToSlide(Math.min(slides.length - 1, currentSlideIndex + 1));
  }, [goToSlide, currentSlideIndex, slides.length]);

  // 全屏切换
  const toggleFullscreen = useCallback(() => {
    if (!fullscreenRef.current) return;
    if (!document.fullscreenElement) {
      fullscreenRef.current.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
  }, []);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === fullscreenRef.current);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!iframeReady) return;
    iframeRef.current?.contentWindow?.postMessage({ type: "refitSlides" }, "*");
  }, [iframeReady, slides, currentSlideIndex, showVersionPanel, isFullscreen]);

  useEffect(() => {
    if (!iframeReady) return;
    if (lastSyncedSlideRef.current === currentSlideIndex) return;
    lastSyncedSlideRef.current = currentSlideIndex;
    goToSlide(currentSlideIndex);
  }, [currentSlideIndex, goToSlide, iframeReady]);

  // 用新标签页打开完整 HTML 预览
  const openInNewTab = useCallback(() => {
    if (!presentationId) return;
    window.open(`/api/presentations/${presentationId}/html`, "_blank");
  }, [presentationId]);

  // ── Sprint 3: 编辑相关回调 ──

  /** 进入编辑模式 */
  const enterEditMode = useCallback(() => {
    const slide = slides[currentSlideIndex];
    if (!slide) return;
    // 保存当前 HTML 到撤销栈
    pushUndo(slide.html);
    setIsEditing(true);
    setPptState("editing");
  }, [slides, currentSlideIndex, pushUndo, setIsEditing, setPptState]);

  /** WYSIWYG 保存回调 */
  const handleEditorSave = useCallback(
    async (sanitizedHtml: string) => {
      // 1. 更新本地 store
      updateSlideHtml(currentSlideIndex, sanitizedHtml);

      // 2. 通过 REST API 持久化到数据库
      const slide = slides[currentSlideIndex];
      if (slide?.id && presentationId) {
        try {
          await fetch(`/api/presentations/slides/${slide.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              html: sanitizedHtml,
              source: "wysiwyg",
            }),
          });
        } catch (err) {
          console.error("[PreviewPanel] 保存失败:", err);
        }
      }

      // 3. 退出编辑模式
      setIsEditing(false);
      clearUndoRedo();
      setPptState("completed");
    },
    [
      currentSlideIndex,
      slides,
      presentationId,
      updateSlideHtml,
      setIsEditing,
      clearUndoRedo,
      setPptState,
    ]
  );

  /** 取消编辑 */
  const handleEditorCancel = useCallback(() => {
    setIsEditing(false);
    clearUndoRedo();
    setPptState("completed");
  }, [setIsEditing, clearUndoRedo, setPptState]);

  // 空状态
  if (pptState === "idle" && slides.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="w-20 h-20 rounded-2xl bg-primary-50 flex items-center justify-center mx-auto mb-5">
            <span className="text-4xl">📊</span>
          </div>
          <p className="text-base font-medium text-gray-500 mb-2">等待生成 PPT</p>
          <p className="text-sm text-gray-400 mb-4">在左侧输入需求，AI 将自动生成演示文稿</p>
          <div className="flex items-center justify-center gap-4 text-xs text-gray-400">
            <span className="flex items-center gap-1">🎯 智能生成</span>
            <span className="flex items-center gap-1">✨ 实时预览</span>
            <span className="flex items-center gap-1">📝 在线编辑</span>
          </div>
        </div>
      </div>
    );
  }

  if ((pptState === "outline_ready" || pptState === "outline_pending") && slides.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto max-w-4xl rounded-[32px] border border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f8fbff_100%)] p-6 shadow-[0_32px_80px_-44px_rgba(15,23,42,0.45)] md:p-8">
          <div className="flex flex-col gap-3 border-b border-slate-100 pb-5 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.28em] text-sky-600">Outline Review</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-900">{presentationTitle || "待确认大纲"}</h2>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
                当前阶段只生成了页面级结构。你可以在左侧直接确认生成，或输入修改意见继续调整。
              </p>
            </div>
            <div className="rounded-2xl border border-sky-100 bg-sky-50 px-4 py-3 text-sm text-sky-700">
              {pptState === "outline_pending" ? "正在整理大纲..." : `共 ${outline.length} 页，等待确认后再渲染成品`}
            </div>
          </div>

          <div className="mt-6 grid gap-4 md:grid-cols-2">
            {outline.map((item, index) => (
              <div
                key={`${item.title}-${index}`}
                className="rounded-[24px] border border-slate-200 bg-white/90 p-5 shadow-sm"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex h-8 min-w-8 items-center justify-center rounded-full bg-slate-900 px-2 text-xs font-semibold text-white">
                      {index + 1}
                    </span>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500">
                      {item.type}
                    </span>
                    {item.metadata?.is_appendix ? (
                      <span className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-700">
                        附录
                      </span>
                    ) : (
                      <span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700">
                        主文
                      </span>
                    )}
                  </div>
                  {item.metadata?.evidence_sources && item.metadata.evidence_sources.length > 0 ? (
                    <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                      {item.metadata.evidence_sources.length} 个来源
                    </span>
                  ) : null}
                </div>
                <h3 className="mt-4 text-lg font-semibold text-slate-900">{item.title}</h3>
                {item.metadata?.core_conclusion ? (
                  <div className="mt-3 rounded-2xl border border-sky-100 bg-sky-50/80 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-sky-600">Core Conclusion</p>
                    <p className="mt-1 text-sm leading-6 text-slate-700">{item.metadata.core_conclusion}</p>
                  </div>
                ) : null}
                {item.metadata?.chart_plan?.needed ? (
                  <div className="mt-3 rounded-2xl border border-violet-100 bg-violet-50/70 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-violet-600">Chart Plan</p>
                    <p className="mt-1 text-sm text-slate-700">
                      {item.metadata.chart_plan.chart_type || "chart"}
                      {item.metadata.chart_plan.data_fields.length > 0
                        ? ` · ${item.metadata.chart_plan.data_fields.join("、")}`
                        : " · 待补字段"}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {item.metadata.chart_plan.insight || item.metadata.core_conclusion || "用于支撑本页结论"}
                    </p>
                  </div>
                ) : null}
                {item.bullets.length > 0 ? (
                  <ul className="mt-3 space-y-2 text-sm leading-6 text-slate-600">
                    {item.bullets.slice(0, 4).map((bullet, bulletIndex) => (
                      <li key={`${item.title}-${bulletIndex}`} className="flex gap-2">
                        <span className="mt-1.5 h-1.5 w-1.5 rounded-full bg-sky-500" />
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-3 text-sm leading-6 text-slate-500">该页已确定标题与版式，等待进一步渲染。</p>
                )}
                {item.metadata?.evidence_sources && item.metadata.evidence_sources.length > 0 ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {item.metadata.evidence_sources.slice(0, 3).map((source) => (
                      <span
                        key={`${item.title}-${source.material_id}`}
                        className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs text-slate-600"
                      >
                        {source.label}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (pptState === "generating" && slides.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-6 py-8">
        <div className="mx-auto grid max-w-6xl gap-6 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-[32px] border border-slate-200 bg-[linear-gradient(180deg,#ffffff_0%,#f5f9ff_100%)] p-6 shadow-[0_32px_90px_-48px_rgba(15,23,42,0.42)] md:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-5">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-sky-600">Generation Pipeline</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-900">{presentationTitle || "正在生成演示文稿"}</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
                  当前已进入正式渲染阶段。系统会先完成结构渲染，再写入工作台并逐页推送到右侧预览。
                </p>
              </div>
              <div className="rounded-[28px] border border-sky-100 bg-sky-50/80 px-5 py-4 text-right shadow-sm">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-sky-600">Slide Progress</p>
                <p className="mt-2 text-3xl font-semibold text-slate-900">{currentPage}<span className="text-lg text-slate-400">/{plannedSlides || "-"}</span></p>
                <p className="mt-1 text-xs text-slate-500">首批页面就绪后会立即显示缩略图和预览</p>
              </div>
            </div>

            <div className="mt-6 grid gap-4">
              {waitStageItems.map((item, index) => {
                const isDone = index < activeWaitStage;
                const isActive = index === activeWaitStage;
                return (
                  <div
                    key={item.label}
                    className={`rounded-[24px] border px-5 py-4 transition-all ${
                      isActive
                        ? "border-sky-200 bg-sky-50/90 shadow-[0_18px_40px_-28px_rgba(14,116,144,0.38)]"
                        : isDone
                        ? "border-emerald-200 bg-emerald-50/80"
                        : "border-slate-200 bg-white/80"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold ${
                        isActive
                          ? "bg-slate-900 text-white"
                          : isDone
                          ? "bg-emerald-600 text-white"
                          : "bg-slate-100 text-slate-500"
                      }`}>
                        {isDone ? "✓" : index + 1}
                      </div>
                      <div>
                        <p className="text-sm font-semibold text-slate-900">{item.label}</p>
                        <p className="mt-1 text-sm leading-6 text-slate-500">{item.description}</p>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="rounded-[32px] border border-slate-200 bg-white/92 p-6 shadow-[0_28px_70px_-44px_rgba(15,23,42,0.35)] md:p-8">
            <div className="flex items-center justify-center">
              <div className="relative h-40 w-40">
                <div className="absolute inset-0 rounded-full border-[10px] border-slate-200/80" />
                <div
                  className="absolute inset-0 rounded-full border-[10px] border-transparent border-t-sky-500 border-r-indigo-400 transition-transform duration-700"
                  style={{ transform: `rotate(${Math.max(18, (plannedSlides ? (currentPage / plannedSlides) * 300 : 90))}deg)` }}
                />
                <div className="absolute inset-5 rounded-full bg-[radial-gradient(circle_at_30%_30%,rgba(255,255,255,0.95),rgba(219,234,254,0.75))] shadow-inner" />
                <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Current</p>
                  <p className="mt-2 text-4xl font-semibold text-slate-900">{currentPage}</p>
                  <p className="mt-1 text-sm text-slate-400">of {plannedSlides || "-"} slides</p>
                </div>
              </div>
            </div>

            <div className="mt-8 rounded-[24px] border border-slate-200 bg-slate-50/75 p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-slate-500">Live Status</p>
              <div className="mt-4 space-y-3">
                {generationStatusMessages.length > 0 ? generationStatusMessages.map((message, index) => (
                  <div key={`${message}-${index}`} className="rounded-2xl bg-white px-4 py-3 text-sm leading-6 text-slate-600 shadow-sm">
                    {message}
                  </div>
                )) : (
                  <div className="rounded-2xl bg-white px-4 py-3 text-sm leading-6 text-slate-600 shadow-sm">
                    正在准备生成环境，请稍候...
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col relative w-full h-full">
      {/* 浮动控制面板：在预览右上角 */}
      {slides.length > 0 && (
        <div className="absolute top-4 right-4 z-50 flex items-center gap-2">
          {/* Sprint 3: 编辑按钮 */}
          {(pptState === "completed" || pptState === "editing") && !isEditing && (
            <button
              onClick={enterEditMode}
              className="text-[11px] px-3 py-1.5 bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all flex items-center gap-1 font-medium"
              title="编辑当前幻灯片"
            >
              ✏️ 编辑
            </button>
          )}
          {/* Sprint 3: 版本历史 */}
          {(pptState === "completed" || pptState === "editing") && (
            <button
              onClick={() => setShowVersionPanel(!showVersionPanel)}
              className={`text-[11px] px-3 py-1.5 rounded-xl transition-all border shadow-sm backdrop-blur-sm flex items-center gap-1 font-medium ${
                showVersionPanel
                  ? "bg-primary-50/90 text-primary-700 border-primary-200"
                  : "bg-white/80 hover:bg-white text-gray-700 border-gray-200/50"
              }`}
              title="版本历史"
            >
              📝 版本
            </button>
          )}
          {/* Sprint 3: 导出按钮 */}
          <div className="relative">
            <button
              onClick={() => setShowExport(!showExport)}
              disabled={!presentationId}
              className="text-[11px] px-3 py-1.5 bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
              title="导出演示文稿"
            >
              📥 导出
            </button>
            <ExportPanel
              visible={showExport}
              onClose={() => setShowExport(false)}
            />
          </div>
          <button
            onClick={openInNewTab}
            disabled={!presentationId}
            className="text-[11px] px-3 py-1.5 bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all disabled:opacity-40 flex items-center gap-1 font-medium"
            title="在新标签页中打开完整 HTML"
          >
            ↗ HTML
          </button>
          <button
            onClick={toggleFullscreen}
            className="text-[11px] px-3 py-1.5 bg-white/80 hover:bg-white backdrop-blur-sm border border-gray-200/50 shadow-sm text-gray-700 rounded-xl transition-all flex items-center gap-1 font-medium"
            title="全屏预览 (F11)"
          >
            {isFullscreen ? "退出全屏" : "全屏"}
          </button>
        </div>
      )}

      {/* 悬浮进度条：在页面顶部中间 */}
      {pptState === "generating" && totalPages > 0 && (
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-2 bg-white/80 backdrop-blur-md shadow-lg border border-primary-100 rounded-2xl">
          <div className="flex items-center gap-2">
            <span className="text-base animate-pulse">⚡</span>
            <span className="text-sm text-primary-700 font-semibold">生成幻灯片中 {currentPage}/{totalPages}</span>
          </div>
          <div className="w-24 h-1.5 bg-primary-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary-500 to-primary-400 rounded-full transition-all duration-500 animate-progress-stripe"
              style={{ width: `${(currentPage / totalPages) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* 主预览区 — 缩略图 + iframe/编辑器 + 版本面板 */}
      <div className="flex-1 flex overflow-hidden">
        {/* 缩略图导航 */}
        {slides.length > 0 && (
          <div className="w-44 border-r border-gray-100 bg-gray-50/50 overflow-y-auto p-3 space-y-2 flex-shrink-0 scrollbar-thin">
            <div className="text-[10px] text-gray-400 font-semibold px-2 mb-2 uppercase tracking-wider">幻灯片</div>
            {slides.map((slide, i) => (
              <button
                key={slide.index}
                onClick={() => {
                  if (!iframeReady) return;
                  goToSlide(i);
                }}
                disabled={!iframeReady}
                className={`w-full aspect-video rounded-lg overflow-hidden text-left transition-all relative group ${
                  currentSlideIndex === i
                    ? "border-2 border-primary-500 shadow-lg ring-2 ring-primary-200"
                    : "border-2 border-gray-200 hover:border-gray-300 hover:shadow-md"
                } ${!iframeReady ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
              >
                {/* 页码标签 */}
                <div className={`absolute top-1.5 left-1.5 z-10 px-1.5 py-0.5 rounded text-[9px] font-bold shadow-sm ${
                  currentSlideIndex === i
                    ? "bg-primary-500 text-white"
                    : "bg-black/50 text-white backdrop-blur-sm"
                }`}>
                  {i + 1}
                </div>
                {slide.metadata?.is_appendix && (
                  <div className="absolute top-1.5 right-1.5 z-10 rounded bg-amber-400/90 px-1.5 py-0.5 text-[9px] font-bold text-amber-950 shadow-sm">
                    附录
                  </div>
                )}
                <div
                  className="w-full h-full p-1.5 overflow-hidden flex flex-col justify-center"
                  style={{
                    fontSize: "5px",
                    lineHeight: "1.3",
                    backgroundColor:
                      themeId === "tech_dark"
                        ? "#0f172a"
                        : themeId === "academic"
                        ? "#fefce8"
                        : "#ffffff",
                    color:
                      themeId === "tech_dark" ? "#e2e8f0" : "#1e293b",
                  }}
                >
                  <div className="font-bold truncate leading-tight" style={{ fontSize: "6px" }}>
                    {slide.html.replace(/<[^>]+>/g, "").substring(0, 20) || "空内容"}
                  </div>
                </div>
                {/* 当前页指示器 - 底部高亮条 */}
                {currentSlideIndex === i && iframeReady && (
                  <div className="absolute bottom-0 left-0 right-0 h-1 bg-primary-500 rounded-b-lg" />
                )}
                {/* 悬停遮罩 */}
                <div className={`absolute inset-0 bg-primary-500/10 opacity-0 group-hover:opacity-100 transition-opacity rounded-lg ${currentSlideIndex === i ? 'opacity-100' : ''}`} />
              </button>
            ))}
          </div>
        )}

        {/* 中央区域 — 预览模式 */}
        <div className="flex-1 flex flex-col overflow-hidden">
            <div
              ref={fullscreenRef}
              className="flex-1 relative flex items-center justify-center overflow-hidden bg-transparent"
            >
              {srcdoc ? (
                <>
                  {/* 幻灯片容器 - 充满父容器 */}
                  <div className="w-full h-full relative">
                    <iframe
                      key={`ppt-preview-${previewRevision}`}
                      ref={iframeRef}
                      srcDoc={srcdoc}
                      className="w-full h-full border-0"
                      sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
                      title="PPT 预览"
                      onLoad={() => {
                        setIframeReady(false);
                      }}
                    />
                  </div>

                  {/* 翻页按钮 - 位于幻灯片容器左右两侧，清晰可见 */}
                  {slides.length > 1 && (
                    <>
                      <button
                        onClick={goPrev}
                        disabled={currentSlideIndex === 0 || !iframeReady}
                        className="absolute left-4 md:left-8 top-1/2 -translate-y-1/2 w-12 h-12 md:w-14 md:h-14 rounded-full bg-white/90 backdrop-blur-sm border border-gray-200 text-slate-700 hover:bg-white disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-3xl transition-all z-10 shadow-lg hover:scale-105"
                        title="上一页 (←)"
                      >
                        ‹
                      </button>
                      <button
                        onClick={goNext}
                        disabled={currentSlideIndex >= slides.length - 1 || !iframeReady}
                        className="absolute right-4 md:right-8 top-1/2 -translate-y-1/2 w-12 h-12 md:w-14 md:h-14 rounded-full bg-white/90 backdrop-blur-sm border border-gray-200 text-slate-700 hover:bg-white disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center text-3xl transition-all z-10 shadow-lg hover:scale-105"
                        title="下一页 (→)"
                      >
                        ›
                      </button>
                    </>
                  )}
                </>
              ) : (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center">
                    {/* 加载动画 - 更精致的3D旋转效果 */}
                    <div className="relative w-20 h-20 mx-auto mb-6">
                      <div className="absolute inset-0 border-4 border-gray-700 rounded-full" />
                      <div className="absolute inset-2 border-4 border-blue-500 rounded-full border-t-transparent animate-spin shadow-lg shadow-blue-500/20" />
                      <div className="absolute inset-4 bg-gradient-to-br from-blue-500/10 to-purple-500/10 rounded-full" />
                    </div>
                    <p className="text-base font-medium text-gray-300 mb-2">正在生成幻灯片</p>
                    <p className="text-sm text-gray-500">AI 正在设计中，请稍候...</p>
                    {/* 进度指示器 */}
                    <div className="flex items-center justify-center gap-1.5 mt-4">
                      <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{animationDelay: '0ms'}} />
                      <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{animationDelay: '150ms'}} />
                      <span className="w-2 h-2 bg-blue-500 rounded-full animate-bounce" style={{animationDelay: '300ms'}} />
                    </div>
                  </div>
                </div>
              )}
            </div>

            {currentSlideMetadata && (
              <div className="border-t border-slate-200 bg-white/95 px-4 py-4 md:px-5">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                    currentSlideMetadata.is_appendix
                      ? "border border-amber-200 bg-amber-50 text-amber-700"
                      : "border border-emerald-200 bg-emerald-50 text-emerald-700"
                  }`}>
                    {currentSlideMetadata.is_appendix ? "附录页" : "主文页"}
                  </span>
                  {getChartPlanSummary(currentSlideMetadata) ? (
                    <span className="rounded-full border border-violet-200 bg-violet-50 px-3 py-1 text-xs font-medium text-violet-700">
                      图表规划：{getChartPlanSummary(currentSlideMetadata)}
                    </span>
                  ) : null}
                  {currentSlideMetadata.evidence_sources && currentSlideMetadata.evidence_sources.length > 0 ? (
                    <span className="rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-xs font-medium text-sky-700">
                      {currentSlideMetadata.evidence_sources.length} 个可追溯来源
                    </span>
                  ) : null}
                </div>

                {currentSlideMetadata.core_conclusion ? (
                  <div className="mt-3 rounded-2xl border border-slate-200 bg-slate-50/80 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Core Conclusion</p>
                    <p className="mt-1 text-sm leading-6 text-slate-700">{currentSlideMetadata.core_conclusion}</p>
                  </div>
                ) : null}

                {currentSlideMetadata.chart_plan?.needed ? (
                  <div className="mt-3 rounded-2xl border border-violet-100 bg-violet-50/70 px-4 py-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-violet-600">Chart Requirements</p>
                    <p className="mt-1 text-sm text-slate-700">
                      {currentSlideMetadata.chart_plan.chart_type || "chart"}
                      {currentSlideMetadata.chart_plan.data_fields.length > 0
                        ? ` · ${currentSlideMetadata.chart_plan.data_fields.join("、")}`
                        : " · 待补字段"}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">
                      {currentSlideMetadata.chart_plan.insight || currentSlideMetadata.core_conclusion}
                    </p>
                  </div>
                ) : null}

                {currentSlideMetadata.evidence_sources && currentSlideMetadata.evidence_sources.length > 0 ? (
                  <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {currentSlideMetadata.evidence_sources.map((source) => (
                      <div key={source.material_id} className="rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm">
                        <div className="flex items-center justify-between gap-3">
                          <p className="text-sm font-medium text-slate-800">{source.label}</p>
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] text-slate-500">
                            {source.source_type}
                          </span>
                        </div>
                        {source.excerpt ? (
                          <p className="mt-2 text-xs leading-5 text-slate-500">{source.excerpt}</p>
                        ) : null}
                        {source.url ? (
                          <a
                            href={source.url}
                            target="_blank"
                            rel="noreferrer"
                            className="mt-2 inline-flex text-xs font-medium text-sky-600 hover:text-sky-700 hover:underline"
                          >
                            查看来源
                          </a>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            )}
        </div>
      </div>
    </div>
  );
}
