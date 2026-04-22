"use client";

import { useChatStore } from "@/stores/chatStore";

export function CodeViewer() {
  const artifactContent = useChatStore((s) => s.artifactContent);

  return (
    <div className="flex-1 overflow-auto bg-slate-950 text-slate-100">
      <div className="border-b border-slate-800 bg-slate-900/90 px-5 py-3 backdrop-blur-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-400">Code Artifact</p>
        <p className="mt-1 text-sm text-slate-400">历史会话中的代码产物已恢复，可在这里查看或下载。</p>
      </div>

      <div className="p-5">
        {artifactContent ? (
          <pre className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900 p-4 text-sm leading-6 text-slate-100 shadow-inner">
            <code>{artifactContent}</code>
          </pre>
        ) : (
          <div className="flex min-h-[240px] items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 text-sm text-slate-500">
            当前没有可显示的代码内容
          </div>
        )}
      </div>
    </div>
  );
}
