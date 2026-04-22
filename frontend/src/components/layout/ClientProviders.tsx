/**
 * ClientProviders — 客户端组件容器。
 * 包含需要全局渲染的客户端组件（如 TokenCounter、Toast）。
 * Sprint 4: 开发者模式 Token 计数器。
 */
"use client";

import TokenCounter from "@/components/chat/TokenCounter";
import { ToastProvider } from "@/components/ui/Toast";

export default function ClientProviders({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ToastProvider>
      {children}
      <TokenCounter />
    </ToastProvider>
  );
}
