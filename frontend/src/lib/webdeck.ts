import type {
  DeckManifest as StoredDeckManifest,
  DeckPageBundle,
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
  page_bundle?: Record<string, unknown> | null;
  lanes?: Array<{
    lane_id?: string;
    kind?: string;
    status?: string;
    error?: string | null;
  }>;
};

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  return value as Record<string, unknown>;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

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

export function normalizePageBundle(raw?: Record<string, unknown> | null): DeckPageBundle | undefined {
  const record = asRecord(raw);
  if (!record) {
    return undefined;
  }

  const artifacts = Array.isArray(record.artifacts)
    ? record.artifacts
        .map((item) => asRecord(item))
        .filter((item): item is Record<string, unknown> => Boolean(item))
        .map((item) => ({
          assetId: String(item.asset_id || item.assetId || ""),
          kind: String(item.kind || "asset"),
          content: item.content ? String(item.content) : undefined,
          metadata: asRecord(item.metadata) || {},
        }))
    : [];

  const editableModel = Array.isArray(record.editable_model ?? record.editableModel)
    ? (record.editable_model ?? record.editableModel as Array<unknown>)
        .map((item) => asRecord(item))
        .filter((item): item is Record<string, unknown> => Boolean(item))
        .map((item) => ({
          nodeId: String(item.node_id || item.nodeId || ""),
          nodeKind: String(item.node_kind || item.nodeKind || "text"),
          tagName: String(item.tag_name || item.tagName || "div"),
          text: String(item.text || ""),
          selectorHint: String(item.selector_hint || item.selectorHint || ""),
          layoutScopeId: item.layout_scope_id || item.layoutScopeId
            ? String(item.layout_scope_id || item.layoutScopeId)
            : undefined,
          editable: item.editable !== false,
        }))
    : [];

  const layoutModel = Array.isArray(record.layout_model ?? record.layoutModel)
    ? (record.layout_model ?? record.layoutModel as Array<unknown>)
        .map((item) => asRecord(item))
        .filter((item): item is Record<string, unknown> => Boolean(item))
        .map((item) => ({
          scopeId: String(item.scope_id || item.scopeId || ""),
          scopeKind: String(item.scope_kind || item.scopeKind || "container"),
          tagName: String(item.tag_name || item.tagName || "div"),
          label: String(item.label || item.scope_kind || item.scopeKind || "布局区"),
          moduleNodeIds: asStringArray(item.module_node_ids || item.moduleNodeIds),
          allowedOps: asStringArray(item.allowed_ops || item.allowedOps),
          parameters: asRecord(item.parameters) || {},
        }))
    : [];

  const assetManifest = Array.isArray(record.asset_manifest ?? record.assetManifest)
    ? (record.asset_manifest ?? record.assetManifest as Array<unknown>)
        .map((item) => asRecord(item))
        .filter((item): item is Record<string, unknown> => Boolean(item))
        .map((item) => ({
          assetId: String(item.asset_id || item.assetId || ""),
          kind: String(item.kind || "asset"),
          label: String(item.label || item.kind || "asset"),
          editableVia: String(item.editable_via || item.editableVia || "preview_only"),
          bindingNodeId: item.binding_node_id || item.bindingNodeId
            ? String(item.binding_node_id || item.bindingNodeId)
            : undefined,
          metadata: asRecord(item.metadata) || {},
        }))
    : [];

  return {
    pageId: record.page_id ? String(record.page_id) : record.pageId ? String(record.pageId) : undefined,
    status: record.status ? String(record.status) : undefined,
    html: record.html ? String(record.html) : undefined,
    cssTokens: asRecord(record.css_tokens || record.cssTokens) || {},
    jsModules: asStringArray(record.js_modules || record.jsModules),
    artifacts,
    editorSchemaVersion: record.editor_schema_version
      ? String(record.editor_schema_version)
      : record.editorSchemaVersion
      ? String(record.editorSchemaVersion)
      : undefined,
    editableModel,
    layoutModel,
    assetManifest,
    renderHints: asRecord(record.render_hints || record.renderHints) || {},
    review: asRecord(record.review) || null,
  };
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
  pageDetailsByPageId: Record<string, { html?: string; pageBundle?: DeckPageBundle }> = {},
): DeckPageData[] {
  return pages
    .map((page, index) => ({
      id: page.page_id || `page_${index + 1}`,
      pageIndex: typeof page.page_index === "number" ? page.page_index : index,
      title: page.title || `第 ${index + 1} 页`,
      kind: normalizePageKind(page.page_kind),
      status: normalizePageStatus(page.status),
      html: pageDetailsByPageId[page.page_id || ""]?.html,
      pageBundle:
        pageDetailsByPageId[page.page_id || ""]?.pageBundle
        || normalizePageBundle(page.page_bundle),
      lanes: (page.lanes || []).map((lane) => ({
        id: lane.lane_id || `${page.page_id || `page_${index + 1}`}_lane_${Math.random().toString(36).slice(2, 8)}`,
        laneKind: normalizeLaneKind(lane.kind),
        status: normalizeLaneStatus(lane.status),
        error: lane.error || undefined,
      })),
    }))
    .sort((left, right) => left.pageIndex - right.pageIndex);
}