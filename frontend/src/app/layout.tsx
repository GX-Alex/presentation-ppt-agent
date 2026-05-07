import type { Metadata } from "next";
import { Viewport } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import ClientProviders from "@/components/layout/ClientProviders";

export const metadata: Metadata = {
  title: "Presentation Agent Platform",
  description: "通用智能体平台 — AI 驱动的 PPT/文档生成",
};

/** 响应式视口配置 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="h-screen overflow-hidden flex p-[var(--bento-gap)] gap-[var(--bento-gap)]">
        <Sidebar />
        <main className="flex-1 bento-card overflow-hidden flex flex-col md:ml-0 ml-0">
          <ClientProviders>{children}</ClientProviders>
        </main>
      </body>
    </html>
  );
}
