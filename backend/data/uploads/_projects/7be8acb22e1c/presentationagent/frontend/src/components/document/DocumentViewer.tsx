"use client";

import { useChatStore } from "@/stores/chatStore";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export function DocumentViewer() {
  const artifactContent = useChatStore((s) => s.artifactContent);

  return (
    <div className="flex-1 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white flex flex-col">
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100 bg-gray-50/50">
        <div className="flex items-center gap-3">
          <span className="text-2xl">📄</span>
          <h2 className="text-lg font-medium text-gray-800">智能文档</h2>
        </div>
        <div className="text-sm text-gray-500 font-mono">
          Markdown / Rich Text
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-8 bg-white max-w-none">
        {artifactContent ? (
          <div className="prose prose-slate max-w-3xl mx-auto prose-h1:text-2xl prose-h2:text-xl prose-h3:text-lg prose-a:text-blue-600 prose-img:rounded-xl">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {artifactContent}
            </ReactMarkdown>
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-gray-400">
            <span className="animate-pulse">文档加载中...</span>
          </div>
        )}
      </div>
    </div>
  );
}