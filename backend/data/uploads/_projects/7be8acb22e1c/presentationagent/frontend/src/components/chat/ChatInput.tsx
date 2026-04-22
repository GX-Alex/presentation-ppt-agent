/**
 * ChatInput 组件 — 消息输入框 + 发送按钮 + 附件上传。
 * 支持 Enter 发送、Shift+Enter 换行。
 * 输入框可展开/折叠，默认较大。
 * Sprint 5: 📎 附件按钮 + 拖拽上传 + URL 自动识别。
 */
"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useChatStore } from "@/stores/chatStore";
import { FileUpload, type UploadResult } from "./FileUpload";
import { ChevronUp, ChevronDown, Send } from "lucide-react";
import { QualityGenerateDialog } from "./QualityGenerateDialog";
import type { QualityGenerateBrief } from "@/lib/qualityGeneration";
import { useToast } from "@/components/ui/Toast";
import {
  buildWorkspaceSyncMessage,
  findLatestWorkspaceArtifact,
  isWorkspaceArtifactType,
} from "@/lib/artifacts";

interface ChatInputProps {
  /** 发送消息回调 */
  onSend: (content: string, attachments?: UploadResult[]) => void;
  /** 高质量结构化生成 */
  onQualityGenerate?: (brief: QualityGenerateBrief) => boolean | Promise<boolean>;
  showQualityDialog?: boolean;
  onCloseQualityDialog?: () => void;
}

