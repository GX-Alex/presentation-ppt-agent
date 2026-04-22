/**
 * Web Deck Brief 输入表单 — 用于收集用户需求。
 * 对齐 high.md §8.3：前端 Brief 表单。
 */
"use client";

import { useState, useCallback } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useChatStore } from "@/stores/chatStore";

export function DeckBriefForm() {
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("");
  const [pageCount, setPageCount] = useState<number | "">("");
  const [extras, setExtras] = useState("");
  const { sendWebDeckGenerate } = useWebSocket();
  const isProcessing = useChatStore((s) => s.isProcessing);

  const handleSubmit = useCallback(() => {
    if (!topic.trim() || isProcessing) return;
    sendWebDeckGenerate({
      topic: topic.trim(),
      audience: audience.trim() || undefined,
      page_count: typeof pageCount === "number" ? pageCount : undefined,
      extra: extras.trim() || undefined,
    });
  }, [topic, audience, pageCount, extras, isProcessing, sendWebDeckGenerate]);

  return (
    <div className="flex flex-col gap-4 p-6 max-w-md mx-auto">
      <h3 className="text-lg font-semibold text-gray-800">创建 Web Deck</h3>

      {/* 主题 */}
      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          主题 <span className="text-red-400">*</span>
        </label>
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="例如：2024 年 AI 发展趋势分析"
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-400 focus:border-transparent outline-none"
          disabled={isProcessing}
        />
      </div>

      {/* 受众 */}
      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          目标受众
        </label>
        <input
          type="text"
          value={audience}
          onChange={(e) => setAudience(e.target.value)}
          placeholder="例如：技术管理层、投资人"
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-400 focus:border-transparent outline-none"
          disabled={isProcessing}
        />
      </div>

      {/* 页数 */}
      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          目标页数
        </label>
        <input
          type="number"
          value={pageCount}
          onChange={(e) =>
            setPageCount(e.target.value ? parseInt(e.target.value, 10) : "")
          }
          placeholder="留空则自动"
          min={3}
          max={30}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-400 focus:border-transparent outline-none"
          disabled={isProcessing}
        />
      </div>

      {/* 补充说明 */}
      <div>
        <label className="block text-sm font-medium text-gray-600 mb-1">
          补充说明
        </label>
        <textarea
          value={extras}
          onChange={(e) => setExtras(e.target.value)}
          placeholder="风格偏好、重点内容、必须包含的要点..."
          rows={3}
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:ring-2 focus:ring-blue-400 focus:border-transparent outline-none"
          disabled={isProcessing}
        />
      </div>

      {/* 提交 */}
      <button
        onClick={handleSubmit}
        disabled={!topic.trim() || isProcessing}
        className="w-full py-2.5 px-4 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isProcessing ? "生成中..." : "开始生成"}
      </button>
    </div>
  );
}
