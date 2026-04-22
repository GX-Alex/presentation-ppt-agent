import type {
  DeckManifest as StoredDeckManifest,
  DeckPageData,
  DeckStatus as StoredDeckStatus,
  LaneKind,
  LaneStatus as StoredLaneStatus,
  PageKind,
  PageStatus as StoredPageStatus,
} from "@/stores/deckStore";

export type BackendWebDeckPage = {
  page_id?: string;
  title?: string;
  page_kind?: string;
  goal?: string;
  narrative_contract?: {
    audience?: string;
    core_message?: string;
  };
  asset_requirements?: Array<{
    description?: string;
  }>;
};

export type BackendWebDeckManifest = {
  title?: string;
  subtitle?: string;
  pages?: BackendWebDeckPage[];
};

export type BackendWebDeckSummaryPage = {
  page_id?: string;
  page_index?: number;
  title?: string;
  page_kind?: string;
  status?: string;
  has_html?: boolean;
  lanes?: Array<{
    lane_id?: string;
    kind?: string;
    status?: string;
    error?: string | null;
  }>;
};

export function normalizeDeckStatus(status?: string): StoredDeckStatus {
  switch (status) {
    case "planning":
      return "planning";
    case "plan_ready":
      return "plan_ready";
    case "generating":
    case "retrying":
      return "generating";
    case "reviewing":
      return "reviewing";
    case "completed":
      return "completed";
    case "failed":
    case "partial":
    default:
      return "failed";
  }
}

export function normalizePageKind(kind?: string): PageKind {
  switch (kind) {
    case "cover":
    case "toc":
    case "summary":
    case "content":
    case "architecture":
    case "chart_analysis":
    case "roadmap":
    case "comparison":
    case "closing":
    case "appendix":
      return kind;
    default:
      return "content";
  }
}

export function normalizePageStatus(status?: string): StoredPageStatus {
  switch (status) {
    case "running":
    case "in_progress":
    case "retrying":
      return "running";
    case "completed":
    case "done":
      return "done";
    case "failed":
      return "failed";
    case "pending":
    default:
      return "pending";
  }
}

export function normalizeLaneKind(kind?: string): LaneKind {
  switch (kind) {
    case "narrative":
    case "chart":
    case "diagram":
    case "asset":
    case "layout":
    case "review":
      return kind;
    default:
      return "narrative";
  }
}

export function normalizeLaneStatus(status?: string): StoredLaneStatus {
  switch (status) {
    case "running":
    case "in_progress":
    case "retrying":
      return "running";
    case "completed":
    case "done":
      return "done";
    case "failed":
      return "failed";
    case "pending":
    default:
      return "pending";
  }
}

export function mapManifest(manifest: BackendWebDeckManifest): StoredDeckManifest {
  const pages = Array.isArray(manifest.pages) ? manifest.pages : [];
  const audienceLevel = pages
    .map((page) => page.narrative_contract?.audience)
    .find((audience): audience is string => Boolean(audience)) || "通用";

  return {
    topic: manifest.title || "未命名 Web Deck",
    audienceLevel,
    totalPages: pages.length,
    pages: pages.map((page, index) => ({
      id: page.page_id || `page_${index + 1}`,
      pageIndex: index,
      title: page.title || `第 ${index + 1} 页`,
      kind: normalizePageKind(page.page_kind),
      keyPoints: [
        page.goal,
        ...(page.asset_requirements || []).map((item) => item.description).filter(Boolean),
      ].filter((item): item is string => Boolean(item)).slice(0, 3),
      narrativeHint: page.narrative_contract?.core_message || page.goal || "",
    })),
  };
}

export function buildShellPagesFromManifest(manifest: StoredDeckManifest): DeckPageData[] {
  return manifest.pages.map((page) => ({
    id: page.id,
    pageIndex: page.pageIndex,
    title: page.title,
    kind: page.kind,
    status: "pending",
    lanes: [],
  }));
}

export function formatWebDeckManifestSummary(manifest: StoredDeckManifest): string {
  return manifest.pages
    .map((page, index) => {
      const lines = [`${index + 1}. ${page.title} (${page.kind})`];
      if (page.narrativeHint) {
        lines.push(`   核心信息: ${page.narrativeHint}`);
      }
      if (page.keyPoints.length > 0) {
        lines.push(`   要点: ${page.keyPoints.join("；")}`);
      }
      return lines.join("\n");
    })
    .join("\n");
}

export function mapSummaryPages(
  pages: BackendWebDeckSummaryPage[],
  htmlByPageId: Record<string, string> = {},
): DeckPageData[] {
  return pages
    .map((page, index) => ({
      id: page.page_id || `page_${index + 1}`,
      pageIndex: typeof page.page_index === "number" ? page.page_index : index,
      title: page.title || `第 ${index + 1} 页`,
      kind: normalizePageKind(page.page_kind),
      status: normalizePageStatus(page.status),
      html: htmlByPageId[page.page_id || ""],
      lanes: (page.lanes || []).map((lane) => ({
        id: lane.lane_id || `${page.page_id || `page_${index + 1}`}_lane_${Math.random().toString(36).slice(2, 8)}`,
        laneKind: normalizeLaneKind(lane.kind),
        status: normalizeLaneStatus(lane.status),
        error: lane.error || undefined,
      })),
    }))
    .sort((left, right) => left.pageIndex - right.pageIndex);
}