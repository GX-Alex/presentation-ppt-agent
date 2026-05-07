"use client";

import { useChatStore } from "@/stores/chatStore";
import { PreviewPanel as PptViewer } from "@/components/ppt/PreviewPanel";
import { DiagramWorkspaceShell } from "@/components/drawio/DiagramWorkspaceShell";
import { CodeViewer } from "@/components/code/CodeViewer";
import { DocumentViewer } from "@/components/document/DocumentViewer";
import { WebSandboxViewer } from "@/components/web/WebSandboxViewer";
import { DeckViewer } from "@/components/webdeck/DeckViewer";
import { ArtifactActionsBar } from "./ArtifactActionsBar";

export function WorkspacePanel() {
  const currentArtifactType = useChatStore((s) => s.currentArtifactType);

  if (currentArtifactType === "drawio") {
    return (
      <div className="flex-1 min-h-0 w-full flex flex-col">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
          <ArtifactActionsBar />
          <DiagramWorkspaceShell />
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 w-full h-full relative flex flex-col">
      <ArtifactActionsBar />

      {currentArtifactType === "ppt" && <PptViewer />}
      {currentArtifactType === "code" && <CodeViewer />}
      {currentArtifactType === "document" && <DocumentViewer />}
      {currentArtifactType === "webpage" && <WebSandboxViewer />}
      {currentArtifactType === "webdeck" && <DeckViewer />}

      {currentArtifactType === "none" && (
        <div className="flex-1 flex items-center justify-center text-gray-500 relative">
           <div className="text-center">
              <div className="w-20 h-20 rounded-2xl bg-gray-50 flex items-center justify-center mx-auto mb-5 border border-gray-100 shadow-sm">
                <span className="text-4xl text-gray-400">✨</span>
              </div>
              <p className="text-base font-medium text-gray-500 mb-2">智能工作区已就绪</p>
              <p className="text-sm text-gray-400/80 mb-4 max-w-[250px] mx-auto leading-relaxed">
                在左侧输入需求，AI 将在这里为您生成 <br/> 幻灯片、流程图、智能文档或 Web 应用
              </p>
           </div>
        </div>
      )}
    </div>
  );
}
