/**
 * TokenCounter 组件 — 开发者模式的 Token 用量计数器。
 * Sprint 4: 显示当前 Token 用量、使用比率、告警状态。
 * 仅在 devMode 开启时显示。
 */
"use client";

import { useChatStore } from "@/stores/chatStore";

export default function TokenCounter() {
  const { tokenUsage, devMode } = useChatStore();

  // 非开发者模式不渲染
  if (!devMode || !tokenUsage) return null;

  const ratio = tokenUsage.usageRatio * 100;
  const isAlert = tokenUsage.alert;

  // 进度条颜色
  const barColor = isAlert
    ? "bg-red-500"
    : ratio > 50
    ? "bg-yellow-500"
    : "bg-green-500";

  return (
    <div
      className={`fixed bottom-4 right-4 z-50 w-72 rounded-lg shadow-lg border p-3 text-xs ${
        isAlert
          ? "bg-red-50 border-red-200"
          : "bg-white border-gray-200"
      }`}
    >
      {/* 标题 */}
      <div className="flex items-center justify-between mb-2">
        <span className="font-semibold text-gray-700">🔢 Token 监控</span>
        <span
          className={`px-1.5 py-0.5 rounded ${
            isAlert ? "bg-red-100 text-red-600" : "bg-gray-100 text-gray-500"
          }`}
        >
          {ratio.toFixed(1)}%
        </span>
      </div>

      {/* 进度条 */}
      <div className="w-full bg-gray-200 rounded-full h-1.5 mb-2">
        <div
          className={`h-1.5 rounded-full transition-all ${barColor}`}
          style={{ width: `${Math.min(ratio, 100)}%` }}
        />
      </div>

      {/* 详情 */}
      <div className="grid grid-cols-2 gap-1 text-gray-500">
        <span>Prompt:</span>
        <span className="text-right font-mono">
          {tokenUsage.promptTokens.toLocaleString()}
        </span>
        <span>Completion:</span>
        <span className="text-right font-mono">
          {tokenUsage.completionTokens.toLocaleString()}
        </span>
        <span>Total:</span>
        <span className="text-right font-mono">
          {tokenUsage.totalTokens.toLocaleString()}
        </span>
        <span>Context:</span>
        <span className="text-right font-mono">
          {tokenUsage.contextWindow.toLocaleString()}
        </span>
      </div>

      {/* 告警消息 */}
      {isAlert && tokenUsage.alertMessage && (
        <div className="mt-2 p-2 bg-red-100 text-red-700 rounded text-xs">
          {tokenUsage.alertMessage}
        </div>
      )}
    </div>
  );
}
