/**
 * FileUpload 组件 — 文件上传面板。
 * Sprint 5: 📎 附件按钮 + 拖拽上传 + 文件预览 + 上传进度。
 */
"use client";

import { useState, useRef, useCallback, useEffect } from "react";

/** 上传文件的状态 */
export interface UploadFileItem {
  id: string;
  file: File;
  name: string;
  size: number;
  type: string;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
  assetId?: string;
  fileUrl?: string;
  error?: string;
}

/** 上传成功后的结果 */
export interface UploadResult {
  asset_id: string;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  file_url: string;
}

interface FileUploadProps {
  /** 上传完成回调（传递已上传文件信息给父组件） */
  onUploadComplete?: (results: UploadResult[]) => void;
  /** 上传状态回调（true: 正在上传，false: 无上传） */
  onUploadingStateChange?: (isUploading: boolean) => void;
  /** 关联任务 ID */
  taskId?: string | null;
  /** 是否禁用 */
  disabled?: boolean;
}

/** 允许的文件扩展名 */
const ALLOWED_EXTENSIONS = [
  ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv",
  ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json",
  ".yaml", ".yml", ".java", ".go", ".rs", ".c", ".cpp", ".h",
  ".sh", ".sql", ".zip",
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
];

/** 最大文件大小 50MB */
const MAX_FILE_SIZE = 50 * 1024 * 1024;

/** 格式化文件大小 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

/** 生成唯一 ID */
function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

/** 根据扩展名获取文件图标 */
function getFileIcon(name: string): string {
  const ext = name.split(".").pop()?.toLowerCase() || "";
  const iconMap: Record<string, string> = {
    pdf: "📕", docx: "📘", pptx: "📙", xlsx: "📗",
    txt: "📝", md: "📝", csv: "📊",
    zip: "📦",
    png: "🖼️", jpg: "🖼️", jpeg: "🖼️", gif: "🖼️", webp: "🖼️", svg: "🖼️",
    py: "🐍", js: "📜", ts: "📜", jsx: "📜", tsx: "📜",
    html: "🌐", css: "🎨", json: "📋",
  };
  return iconMap[ext] || "📄";
}

