/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * MessageList 组件 — 渲染对话消息列表。
 * 支持类型: text(文字) / thinking(思考) / status(状态) / error(错误) / outline(大纲) / tool_calls(工具调用)
 * 自动滚动到底部。
 */
"use client";

import { useEffect, useRef, useState, useCallback, type ReactNode } from "react";
import { useChatStore, type ChatMessage } from "@/stores/chatStore";
import { useDeckStore } from "@/stores/deckStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import { ChevronDown, ChevronRight, Copy, Check, ArrowDown, Paperclip, ExternalLink, Loader2, CheckCircle2, Brain, Wrench, Info, FileText, Layout, Code2, Eye } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ExecutionTimeline from "./ExecutionTimeline";

const REASONING_TYPES = new Set(["thinking", "tool_calls", "status"]);

// ────── Fix 1: 附件解析 ──────

interface ParsedAttachment {
  filename: string;
  assetId: string;
  url: string;
}

/** 从消息内容中提取 [附件: ...] 标记 */
function parseAttachments(content: string): { cleanContent: string; attachments: ParsedAttachment[] } {
  const attachments: ParsedAttachment[] = [];
  const regex = /\[附件: (.+?) \(Asset ID: (.+?), URL: (.+?)\)\]/g;
  let match;
  while ((match = regex.exec(content)) !== null) {
    attachments.push({
      filename: match[1],
      assetId: match[2],
      url: match[3],
    });
  }
  const cleanContent = content.replace(regex, "").replace(/\n{3,}/g, "\n\n").trim();
  return { cleanContent, attachments };
}

