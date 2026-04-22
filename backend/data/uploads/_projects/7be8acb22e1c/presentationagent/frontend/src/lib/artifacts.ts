import type { ArtifactType } from "@/stores/chatStore";

export type WorkspaceArtifactType = Extract<ArtifactType, "drawio" | "document" | "webpage" | "code">;

const WORKSPACE_ARTIFACT_TYPES: WorkspaceArtifactType[] = ["drawio", "document", "webpage", "code"];
const ARTIFACT_REGEX = /<general-artifact\s+type="([^"]+)">([\s\S]*?)<\/general-artifact>/i;

export const ARTIFACT_PLACEHOLDER = "\n> ✨ *智能工作区已更新，请在右侧面板查看。*\n";

export interface ParsedWorkspaceArtifact {
  artifactType: WorkspaceArtifactType;
  artifactContent: string;
  cleanedContent: string;
}

const WORKSPACE_ARTIFACT_LABELS: Record<WorkspaceArtifactType, string> = {
  drawio: "draw.io 图",
  document: "文档",
  webpage: "网页原型",
  code: "代码产物",
};

export function isWorkspaceArtifactType(value: string): value is WorkspaceArtifactType {
  return WORKSPACE_ARTIFACT_TYPES.includes(value as WorkspaceArtifactType);
}

export function parseWorkspaceArtifact(rawContent: string): ParsedWorkspaceArtifact | null {
  const match = rawContent.match(ARTIFACT_REGEX);
  if (!match) {
    return null;
  }

  const artifactType = match[1];
  if (!isWorkspaceArtifactType(artifactType)) {
    return null;
  }

  return {
    artifactType,
    artifactContent: match[2].trim(),
    cleanedContent: rawContent.replace(ARTIFACT_REGEX, ARTIFACT_PLACEHOLDER),
  };
}

export function findLatestWorkspaceArtifact(messages: Array<{ content: string }>): ParsedWorkspaceArtifact | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const parsed = parseWorkspaceArtifact(messages[index]?.content || "");
    if (parsed) {
      return parsed;
    }
  }

  return null;
}

export function buildWorkspaceArtifactEnvelope(
  artifactType: WorkspaceArtifactType,
  artifactContent: string,
): string {
  return `<general-artifact type="${artifactType}">\n${artifactContent.trim()}\n</general-artifact>`;
}

export function buildWorkspaceSyncMessage(
  artifactType: WorkspaceArtifactType,
  artifactContent: string,
): string {
  const label = WORKSPACE_ARTIFACT_LABELS[artifactType] || "工作区产物";
  return [
    `当前工作区中的最新${label}已由用户手动编辑并保存。后续修改必须严格以此版本为准。`,
    buildWorkspaceArtifactEnvelope(artifactType, artifactContent),
  ].join("\n\n");
}