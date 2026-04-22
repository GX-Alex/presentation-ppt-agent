"use client";

/**
 * Chat 页面 — 主工作区，包含 ChatPanel（对话面板）+ WorkspacePanel（预览面板）。
 * 路由: /chat/[id]  (id 可以是 "new" 表示新任务)
 * 预览面板支持展开/折叠，主聊天区域自动填充。
 * 移动端: 默认隐藏预览，通过浮动按钮以 overlay 模式查看。
 */
import { use, useState, useCallback, useRef, useEffect } from "react";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { WorkspacePanel } from "@/components/workspace/WorkspacePanel";
import { PanelRightClose, PanelRightOpen, X } from "lucide-react";

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

export default function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const isMobile = useIsMobile();
  const [previewOpen, setPreviewOpen] = useState(false); // 默认关闭，等确认是否桌面端后再打开
  const [chatWidth, setChatWidth] = useState(400);
  const isDragging = useRef(false);

  // 桌面端默认打开预览
  useEffect(() => {
    if (!isMobile) setPreviewOpen(true);
  }, [isMobile]);

  const togglePreview = useCallback(() => setPreviewOpen((v) => !v), []);

  const containerRef = useRef<HTMLDivElement>(null);

  // 拖拽逻辑 — 同时支持 mouse 和 touch
  useEffect(() => {
    const handleMove = (clientX: number) => {
      if (!isDragging.current || !containerRef.current) return;
      const containerLeft = containerRef.current.getBoundingClientRect().left;
      const newWidth = Math.min(Math.max(clientX - containerLeft, 300), window.innerWidth * 0.6);
      setChatWidth(newWidth);
    };

    const handleMouseMove = (e: MouseEvent) => handleMove(e.clientX);
    const handleTouchMove = (e: TouchEvent) => {
      if (e.touches.length === 1) handleMove(e.touches[0].clientX);
    };

    const handleEnd = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = "default";
        document.body.style.userSelect = "auto";
      }
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleEnd);
    document.addEventListener("touchmove", handleTouchMove, { passive: true });
    document.addEventListener("touchend", handleEnd);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleEnd);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchend", handleEnd);
    };
  }, []);

  const startDrag = useCallback((e: React.MouseEvent | React.TouchEvent) => {
    e.preventDefault();
    isDragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  // 移动端: overlay 模式的预览面板
  if (isMobile) {
    return (
      <div className="flex flex-col h-full relative">
        <div className="flex-1 flex flex-col overflow-hidden">
          <ChatPanel taskId={id} />
        </div>

        {/* 浮动按钮 — 打开工作区预览 */}
        {!previewOpen && (
          <button
            onClick={togglePreview}
            className="fixed bottom-20 right-4 z-30 p-3 bg-primary-600 text-white rounded-full shadow-lg hover:bg-primary-700 active:scale-95 transition-all"
            title="查看工作区"
          >
            <PanelRightOpen className="w-5 h-5" />
          </button>
        )}

        {/* 移动端 overlay 预览 */}
        {previewOpen && (
          <>
            <div
              className="fixed inset-0 z-40 bg-black/30 backdrop-blur-sm"
              onClick={togglePreview}
            />
            <div className="fixed inset-y-0 right-0 z-50 w-full max-w-[90vw] bg-white shadow-2xl flex flex-col animate-slideInRight">
              <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                <span className="text-sm font-semibold text-gray-700">工作区</span>
                <button
                  onClick={togglePreview}
                  className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="flex-1 overflow-auto">
                <WorkspacePanel />
              </div>
            </div>
          </>
        )}
      </div>
    );
  }

  // 桌面端: 原有双面板布局
  return (
    <div ref={containerRef} className="flex h-full gap-0 p-[var(--bento-gap)] relative">
      {/* 对话面板 */}
      <div
        className="flex flex-col transition-[width] duration-0 overflow-hidden"
        style={{
          width: previewOpen ? `${chatWidth}px` : "100%",
          minWidth: previewOpen ? "300px" : "100%",
        }}
      >
        <ChatPanel taskId={id} />
      </div>

      {/* 拖拽分割线 */}
      {previewOpen && (
        <div
          className="w-4 flex-shrink-0 cursor-col-resize flex items-center justify-center group z-10 mx-1 touch-none"
          onMouseDown={startDrag}
          onTouchStart={startDrag}
        >
          <div className="h-12 w-1 rounded-full bg-gray-300 group-hover:bg-primary-500 transition-colors" />
        </div>
      )}

      {/* 预览面板展开/折叠按钮 */}
      <button
        onClick={togglePreview}
        className="absolute top-5 right-5 z-20 p-2 bg-white/50 backdrop-blur-sm border border-gray-200/50 rounded-xl hover:shadow-sm transition-all text-gray-500 hover:text-gray-700"
        title={previewOpen ? "关闭预览" : "展开预览"}
      >
        {previewOpen ? (
          <PanelRightClose className="w-5 h-5" />
        ) : (
          <PanelRightOpen className="w-5 h-5" />
        )}
      </button>

      {/* 预览面板 */}
      <div
        className={`flex flex-col transition-all duration-300 overflow-hidden ${
          previewOpen ? "flex-1" : "w-0 opacity-0"
        }`}
      >
        {previewOpen && <WorkspacePanel />}
      </div>
    </div>
  );
}