export function FileUpload({ onUploadComplete, onUploadingStateChange, taskId, disabled }: FileUploadProps) {
  const [files, setFiles] = useState<UploadFileItem[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [showPanel, setShowPanel] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  /** 校验文件 */
  const validateFile = useCallback((file: File): string | null => {
    // 扩展名检查
    const ext = "." + (file.name.split(".").pop()?.toLowerCase() || "");
    if (!ALLOWED_EXTENSIONS.includes(ext)) {
      return `不支持的文件类型: ${ext}`;
    }
    // 大小检查
    if (file.size > MAX_FILE_SIZE) {
      return `文件过大: ${formatSize(file.size)}，最大 ${formatSize(MAX_FILE_SIZE)}`;
    }
    return null;
  }, []);

  /** 添加文件到列表 */
  const addFiles = useCallback((newFiles: FileList | File[]) => {
    const items: UploadFileItem[] = [];
    for (const file of Array.from(newFiles)) {
      const error = validateFile(file);
      items.push({
        id: uid(),
        file,
        name: file.name,
        size: file.size,
        type: file.type,
        status: error ? "error" : "pending",
        progress: 0,
        error: error || undefined,
      });
    }
    setFiles((prev) => [...prev, ...items]);
    setShowPanel(true);
  }, [validateFile]);

  /** 上传所有待上传文件 */
  const uploadAll = useCallback(async () => {
    const pendingFiles = files.filter((f) => f.status === "pending");
    if (pendingFiles.length === 0) return;

    const formData = new FormData();
    for (const item of pendingFiles) {
      formData.append("files", item.file);
    }
    if (taskId) {
      formData.append("task_id", taskId);
    }

    // 标记所有待上传为 uploading
    setFiles((prev) =>
      prev.map((f) =>
        f.status === "pending" ? { ...f, status: "uploading" as const, progress: 50 } : f
      )
    );

    try {
      const resp = await fetch(`/api/files/upload${taskId ? `?task_id=${taskId}` : ""}`, {
        method: "POST",
        body: formData,
      });

      if (!resp.ok) {
        throw new Error(`上传失败: HTTP ${resp.status}`);
      }

      const data = await resp.json();
      const uploaded: UploadResult[] = data.uploaded || [];
      const errors: Array<{ filename: string; error: string }> = data.errors || [];

      // 更新文件状态
      setFiles((prev) =>
        prev.map((f) => {
          if (f.status !== "uploading") return f;
          // 查找上传成功的结果
          const result = uploaded.find((u) => u.filename === f.name);
          if (result) {
            return {
              ...f,
              status: "success" as const,
              progress: 100,
              assetId: result.asset_id,
              fileUrl: result.file_url,
            };
          }
          // 查找失败的结果
          const err = errors.find((e) => e.filename === f.name);
          if (err) {
            return { ...f, status: "error" as const, progress: 0, error: err.error };
          }
          return { ...f, status: "error" as const, progress: 0, error: "未知错误" };
        })
      );

      // 回调通知
      if (uploaded.length > 0 && onUploadComplete) {
        onUploadComplete(uploaded);
      }
    } catch (err) {
      // 全部标记为失败
      const errorMsg = err instanceof Error ? err.message : "上传失败";
      setFiles((prev) =>
        prev.map((f) =>
          f.status === "uploading" ? { ...f, status: "error" as const, progress: 0, error: errorMsg } : f
        )
      );
    }
  }, [files, taskId, onUploadComplete]);

  /** 自动触发待上传文件 */
  useEffect(() => {
    if (files.some((f) => f.status === "pending")) {
      uploadAll();
    }
  }, [files, uploadAll]);

  /** 回调上传状态 */
  useEffect(() => {
    if (onUploadingStateChange) {
      const isUploading = files.some(f => f.status === "pending" || f.status === "uploading");
      onUploadingStateChange(isUploading);
    }
  }, [files, onUploadingStateChange]);

  /** 移除文件 */
  const removeFile = useCallback((id: string) => {
    setFiles((prev) => {
      const next = prev.filter((f) => f.id !== id);
      if (next.length === 0) setShowPanel(false);
      return next;
    });
  }, []);

  /** 清空所有 */
  const clearAll = useCallback(() => {
    setFiles([]);
    setShowPanel(false);
  }, []);

  /** 点击 📎 按钮 */
  const handleAttachClick = useCallback(() => {
    if (showPanel && files.length > 0) {
      setShowPanel(false);
    } else if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  }, [showPanel, files.length]);

  /** 文件选择器 onChange */
  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        addFiles(e.target.files);
      }
      // 重置 input（允许重复选择同一文件）
      e.target.value = "";
    },
    [addFiles]
  );

  // ──── 拖拽事件 ────
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);

      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles]
  );

  const hasPending = files.some((f) => f.status === "pending");
  const hasFiles = files.length > 0;

  return (
    <>
      {/* 隐藏的文件选择器 */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileSelect}
        accept={ALLOWED_EXTENSIONS.join(",")}
      />

      {/* 📎 附件按钮 */}
      <button
        onClick={handleAttachClick}
        disabled={disabled}
        className={`p-2 transition-colors ${
          hasFiles
            ? "text-primary-600 hover:text-primary-700"
            : "text-gray-400 hover:text-gray-600"
        } disabled:opacity-40 disabled:cursor-not-allowed relative`}
        title="上传附件"
      >
        📎
        {hasFiles && (
          <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-primary-500 text-white text-[10px] rounded-full flex items-center justify-center">
            {files.length}
          </span>
        )}
      </button>

      {/* 拖拽覆盖层 */}
      {isDragging && (
        <div
          className="fixed inset-0 z-50 bg-primary-50/80 flex items-center justify-center"
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <div className="bg-white rounded-2xl border-2 border-dashed border-primary-400 p-12 text-center shadow-lg">
            <div className="text-4xl mb-3">📂</div>
            <div className="text-lg font-medium text-gray-700">拖拽文件到此处上传</div>
            <div className="text-sm text-gray-400 mt-1">
              支持文档、代码、图片、ZIP 压缩包
            </div>
          </div>
        </div>
      )}

      {/* 文件列表面板 */}
      {showPanel && hasFiles && (
        <div className="absolute bottom-full left-0 right-0 mb-1 mx-4 bg-white border border-gray-200 rounded-xl shadow-lg max-h-60 overflow-y-auto">
          {/* 头部 */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100 bg-gray-50 rounded-t-xl">
            <span className="text-xs font-medium text-gray-600">
              附件 ({files.length})
            </span>
            <div className="flex gap-1">
              {hasPending && (
                <button
                  onClick={uploadAll}
                  className="text-xs px-2 py-0.5 bg-primary-500 text-white rounded hover:bg-primary-600 transition-colors"
                >
                  全部上传
                </button>
              )}
              <button
                onClick={clearAll}
                className="text-xs px-2 py-0.5 text-gray-400 hover:text-red-500 transition-colors"
              >
                清空
              </button>
            </div>
          </div>

          {/* 文件列表 */}
          <div className="divide-y divide-gray-50">
            {files.map((item) => (
              <div key={item.id} className="flex items-center gap-2 px-3 py-1.5 text-sm">
                <span className="text-base">{getFileIcon(item.name)}</span>
                <div className="flex-1 min-w-0">
                  <div className="truncate text-gray-700">{item.name}</div>
                  <div className="text-xs text-gray-400 flex items-center gap-2">
                    <span>{formatSize(item.size)}</span>
                    {item.status === "uploading" && (
                      <span className="text-primary-500">上传中...</span>
                    )}
                    {item.status === "success" && (
                      <span className="text-green-500">✓ 已上传</span>
                    )}
                    {item.status === "error" && (
                      <span className="text-red-500" title={item.error}>
                        ✗ {item.error}
                      </span>
                    )}
                  </div>
                </div>
                {/* 进度条 */}
                {item.status === "uploading" && (
                  <div className="w-16 h-1 bg-gray-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-primary-500 transition-all"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                )}
                {/* 删除按钮 */}
                <button
                  onClick={() => removeFile(item.id)}
                  className="text-gray-300 hover:text-red-400 transition-colors text-xs"
                  title="移除"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

/** 将拖拽事件处理器暴露出去，供父组件在外层 DIV 注册 */
export function useDragDrop(addFiles: (files: FileList) => void) {
  const [isDragging, setIsDragging] = useState(false);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length > 0) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles]
  );

  return { isDragging, onDragOver, onDragLeave, onDrop };
}
