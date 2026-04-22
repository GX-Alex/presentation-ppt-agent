"use client";

import { useEffect, useRef, useState } from "react";
import { useChatStore } from "@/stores/chatStore";

export function WebSandboxViewer() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  // Prefer htmlArtifactContent (preserved across composite tasks) over artifactContent
  const htmlArtifactContent = useChatStore((s) => s.htmlArtifactContent);
  const artifactContent = useChatStore((s) => s.artifactContent);
  const content = htmlArtifactContent || artifactContent;
  const [renderCounter, setRenderCounter] = useState(0);

  // 当代码变更时重新触发 iframe 渲染
  useEffect(() => {
    setRenderCounter((c) => c + 1);
  }, [content]);

  // 将用户提供的工件内容（通常是 HTML/JS/CSS 混合代码）注入到 Iframe 的 srcDoc 中
  const htmlContent = content || `
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <style>
    body { font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #fafafa; color: #a1a1aa; }
  </style>
</head>
<body>
  <div>沙盒准备就绪</div>
</body>
</html>
  `;

  return (
    <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white flex flex-col">
      {/* 浏览器顶部导航条模拟 */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-gray-100 bg-gray-50/80">
        <div className="flex gap-1.5 mr-2">
          <div className="w-3 h-3 rounded-full bg-red-400"></div>
          <div className="w-3 h-3 rounded-full bg-yellow-400"></div>
          <div className="w-3 h-3 rounded-full bg-green-400"></div>
        </div>
        <div className="flex-1 px-3 py-1 bg-white border border-gray-200 rounded-md text-xs text-gray-500 font-mono text-center shadow-sm">
          localhost:3000 / Web 沙盒预览
        </div>
        <button 
          onClick={() => setRenderCounter(c => c + 1)}
          className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-md transition-colors"
          title="刷新预览"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
        </button>
      </div>

      <div className="flex-1 relative bg-white">
        <iframe
          key={renderCounter} // 强制完全重新加载
          ref={iframeRef}
          className="w-full h-full border-0 absolute inset-0"
          srcDoc={htmlContent}
          sandbox="allow-scripts allow-forms allow-same-origin allow-popups"
          title="Web Sandbox"
        />
      </div>
    </div>
  );
}