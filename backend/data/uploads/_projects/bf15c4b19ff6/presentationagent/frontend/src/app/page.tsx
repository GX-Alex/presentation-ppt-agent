"use client";

import { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useChatStore } from "@/stores/chatStore";
import { Paperclip, Send, Sparkles, Wifi, WifiOff } from "lucide-react";

/** 快捷入口按钮 */
const quickActions = [
  { label: "AI PPT", icon: "📊", prompt: "帮我生成一个PPT" },
  { label: "调研报告", icon: "📋", prompt: "帮我做一个调研报告" },
  { label: "深度研究", icon: "🔍", prompt: "帮我深度研究一个主题" },
  { label: "网页搜索", icon: "🌐", prompt: "帮我搜索" },
];

/** AI 能力列表 */
const aiCapabilities = [
  { label: "📊 AI PPT 生成", prompt: "帮我生成一个PPT，主题是：" },
  { label: "📋 调研报告", prompt: "帮我做一个调研报告，关于：" },
  { label: "🔍 深度研究", prompt: "帮我深度研究一个主题：" },
  { label: "🌐 网页搜索", prompt: "帮我搜索：" },
  { label: "💻 代码分析", prompt: "帮我分析以下代码：" },
  { label: "📝 文案撰写", prompt: "帮我撰写一篇文案：" },
];

export default function HomePage() {
  const router = useRouter();
  const { sendChat } = useWebSocket();
  const connectionStatus = useChatStore((s) => s.connectionStatus);
  const [input, setInput] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [showCapabilities, setShowCapabilities] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const isConnected = connectionStatus === "connected";
  const isConnecting = connectionStatus === "connecting";

  /** 发送消息并跳转到聊天页 */
  const handleSend = useCallback(() => {
    const trimmed = input.trim();
    if (!trimmed || !isConnected) return;
    sendChat(trimmed, "new");
    setInput("");
    // 延迟跳转，等待 task_info 消息返回 task_id
    setTimeout(() => {
      const currentTaskId = useChatStore.getState().taskId;
      router.push(`/chat/${currentTaskId || "new"}`);
    }, 300);
  }, [input, isConnected, sendChat, router]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  /** 快捷入口点击 */
  const handleQuickAction = useCallback(
    (prompt: string) => {
      setInput(prompt);
      textareaRef.current?.focus();
    },
    []
  );

  /** 自动调整 textarea 高度 */
  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      const el = e.target;
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 200) + "px";
    },
    []
  );

  /** 上传附件：先跳转到聊天页再操作 */
  const handleUploadClick = useCallback(() => {
    // 清空 store 并跳转到新对话页（在对话页可使用完整的 FileUpload 组件）
    const store = useChatStore.getState();
    store.clearMessages();
    store.resetPpt();
    store.clearExecutionSteps();
    useChatStore.setState({ taskId: null, intent: null });
    router.push("/chat/new");
  }, [router]);

  /** 选择 AI 能力 */
  const handleCapabilitySelect = useCallback(
    (prompt: string) => {
      setInput(prompt);
      setShowCapabilities(false);
      textareaRef.current?.focus();
    },
    []
  );

  return (
    <div className="flex flex-col items-center justify-center h-full px-4 relative">
      {/* Zen 留白标题区 */}
      <div className="text-center mb-10">
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-3 tracking-tight">
          General Agent
        </h1>
        <p className="text-gray-400 text-base">AI 驱动的智能工作平台 — PPT · 文档 · 研究</p>
      </div>

      {/* 后端未连接警告 */}
      {!isConnected && (
        <div className="w-full max-w-2xl mb-6 px-4 py-3 bg-yellow-50 border border-yellow-200 rounded-xl">
          <div className="flex items-center gap-3">
            <div className="flex-shrink-0">
              <span className="w-2.5 h-2.5 rounded-full bg-yellow-500 animate-pulse block" />
            </div>
            <div className="flex-1">
              <p className="text-sm font-medium text-yellow-800">
                {isConnecting ? "正在连接后端服务..." : "无法连接到后端服务"}
              </p>
              <p className="text-xs text-yellow-600 mt-0.5">
                {isConnecting
                  ? "请稍候..."
                  : "请确保后端服务已启动 (运行 ./start.sh 或 ./dev.sh)"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 悬浮毛玻璃输入框区域 */}
      <div className="w-full max-w-2xl">
        <div className="glass-float rounded-2xl overflow-hidden transition-shadow hover:shadow-lg">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onFocus={() => setExpanded(true)}
            placeholder="描述你的需求，让 AI 帮你完成..."
            rows={expanded ? 4 : 2}
            className="w-full px-5 pt-4 pb-14 bg-transparent resize-none text-sm leading-relaxed
              focus:outline-none placeholder:text-gray-400 transition-all"
          />
          {/* 底部工具栏 */}
          <div className="absolute bottom-3 left-4 right-4 flex items-center justify-between">
            <div className="flex items-center gap-2 relative">
              <button
                onClick={handleUploadClick}
                className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-black/5 transition-colors"
                title="上传附件"
              >
                <Paperclip className="w-4 h-4" />
              </button>
              <button
                onClick={() => setShowCapabilities(!showCapabilities)}
                className={`p-2 rounded-lg transition-colors ${
                  showCapabilities
                    ? "text-primary-600 bg-primary-50"
                    : "text-gray-400 hover:text-gray-600 hover:bg-black/5"
                }`}
                title="AI 能力"
              >
                <Sparkles className="w-4 h-4" />
              </button>
              {/* AI 能力下拉菜单 */}
              {showCapabilities && (
                <div className="absolute bottom-full left-0 mb-2 w-56 bento-card shadow-lg py-1 z-10">
                  <div className="px-3 py-1.5 text-[11px] text-gray-400 font-semibold uppercase tracking-wider">AI 能力</div>
                  {aiCapabilities.map((cap) => (
                    <button
                      key={cap.label}
                      onClick={() => handleCapabilitySelect(cap.prompt)}
                      className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors rounded-lg mx-0"
                    >
                      {cap.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              {/* 连接状态指示器 */}
              <div className="flex items-center gap-1.5">
                {isConnected ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-green-500" />
                    <Wifi className="w-3 h-3 text-green-500" />
                  </>
                ) : isConnecting ? (
                  <>
                    <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
                    <span className="text-[10px] text-yellow-600">连接中...</span>
                  </>
                ) : (
                  <>
                    <span className="w-2 h-2 rounded-full bg-red-500" />
                    <WifiOff className="w-3 h-3 text-red-500" />
                  </>
                )}
              </div>
              <span className="text-[11px] text-gray-400 font-medium">MiniMax-M2.5</span>
              <button
                onClick={handleSend}
                disabled={!input.trim() || !isConnected}
                className="p-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700
                  disabled:opacity-30 disabled:cursor-not-allowed transition-all active:scale-95 shadow-sm"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        {/* 快捷入口胶囊按钮 */}
        <div className="flex flex-wrap justify-center gap-2.5 mt-8">
          {quickActions.map((action) => (
            <button
              key={action.label}
              onClick={() => handleQuickAction(action.prompt)}
              className="flex items-center gap-1.5 px-4 py-2 bg-white border border-gray-200/80 rounded-full
                text-sm text-gray-600 hover:bg-gray-50 hover:border-gray-300 hover:shadow-sm transition-all"
            >
              <span>{action.icon}</span>
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