/** URL 匹配正则 */
const URL_REGEX = /https?:\/\/[^\s<>"')\]]+/gi;

export function ChatInput({ onSend, onQualityGenerate, showQualityDialog = false, onCloseQualityDialog }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<UploadResult[]>([]);
  const [isFileUploading, setIsFileUploading] = useState(false);
  const [isSyncingWorkspaceArtifact, setIsSyncingWorkspaceArtifact] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const connectionStatus = useChatStore((s) => s.connectionStatus);
  const taskId = useChatStore((s) => s.taskId);
  const isProcessing = useChatStore((s) => s.isProcessing);
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);
  const artifactContent = useChatStore((s) => s.artifactContent);
  const messages = useChatStore((s) => s.messages);
  const addMessage = useChatStore((s) => s.addMessage);
  const toast = useToast();

  const isConnected = connectionStatus === "connected";
  const isConnecting = connectionStatus === "connecting";

  // P1-5: AI 处理结束后自动聚焦输入框
  const prevProcessing = useRef(isProcessing);
  useEffect(() => {
    if (prevProcessing.current && !isProcessing) {
      textareaRef.current?.focus();
    }
    prevProcessing.current = isProcessing;
  }, [isProcessing]);

  const syncWorkspaceArtifactIfNeeded = useCallback(async (): Promise<boolean> => {
    if (!taskId || taskId === "new") {
      return true;
    }
    if (!artifactContent || !isWorkspaceArtifactType(currentArtifactType)) {
      return true;
    }

    const currentContent = artifactContent.trim();
    const latestArtifact = findLatestWorkspaceArtifact(messages);
    if (!currentContent || latestArtifact?.artifactContent?.trim() === currentContent) {
      return true;
    }

    setIsSyncingWorkspaceArtifact(true);
    try {
      const response = await fetch(`/api/tasks/${taskId}/workspace-artifact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          artifact_type: currentArtifactType,
          content: currentContent,
        }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "同步工作区内容失败");
      }

      const payload = await response.json();
      addMessage({
        id: (payload.message_id as string) || crypto.randomUUID(),
        role: "user",
        content: (payload.content as string) || buildWorkspaceSyncMessage(currentArtifactType, currentContent),
        type: "workspace_sync",
        timestamp: Date.now(),
      });
      return true;
    } catch (error) {
      console.error("[ChatInput] 同步工作区内容失败:", error);
      toast.error(`同步当前工作区失败：${error instanceof Error ? error.message : "未知错误"}`);
      return false;
    } finally {
      setIsSyncingWorkspaceArtifact(false);
    }
  }, [addMessage, artifactContent, currentArtifactType, messages, taskId, toast]);

  /** 发送消息（附带已上传文件信息） */
  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if ((!trimmed && uploadedFiles.length === 0) || !isConnected) return;

    const synced = await syncWorkspaceArtifactIfNeeded();
    if (!synced) {
      return;
    }

    // 检测消息中的 URL（自动识别）
    trimmed.match(URL_REGEX);
    let enrichedContent = trimmed;

    // 附带上传文件信息
    if (uploadedFiles.length > 0) {
      const fileInfo = uploadedFiles
        .map((f) => `[附件: ${f.filename} (Asset ID: ${f.asset_id}, URL: ${f.file_url})]`)
        .join("\n");
      enrichedContent = `${trimmed}\n\n${fileInfo}`;
    }

    onSend(enrichedContent, uploadedFiles.length > 0 ? uploadedFiles : undefined);
    setInput("");
    setUploadedFiles([]);

    // 重置 textarea 高度
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, isConnected, onSend, syncWorkspaceArtifactIfNeeded, uploadedFiles]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        void handleSend();
      }
    },
    [handleSend]
  );

  // 自动调整 textarea 高度（展开模式最大 300px，折叠模式最大 160px）
  const handleInput = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      setInput(e.target.value);
      const el = e.target;
      el.style.height = "auto";
      const maxH = expanded ? 300 : 160;
      el.style.height = Math.min(el.scrollHeight, maxH) + "px";
    },
    [expanded]
  );

  /** 粘贴事件 — 检测 URL 或文件 */
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      // 检查剪贴板中的文件（如截图粘贴）
      const items = e.clipboardData.items;
      const pastedFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        if (items[i].kind === "file") {
          const file = items[i].getAsFile();
          if (file) pastedFiles.push(file);
        }
      }
      // 文件粘贴由 FileUpload 组件处理（暂不拦截原生粘贴）
    },
    []
  );

  /** 上传完成回调 */
  const handleUploadComplete = useCallback((results: UploadResult[]) => {
    setUploadedFiles((prev) => [...prev, ...results]);
  }, []);

  /** 检测输入中的 URL 并高亮提示 */
  const hasUrl = URL_REGEX.test(input);
  // 重置 regex lastIndex
  URL_REGEX.lastIndex = 0;

  return (
    <div
      className="p-3 relative"
      onDragOver={(e) => e.preventDefault()}
    >
      <QualityGenerateDialog
        open={showQualityDialog}
        attachments={uploadedFiles}
        onClose={() => onCloseQualityDialog?.()}
        onSubmit={async (brief) => {
          const submitted = (await onQualityGenerate?.(brief)) ?? false;
          if (!submitted) {
            toast.error("Brief 提交失败，当前连接未就绪，请稍后重试");
            return false;
          }
          toast.success("Brief 已提交，正在准备大纲");
          setInput("");
          setUploadedFiles([]);
          if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
          }
          return true;
        }}
      />

      {/* 连接状态指示器 */}
      {!isConnected && (
        <div
          className={`text-xs mb-2 flex items-center gap-1 ${
            isConnecting ? "text-yellow-500" : "text-red-400"
          }`}
        >
          <span
            className={`inline-block w-1.5 h-1.5 rounded-full ${
              isConnecting ? "bg-yellow-400 animate-pulse" : "bg-red-400"
            }`}
          />
          {isConnecting ? "正在连接..." : "连接断开，正在重连..."}
        </div>
      )}

      {/* 已上传文件提示 */}
      {uploadedFiles.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {uploadedFiles.map((f, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary-50 text-primary-700 rounded-lg text-xs"
            >
              📎 {f.filename}
              <button
                onClick={() => setUploadedFiles((prev) => prev.filter((_, idx) => idx !== i))}
                className="ml-0.5 text-primary-400 hover:text-red-500"
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {/* URL 检测提示 */}
      {hasUrl && (
        <div className="text-xs text-primary-500 mb-1.5 flex items-center gap-1">
          🔗 检测到 URL — 发送后可自动抓取网页内容
        </div>
      )}

      {/* 毛玻璃悬浮输入框 */}
      <div className="glass-float rounded-2xl overflow-hidden">
        <div className="flex items-end gap-2 p-2">
          {/* 📎 附件上传组件 */}
          <div className="flex items-center gap-1 pb-1">
            <FileUpload
              onUploadComplete={handleUploadComplete}
              onUploadingStateChange={setIsFileUploading}
              taskId={taskId}
              disabled={!isConnected}
            />
            {/* 展开/折叠按钮 */}
            <button
              onClick={() => setExpanded((v) => !v)}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-black/5 transition-colors"
              title={expanded ? "折叠输入框" : "展开输入框"}
            >
              {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronUp className="w-3.5 h-3.5" />}
            </button>
          </div>

          {/* 输入框 */}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={
              isProcessing
                ? "AI 正在处理中..."
                : isSyncingWorkspaceArtifact
                  ? "正在同步当前工作区..."
                : isConnected
                  ? "输入消息，Enter 发送..."
                  : "等待连接..."
            }
            disabled={!isConnected || isProcessing || isSyncingWorkspaceArtifact}
            rows={expanded ? 6 : 2}
            className="flex-1 px-3 py-2 bg-transparent border-none
              focus:outline-none
              disabled:text-gray-400
              resize-none text-sm leading-relaxed transition-all"
          />

          {/* 发送按钮 */}
          <div className="pb-1">
            <button
              onClick={() => {
                void handleSend();
              }}
              disabled={(!input.trim() && uploadedFiles.length === 0) || isFileUploading || !isConnected || isProcessing || isSyncingWorkspaceArtifact}
              className={`p-2.5 rounded-xl transition-all ${
                isProcessing || isFileUploading || isSyncingWorkspaceArtifact
                  ? "bg-gray-300 cursor-not-allowed"
                  : (input.trim() || uploadedFiles.length > 0)
                    ? "bg-primary-600 hover:bg-primary-700 active:scale-95 shadow-sm"
                    : "bg-gray-200 cursor-not-allowed"
              } text-white`}
              title={isSyncingWorkspaceArtifact ? "正在同步当前工作区..." : isProcessing ? "处理中..." : isFileUploading ? "正在上传附件..." : "发送消息"}
            >
              {isProcessing || isSyncingWorkspaceArtifact ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