/** 附件芯片列表 */
function AttachmentChips({ attachments }: { attachments: ParsedAttachment[] }) {
  if (attachments.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-white/20">
      {attachments.map((att) => (
        <a
          key={att.assetId}
          href={att.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/15 hover:bg-white/25 rounded-lg text-xs transition-colors"
          title={att.filename}
        >
          <Paperclip className="w-3 h-3 flex-shrink-0" />
          <span className="truncate max-w-[180px]">{att.filename}</span>
          <ExternalLink className="w-2.5 h-2.5 flex-shrink-0 opacity-60" />
        </a>
      ))}
    </div>
  );
}

// ────── Fix 5: 生成产物标识芯片 ──────

/** 产物类型映射 */
const ARTIFACT_TYPE_META: Record<string, { icon: typeof FileText; label: string; color: string }> = {
  drawio: { icon: Layout, label: "流程图", color: "text-blue-600 bg-blue-50 border-blue-200" },
  document: { icon: FileText, label: "文档", color: "text-emerald-600 bg-emerald-50 border-emerald-200" },
  webpage: { icon: Layout, label: "网页原型", color: "text-purple-600 bg-purple-50 border-purple-200" },
  code: { icon: Code2, label: "代码产物", color: "text-amber-600 bg-amber-50 border-amber-200" },
};

/** 从 assistant 消息内容中检测生成产物占位符，返回产物类型列表 */
function detectGeneratedArtifacts(content: string): string[] {
  const artifacts: string[] = [];
  // 检测"智能工作区已更新"占位符（可能出现多次）
  const placeholderCount = (content.match(/✨\s*\*智能工作区已更新/g) || []).length;
  if (placeholderCount > 0) {
    // 从内容中推断产物类型（基于关键词启发式判断）
    if (content.includes("draw.io") || content.includes("drawio") || content.includes("流程图") || content.includes("diagram")) {
      artifacts.push("drawio");
    }
    if (content.includes("网页") || content.includes("HTML") || content.includes("prototype") || content.includes("html")) {
      artifacts.push("webpage");
    }
    if ((content.includes("文档") || content.includes("markdown")) && !content.includes("流程图")) {
      artifacts.push("document");
    }
    if (content.includes("代码") || content.includes("code")) {
      artifacts.push("code");
    }
    // 如果没有匹配到具体类型，默认为 document
    if (artifacts.length === 0) {
      artifacts.push("document");
    }
  }
  return artifacts;
}

/** 生成产物芯片列表 — 点击可在工作区查看 */
function GeneratedArtifactChips({ content, artifactType }: { content: string; artifactType?: string }) {
  const setCurrentArtifactType = useChatStore((s) => s.setCurrentArtifactType);
  // 优先使用存储的 artifactType（来自 WS 事件），否则回退到关键词检测
  const artifacts = artifactType ? [artifactType] : detectGeneratedArtifacts(content);
  if (artifacts.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-gray-100">
      {artifacts.map((type) => {
        const meta = ARTIFACT_TYPE_META[type] || ARTIFACT_TYPE_META.document;
        const Icon = meta.icon;
        return (
          <button
            key={type}
            onClick={() => setCurrentArtifactType(type as import("@/stores/chatStore").ArtifactType)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-lg text-xs font-medium transition-all hover:shadow-sm active:scale-95 ${meta.color}`}
            title={`在工作区查看${meta.label}`}
          >
            <Icon className="w-3.5 h-3.5 flex-shrink-0" />
            <span>{meta.label}</span>
            <Eye className="w-3 h-3 flex-shrink-0 opacity-60" />
          </button>
        );
      })}
    </div>
  );
}

// ────── Fix 5: 系统路径清理 ──────

// ────── Fix 3: 清理 LLM <think> 标签 ──────

/** 移除 LLM 推理标签 <think>...</think>，防止泄漏到消息显示 */
function stripThinkTags(content: string): string {
  return content.replace(/<think>[\s\S]*?<\/think>\s*/gi, "").trim();
}

// ────── Fix 5/6: 系统路径清理（代码块感知） ──────

/** 清理消息中的系统文件路径，替换为文件名。跳过 markdown 代码块内的路径。 */
function cleanSystemPaths(content: string): string {
  // 先将代码块提取出来保护，替换后再放回
  const codeBlocks: string[] = [];
  const placeholder = "___CODE_BLOCK_PLACEHOLDER___";
  // 保护 fenced code blocks (```...```)
  let protected_ = content.replace(/```[\s\S]*?```/g, (match) => {
    codeBlocks.push(match);
    return `${placeholder}${codeBlocks.length - 1}`;
  });
  // 保护 inline code (`...`)
  protected_ = protected_.replace(/`[^`]+`/g, (match) => {
    codeBlocks.push(match);
    return `${placeholder}${codeBlocks.length - 1}`;
  });

  // 在非代码区域清理路径
  protected_ = protected_
    .replace(/(?<![:/])\/(?:Users|home|data|tmp|var|opt|srv|workspace|app|root)\/[^\s"')<\]]+/g, (match) => {
      const filename = match.split("/").pop() || match;
      return filename;
    })
    .replace(/(?:[A-Z]:\\(?:Users|Program Files)[^\s"')<\]]+)/gi, (match) => {
      const filename = match.split("\\").pop() || match;
      return filename;
    });

  // 恢复代码块
  for (let i = 0; i < codeBlocks.length; i++) {
    protected_ = protected_.replace(`${placeholder}${i}`, codeBlocks[i]);
  }
  return protected_;
}
const HIDDEN_MESSAGE_TYPES = new Set(["workspace_sync"]);

function isReasoningMessage(msg: ChatMessage): boolean {
  return !!msg.type && REASONING_TYPES.has(msg.type);
}

function formatToolCallSummary(content: string): string[] {
  try {
    const parsed = JSON.parse(content);
    if (parsed.tool_calls && Array.isArray(parsed.tool_calls) && parsed.tool_calls.length > 0) {
      return parsed.tool_calls.map((toolCall: { name?: string }) => {
        const toolName = toolCall.name || "unknown";
        return `正在执行工具: ${toolName}...`;
      });
    }
  } catch {
    return [content];
  }

  return [content];
}

function getReasoningLines(msg: ChatMessage): string[] {
  if (msg.type === "tool_calls") {
    return formatToolCallSummary(msg.content);
  }
  return [msg.content];
}

function getReasoningLabel(msg: ChatMessage): string {
  if (msg.type === "thinking") return "THINKING";
  if (msg.type === "tool_calls") return "TOOL";
  return "STATUS";
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={handleCopy} className="flex items-center gap-1 hover:text-white transition-colors" title="复制代码">
      {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
      <span>{copied ? "已复制" : "复制"}</span>
    </button>
  );
}

// ────── Fix 2.3: 可折叠代码块组件 ──────

const CODE_COLLAPSE_THRESHOLD = 15; // 超过此行数默认折叠

/** 可折叠的代码块 — 长代码默认折叠，点击展开 */
function CollapsibleCodeBlock({ className, children, ...props }: { className?: string; children: ReactNode; [key: string]: unknown }) {
  const text = String(children).replace(/\n$/, "");
  const lineCount = text.split("\n").length;
  const isLong = lineCount > CODE_COLLAPSE_THRESHOLD;
  const [expanded, setExpanded] = useState(!isLong); // 长代码默认折叠
  const match = /language-(\w+)/.exec(className || "");

  return (
    // not-prose: 防止 Tailwind Typography 覆盖代码块颜色 (Fix 1)
    <div className="relative my-4 rounded-xl bg-[#1e1e1e] overflow-hidden shadow-sm font-mono text-[13px] group not-prose">
      <div className="flex items-center justify-between px-4 py-2 bg-[#2d2d2d] text-gray-300 select-none">
        <span className="text-xs uppercase tracking-wider">{match?.[1] || "code"}</span>
        <div className="flex items-center gap-2.5">
          {isLong && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-white transition-colors"
            >
              {expanded ? (
                <><ChevronDown className="w-3 h-3" /> 折叠</>
              ) : (
                <><ChevronRight className="w-3 h-3" /> 展开 ({lineCount} 行)</>
              )}
            </button>
          )}
          <CopyButton text={text} />
        </div>
      </div>
      <div className={`overflow-x-auto transition-all duration-200 ${!expanded ? "max-h-[160px] overflow-y-hidden" : ""}`}>
        <div className="p-4">
          <code className={`${className || ""} !text-gray-100`} {...props}>
            {children}
          </code>
        </div>
        {!expanded && isLong && (
          <div className="h-8 bg-gradient-to-t from-[#1e1e1e] to-transparent pointer-events-none" />
        )}
      </div>
      {!expanded && isLong && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full py-1.5 text-[11px] text-gray-500 hover:text-gray-300 hover:bg-[#2a2a2a] transition-colors border-t border-[#333]"
        >
          展开完整代码 ({lineCount} 行)
        </button>
      )}
    </div>
  );
}

// ────── 共享 Markdown 渲染组件（用于消息和流式输出） ──────

const sharedMarkdownComponents: any = {
  code({ className, children, node, ...props }: any) {
    const text = String(children).replace(/\n$/, "");
    const isBlock = !!/language-(\w+)/.exec(className || "") || text.includes("\n");
    if (isBlock) {
      return <CollapsibleCodeBlock className={className} {...props}>{children}</CollapsibleCodeBlock>;
    }
    return (
      <code className="bg-black/5 text-pink-600 rounded px-1.5 py-0.5 text-[0.9em] font-mono break-words" {...props}>
        {children}
      </code>
    );
  },
  pre({ children }: any) {
    return <>{children}</>;
  },
  p({ children, node }: any) {
    const hasBlockChild = node?.children?.some(
      (child: any) =>
        child.tagName === "pre" || child.tagName === "div" || child.tagName === "code"
    );
    if (hasBlockChild) {
      return <div className="mb-3 last:mb-0 leading-relaxed">{children}</div>;
    }
    return <p className="mb-3 last:mb-0 leading-relaxed">{children}</p>;
  },
  ul({ children }: any) {
    return <ul className="list-disc pl-5 mb-3 last:mb-0 space-y-1">{children}</ul>;
  },
  ol({ children }: any) {
    return <ol className="list-decimal pl-5 mb-3 last:mb-0 space-y-1">{children}</ol>;
  },
  li({ children }: any) {
    return <li className="leading-relaxed">{children}</li>;
  },
  a({ href, children }: any) {
    return <a href={href} target="_blank" rel="noreferrer" className="text-primary-600 hover:underline break-all">{children}</a>;
  },
};

function ExpandableContent({ content, isUser }: { content: string, isUser: boolean }) {
  const [expanded, setExpanded] = useState(false);

  const isLong = content.length > 800 || content.split('\n').length > 15;
  const shouldCollapse = isLong && !expanded;

  return (
    <div className="relative">
      <div className={`${shouldCollapse ? 'max-h-[300px] overflow-hidden' : ''}`}>
        {isUser ? (
          <div className="whitespace-pre-wrap">{content}</div>
        ) : (
          <div className="prose prose-sm max-w-none break-words">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={sharedMarkdownComponents}>
              {content}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {shouldCollapse && (
        <div className={`absolute bottom-0 left-0 right-0 h-24 bg-gradient-to-t ${isUser ? "from-primary-600" : "from-white"} to-transparent flex items-end justify-center pb-1`}>
          <button
            onClick={() => setExpanded(true)}
            className={`flex items-center gap-1.5 px-4 py-1.5 border rounded-full text-xs font-medium shadow-sm transition-colors ${
              isUser
                ? "bg-primary-500 border-primary-400 text-white hover:bg-primary-400"
                : "bg-white border-gray-200 text-primary-600 hover:bg-gray-50"
            }`}
          >
            <ChevronDown className="w-3.5 h-3.5" />
            展开完整内容
          </button>
        </div>
      )}
      {isLong && expanded && (
        <div className="mt-3 flex justify-center">
          <button
            onClick={() => setExpanded(false)}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-gray-50 border border-gray-200 rounded-full text-xs font-medium text-gray-500 shadow-sm hover:bg-gray-100 transition-colors"
          >
            收起内容
          </button>
        </div>
      )}
    </div>
  );
}

/** 推理过程气泡 — 步骤卡片风格（参照 ExecutionTimeline） */
function ReasoningBubble({
  messages,
  defaultExpanded,
}: {
  messages: ChatMessage[];
  defaultExpanded: boolean;
}) {
  const [collapsed, setCollapsed] = useState(!defaultExpanded);

  const title = messages.some((msg) => msg.type === "tool_calls")
    ? "推理与工具执行"
    : "思考过程";

  const stepCount = messages.length;
  const hasRunning = defaultExpanded; // 如果是最新组且正在处理

  return (
    <div className="flex justify-start my-2">
      <div className="w-full max-w-[92%] md:max-w-[42rem] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        {/* 标题栏 */}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="w-full px-4 py-3 flex items-center gap-2.5 hover:bg-slate-50 transition-colors text-left border-b border-slate-100"
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
          )}
          {hasRunning ? (
            <Loader2 className="w-4 h-4 animate-spin text-blue-500 flex-shrink-0" />
          ) : (
            <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
          )}
          <span className="text-xs font-semibold text-slate-700">{title}</span>
          <span className="text-[10px] text-slate-400 ml-auto">{stepCount} 步</span>
        </button>

        {/* 步骤卡片列表 */}
        {!collapsed && (
          <div className="px-3 py-2.5 max-h-[400px] overflow-y-auto scrollbar-thin space-y-1.5">
            {messages.map((msg, idx) => {
              const isLast = idx === messages.length - 1;
              const isRunningStep = isLast && hasRunning;
              const label = getReasoningLabel(msg);
              const lines = getReasoningLines(msg);

              // 步骤类型样式
              let stepIcon: React.ReactNode;
              let stepBg: string;
              if (msg.type === "thinking") {
                stepIcon = isRunningStep
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                  : <Brain className="w-3.5 h-3.5 text-sky-600" />;
                stepBg = isRunningStep ? "bg-blue-50 border-blue-200" : "bg-sky-50 border-sky-200";
              } else if (msg.type === "tool_calls") {
                stepIcon = isRunningStep
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                  : <Wrench className="w-3.5 h-3.5 text-emerald-600" />;
                stepBg = isRunningStep ? "bg-blue-50 border-blue-200" : "bg-emerald-50 border-emerald-200";
              } else {
                stepIcon = isRunningStep
                  ? <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                  : <Info className="w-3.5 h-3.5 text-slate-500" />;
                stepBg = isRunningStep ? "bg-blue-50 border-blue-200" : "bg-slate-50 border-slate-200";
              }

              return (
                <div
                  key={msg.id}
                  className={`rounded-xl border px-3 py-2.5 ${stepBg} transition-colors`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    {stepIcon}
                    <span className="text-[10px] font-semibold tracking-wider text-slate-500 uppercase">
                      {label}
                    </span>
                    {isRunningStep && (
                      <span className="text-[10px] text-blue-500 ml-auto animate-pulse">进行中</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-600 leading-relaxed whitespace-pre-wrap">
                    {lines.map((line, i) => (
                      <div key={`${msg.id}-${i}`} className="truncate" title={line}>{line}</div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/** 大纲确认卡片 — 显示大纲内容 + 确认/修改操作 */
function OutlineConfirmCard({
  msg,
  showActions,
  onSend,
}: {
  msg: ChatMessage;
  showActions: boolean;
  onSend?: (content: string) => void;
}) {
  const [confirmText, setConfirmText] = useState("好的，确认，开始生成幻灯片");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const pptState = useChatStore((s) => s.pptState);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);
  const deckStatus = useDeckStore((s) => s.deckStatus);
  const projectId = useDeckStore((s) => s.projectId);
  const { sendWebDeckApprove } = useWebSocket();

  const isWebDeckPlanReady = currentArtifactType === "webdeck" && deckStatus === "plan_ready" && !!projectId;
  const isWebDeckGenerating = currentArtifactType === "webdeck" && deckStatus === "generating";
  const isWebDeckCompleted = currentArtifactType === "webdeck" && deckStatus === "completed";
  const disabled = isSubmitting || isProcessing || pptState === "generating";

  useEffect(() => {
    setConfirmText(isWebDeckPlanReady ? "好的，确认，开始生成 Web Deck" : "好的，确认，开始生成幻灯片");
  }, [isWebDeckPlanReady]);

  // P2-7: 当处理状态变化时重置提交中状态（不再依赖 setTimeout）
  useEffect(() => {
    if (isSubmitting && isProcessing) {
      // 后端已接收，等 isProcessing 变回 false 时重置
    }
    if (isSubmitting && !isProcessing) {
      setIsSubmitting(false);
    }
  }, [isProcessing, isSubmitting]);

  const handleConfirm = () => {
    if (disabled) return;
    setIsSubmitting(true);
    if (isWebDeckPlanReady && projectId) {
      sendWebDeckApprove(projectId);
    } else if (confirmText.trim() && onSend) {
      onSend(confirmText.trim());
    }
  };

  // 快捷操作按钮
  const quickActions = isWebDeckPlanReady
    ? [{ label: "确认生成", icon: "✅", text: "好的，确认，开始生成 Web Deck" }]
    : [
        { label: "确认生成", icon: "✅", text: "好的，确认，开始生成幻灯片" },
        { label: "减少页数", icon: "📄", text: "可以减少到3页吗？" },
        { label: "调整风格", icon: "🎨", text: "换个更活泼的风格" },
      ];

  return (
    <div className="flex justify-start my-3 animate-fadeIn">
      <div className="max-w-[90%] bento-card overflow-hidden border border-primary-100">
        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">📋</span>
            <span className="text-sm font-semibold text-primary-600">
              {isWebDeckPlanReady || isWebDeckGenerating || isWebDeckCompleted ? "Web Deck 规划预览" : "PPT 大纲预览"}
            </span>
            {(pptState === "generating" || isWebDeckGenerating) && (
              <span className="ml-auto text-xs text-primary-400 animate-pulse">正在生成...</span>
            )}
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed bg-gray-50 rounded-xl p-4">
            {msg.content}
          </div>
        </div>

        {showActions && (
          <div className="px-5 pb-5 pt-3 border-t border-gray-100">
            {isWebDeckPlanReady ? (
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs leading-5 text-gray-400">
                  确认后会进入 Web Deck Runtime，按页生成并推送目录、预览和 lane 状态；如需改结构，请使用右侧工作台中的“重新规划”。
                </p>
                <button
                  onClick={handleConfirm}
                  disabled={disabled}
                  className="shrink-0 px-4 py-2 bg-primary-600 text-white text-sm rounded-xl hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm active:scale-95"
                >
                  {isSubmitting ? (
                    <>
                      <span className="animate-spin">⏳</span>
                      <span>提交中...</span>
                    </>
                  ) : (
                    <>
                      <span>🚀</span>
                      <span>确认并开始生成</span>
                    </>
                  )}
                </button>
              </div>
            ) : (
              <>
                <div className="mb-3">
                  <p className="text-[11px] text-gray-400 mb-2 font-medium">快捷操作</p>
                  <div className="flex flex-wrap gap-2">
                    {quickActions.map((action, i) => (
                      <button
                        key={i}
                        onClick={() => {
                          setConfirmText(action.text);
                          if (onSend) {
                            setIsSubmitting(true);
                            onSend(action.text);
                          }
                        }}
                        disabled={disabled}
                        className="px-3 py-1.5 bg-white border border-gray-200 rounded-xl text-xs text-gray-600 hover:bg-primary-50 hover:border-primary-300 hover:text-primary-600 disabled:opacity-50 transition-all flex items-center gap-1"
                      >
                        <span>{action.icon}</span> {action.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleConfirm()}
                    placeholder="输入修改意见或直接发送..."
                    disabled={disabled}
                    className="flex-1 text-sm border border-gray-200 rounded-xl px-3 py-2 focus:outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100 transition-all disabled:bg-gray-50"
                  />
                  <button
                    onClick={handleConfirm}
                    disabled={!confirmText.trim() || disabled}
                    className="px-4 py-2 bg-primary-600 text-white text-sm rounded-xl hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center gap-2 shadow-sm active:scale-95"
                  >
                    {isSubmitting ? (
                      <>
                        <span className="animate-spin">⏳</span>
                        <span>发送中...</span>
                      </>
                    ) : (
                      <>
                        <span>🚀</span>
                        <span>开始生成</span>
                      </>
                    )}
                  </button>
                </div>
              </>
            )}
          </div>
        )}

        {isWebDeckCompleted && (
          <div className="px-5 py-3 bg-green-50 border-t border-green-100">
            <div className="flex items-center gap-2 text-green-600">
              <span className="text-lg">🎉</span>
              <span className="text-sm font-medium">Web Deck 生成完成！可以在右侧查看页面目录和逐页预览</span>
            </div>
          </div>
        )}

        {pptState === "completed" && !isWebDeckCompleted && (
          <div className="px-5 py-3 bg-green-50 border-t border-green-100">
            <div className="flex items-center gap-2 text-green-600">
              <span className="text-lg">🎉</span>
              <span className="text-sm font-medium">幻灯片生成完成！可以在右侧预览和编辑</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function QualityEntryCard({
  msg,
  onOpen,
}: {
  msg: ChatMessage;
  onOpen?: () => void;
}) {
  return (
    <div className="flex justify-start my-3 animate-fadeIn">
      <div className="max-w-[90%] bento-card overflow-hidden border border-sky-100">
        <div className="px-5 py-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">✨</span>
            <span className="text-sm font-semibold text-sky-600">高质量生成入口</span>
          </div>
          <div className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed bg-gray-50 rounded-xl p-4">
            {msg.content}
          </div>
        </div>
        <div className="px-5 pb-5 pt-3 border-t border-gray-100 flex items-center justify-between gap-3">
          <p className="text-xs leading-5 text-gray-400">先填写 Brief，再生成可确认的大纲；确认后才会真正出成品。</p>
          <button
            onClick={onOpen}
            className="rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            填写高质量 Brief
          </button>
        </div>
      </div>
    </div>
  );
}

/** 单条消息气泡 */
function MessageBubble({
  msg,
  isLatestOutline,
  onSend,
  onOpenQualityDialog,
  lastUserMessage,
}: {
  msg: ChatMessage;
  isLatestOutline?: boolean;
  onSend?: (content: string) => void;
  onOpenQualityDialog?: () => void;
  lastUserMessage?: string;
}) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  // 错误消息: 友好展示
  if (msg.type === "error") {
    // 解析错误类型
    const content = msg.content;
    let errorTitle = "操作失败";
    let errorDetail = content;
    let canRetry = false;

    if (content.includes("质量生成流程出错")) {
      errorTitle = "高质量生成失败";
      errorDetail = content.replace(/^❌\s*/, "");
      canRetry = true;
    } else if (content.includes("APIConnectionError") || content.includes("connection")) {
      errorTitle = "AI 服务连接失败";
      errorDetail = "请检查网络连接后重试";
      canRetry = true;
    } else if (content.includes("TimeoutError") || content.includes("超时")) {
      errorTitle = "AI 响应超时";
      errorDetail = "服务繁忙，请稍后重试";
      canRetry = true;
    } else if (content.includes("500") || content.includes("server_error")) {
      errorTitle = "AI 服务暂时不可用";
      errorDetail = "服务端异常，请稍后重试";
      canRetry = true;
    } else if (content.includes("429") || content.includes("rate_limit")) {
      errorTitle = "请求过于频繁";
      errorDetail = "请稍后再试";
      canRetry = true;
    } else if (content.includes("大纲生成失败")) {
      errorTitle = "PPT 大纲生成失败";
      errorDetail = content;
      canRetry = true;
    }

    return (
      <div className="flex justify-center my-2">
        <div className="max-w-[85%] bg-red-50/80 backdrop-blur rounded-xl border border-red-200/60 px-4 py-3 shadow-sm">
          <div className="flex items-start gap-2">
            <span className="text-red-400 text-base mt-0.5">⚠️</span>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-red-700">{errorTitle}</p>
              <p className="text-xs text-red-500/80 mt-0.5">{errorDetail}</p>
            </div>
            {canRetry && onSend && lastUserMessage && (
              <button
                onClick={() => onSend(lastUserMessage)}
                className="px-3 py-1.5 text-xs bg-white border border-red-200 hover:bg-red-100 text-red-600 rounded-lg transition-all shadow-sm active:scale-95"
              >
                重试
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // 大纲消息: 最新大纲显示确认卡片，历史大纲显示折叠摘要 (Sprint 2+)
  if (msg.type === "outline") {
    return (
      <OutlineConfirmCard
        msg={msg}
        showActions={!!isLatestOutline}
        onSend={onSend}
      />
    );
  }

  if (msg.type === "quality_entry") {
    return <QualityEntryCard msg={msg} onOpen={onOpenQualityDialog} />;
  }

  // 用户消息 / 助手消息 - 带入场动画
  // Fix 1: 解析附件标记; Fix 5: 清理系统路径
  const { cleanContent, attachments } = isUser
    ? parseAttachments(msg.content)
    : { cleanContent: msg.content, attachments: [] };
  const displayContent = isUser ? cleanContent : cleanSystemPaths(stripThinkTags(msg.content));

  return (
    <div
      className={`flex my-3 ${isUser ? "justify-end" : "justify-start"} animate-fadeIn`}
      style={{ animationDuration: "0.3s" }}
    >
      <div
        className={`max-w-[80%] px-5 py-4 text-sm transition-all ${
          isUser
            ? "bg-primary-600 text-white rounded-[24px] rounded-br-md shadow-sm"
            : isSystem
            ? "bg-gray-100 text-gray-600 rounded-[24px]"
            : "bg-white text-gray-800 rounded-[24px] rounded-bl-md shadow-bento hover:shadow-bento-hover"
        }`}
      >
        <ExpandableContent content={displayContent} isUser={isUser} />
        {isUser && attachments.length > 0 && (
          <AttachmentChips attachments={attachments} />
        )}
        {!isUser && !isSystem && (
          <GeneratedArtifactChips content={msg.content} artifactType={msg.artifactType} />
        )}
      </div>
    </div>
  );
}

export function MessageList({ onSend, onOpenQualityDialog, isLoading }: { onSend?: (content: string) => void; onOpenQualityDialog?: () => void; isLoading?: boolean }) {
  const messages = useChatStore((s) => s.messages);
  const streamingMessage = useChatStore((s) => s.streamingMessage);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const pptState = useChatStore((s) => s.pptState);
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);
  const deckStatus = useDeckStore((s) => s.deckStatus);
  const projectId = useDeckStore((s) => s.projectId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [isNearBottom, setIsNearBottom] = useState(true);
  const [showNewMessageBtn, setShowNewMessageBtn] = useState(false);

  // 找到最后一条用户消息（用于重试）
  const lastUserMessage = messages.reduce(
    (last: string, m) => (m.role === "user" && m.type === "text" ? m.content : last),
    ""
  );

  // P1-2: 智能滚动 — 监听滚动位置
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    setIsNearBottom(nearBottom);
    if (nearBottom) setShowNewMessageBtn(false);
  }, []);

  // 仅在靠近底部时自动滚动
  useEffect(() => {
    if (isNearBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    } else {
      setShowNewMessageBtn(true);
    }
  }, [messages, streamingMessage?.content, isNearBottom]);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowNewMessageBtn(false);
  }, []);

  const renderItems: Array<
    | { kind: "message"; msg: ChatMessage }
    | { kind: "reasoning"; messages: ChatMessage[] }
  > = [];

  for (const msg of messages) {
    if (msg.type && HIDDEN_MESSAGE_TYPES.has(msg.type)) {
      continue;
    }

    if (isReasoningMessage(msg)) {
      const lastItem = renderItems[renderItems.length - 1];
      if (lastItem?.kind === "reasoning") {
        lastItem.messages.push(msg);
      } else {
        renderItems.push({ kind: "reasoning", messages: [msg] });
      }
      continue;
    }

    renderItems.push({ kind: "message", msg });
  }

  // 最新大纲消息的 id（只有最新大纲展示确认卡片）
  const latestOutlineId = messages.reduce(
    (last: string, m) => (m.type === "outline" ? m.id : last),
    ""
  );

  // 确认操作仅当大纲就绪且未处理中时开放
  const canConfirmOutline = !isProcessing && (
    pptState === "outline_ready"
    || (currentArtifactType === "webdeck" && deckStatus === "plan_ready" && !!projectId)
  );

  if (messages.length === 0 && isLoading) {
    return (
      <div className="flex-1 p-4 space-y-4">
        {[...Array(3)].map((_, i) => (
          <div key={i} className={`flex ${i % 2 === 0 ? "justify-end" : "justify-start"}`}>
            <div className={`${i % 2 === 0 ? "w-[45%]" : "w-[60%]"} space-y-2`}>
              <div className="h-4 bg-gray-200 rounded-full animate-pulse" style={{ width: `${70 + i * 10}%` }} />
              <div className="h-4 bg-gray-200 rounded-full animate-pulse" style={{ width: `${50 + i * 15}%` }} />
              {i === 1 && <div className="h-4 bg-gray-200 rounded-full animate-pulse w-[40%]" />}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-4">
        <div className="text-center">
          <div className="w-16 h-16 rounded-2xl bg-primary-50 flex items-center justify-center mx-auto mb-4">
            <span className="text-3xl">🤖</span>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">你好！我是 Presentation Agent</p>
          <p className="text-sm text-gray-400">发一条消息开始对话</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex-1 overflow-y-auto p-4" ref={scrollContainerRef} onScroll={handleScroll}>
      {renderItems.map((item, index) => {
        if (item.kind === "reasoning") {
          const lastReasoningMessage = item.messages[item.messages.length - 1];
          const isLatestReasoningGroup = index === renderItems.length - 1;

          return (
            <ReasoningBubble
              key={item.messages.map((msg) => msg.id).join("-")}
              messages={item.messages}
              defaultExpanded={isProcessing && isLatestReasoningGroup && !!lastReasoningMessage}
            />
          );
        }

        const { msg } = item;
        return (
          <MessageBubble
            key={msg.id}
            msg={msg}
            isLatestOutline={msg.type === "outline" && msg.id === latestOutlineId && canConfirmOutline}
            onSend={onSend}
            onOpenQualityDialog={onOpenQualityDialog}
            lastUserMessage={lastUserMessage}
          />
        );
      })}

      {/* SubAgent 执行步骤时间线 */}
      <ExecutionTimeline />

      {/* 流式输出气泡 — 打字机效果 */}
      {streamingMessage && (
        <div className="flex my-3 justify-start animate-fadeIn" style={{ animationDuration: "0.2s" }}>
          <div className="max-w-[80%] px-5 py-4 text-sm bg-white text-gray-800 rounded-[24px] rounded-bl-md shadow-bento">
            <div className="prose prose-sm max-w-none break-words">
              {streamingMessage.content ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={sharedMarkdownComponents}>
                  {streamingMessage.content}
                </ReactMarkdown>
              ) : null}
              <span className="inline-block w-[2px] h-[1.1em] bg-primary-500 animate-pulse align-text-bottom ml-0.5" />
            </div>
          </div>
        </div>
      )}

      {/* P1-1: 打字指示器 — 等待 AI 响应时显示 */}
      {isProcessing && !streamingMessage && messages.length > 0 && messages[messages.length - 1]?.role === "user" && (
        <div className="flex my-3 justify-start animate-fadeIn">
          <div className="px-5 py-4 bg-white rounded-[24px] rounded-bl-md shadow-bento">
            <div className="animate-pulse-dot">
              <span /><span /><span />
            </div>
          </div>
        </div>
      )}

      <div ref={bottomRef} />

      {/* P1-2: "新消息" 悬浮按钮 — 用户上滑后显示 */}
      {showNewMessageBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-4 py-2 bg-white border border-gray-200 rounded-full text-xs font-medium text-gray-600 shadow-lg hover:bg-gray-50 transition-all z-10"
        >
          <ArrowDown className="w-3.5 h-3.5" />
          新消息
        </button>
      )}
    </div>
  );
}
