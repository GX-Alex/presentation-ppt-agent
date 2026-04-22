export type PackageKind = "foundation" | "workflow" | "skill" | "theme" | "tool_adapter";

export interface PackagePermission {
  name: string;
  rationale: string;
}

export interface PackageDependency {
  package_id: string;
  version_constraint: string;
  optional?: boolean;
}

export interface PackageEntrypoint {
  kind: "workflow" | "skill_set" | "theme_bundle" | "adapter";
  target: string;
  description: string;
}

export interface PackageCompatibility {
  min_platform_version: string;
  target_artifact_mode: Array<"native_pptx_first" | "dual_render">;
}

export interface InstalledPackageHistoryEntry {
  version: string;
  changed_at?: string | null;
  action: string;
}

export interface PackageVersionSummary {
  version: string;
  display_name: string;
  description: string;
  release_notes: string;
  release_date?: string | null;
  is_latest: boolean;
  capability_count: number;
  permission_count: number;
  dependency_count: number;
}

export interface PackageVersionCompareResult {
  package_id: string;
  from_version: string;
  to_version: string;
  direction: "upgrade" | "rollback" | "same";
  from_manifest: PackageManifest;
  to_manifest: PackageManifest;
  added_capabilities: string[];
  removed_capabilities: string[];
  added_permissions: PackagePermission[];
  removed_permissions: PackagePermission[];
  added_dependencies: PackageDependency[];
  removed_dependencies: PackageDependency[];
  release_notes?: string;
  upgrade_notes?: string;
}

export interface PackageManifest {
  schema_version: string;
  package_id: string;
  display_name: string;
  kind: PackageKind;
  version: string;
  description: string;
  publisher: string;
  tags: string[];
  capabilities: string[];
  permissions: PackagePermission[];
  dependencies: PackageDependency[];
  compatibility: PackageCompatibility;
  entrypoints: PackageEntrypoint[];
  metadata?: Record<string, string>;
}

export interface PackageImportResult {
  source_id: string;
  source_ref?: string;
  package_ids: string[];
  versions: string[];
  latest_manifest?: PackageManifest | null;
}

export interface PackageImportRequest {
  source_id?: string;
  owner?: string;
  repo?: string;
  ref?: string;
  plugin_path?: string;
  package_id?: string;
  package_kind?: "workflow" | "tool_adapter";
  related_skill_path?: string;
  adapter_targets?: string[];
}

export interface ExportFormatCapability {
  available: boolean;
  reason?: string | null;
}

export interface ExportCapabilitiesResponse {
  formats: Record<string, ExportFormatCapability>;
}

export interface PackageExecutionLogRecord {
  id: string;
  package_id: string;
  package_version?: string | null;
  execution_kind: string;
  target_type?: string | null;
  target_id?: string | null;
  status: string;
  duration_ms?: number | null;
  error_message?: string | null;
  input_payload?: Record<string, unknown> | null;
  output_payload?: Record<string, unknown> | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ArtifactVariantRecord {
  id: string;
  variant_key: string;
  package_id: string;
  package_version?: string | null;
  variant_type: string;
  presentation_id?: string | null;
  asset_id?: string | null;
  file_url?: string | null;
  mime_type?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface InstalledPackageRecord {
  id: string;
  package_id: string;
  display_name: string;
  package_kind: PackageKind;
  version: string;
  source: string;
  manifest: PackageManifest;
  granted_permissions: PackagePermission[];
  status: string;
  is_enabled: boolean;
  installed_at?: string | null;
  updated_at?: string | null;
  latest_version?: string | null;
  previous_version?: string | null;
  available_versions?: string[];
  upgrade_available?: boolean;
  installed_history?: InstalledPackageHistoryEntry[];
  release_notes?: string | null;
  latest_release_notes?: string | null;
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      detail = data.detail || data.message || detail;
    } catch {
      // ignore json parse failures
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function getRegistryPackages(): Promise<PackageManifest[]> {
  const data = await fetchJson<{ items: PackageManifest[] }>("/api/packages/registry");
  return data.items || [];
}

export async function getRegistryPackageVersions(packageId: string): Promise<PackageVersionSummary[]> {
  const data = await fetchJson<{ versions: PackageVersionSummary[] }>(`/api/packages/registry/${packageId}/versions`);
  return data.versions || [];
}

export async function getInstalledPackages(): Promise<InstalledPackageRecord[]> {
  const data = await fetchJson<{ items: InstalledPackageRecord[] }>("/api/packages/installed");
  return data.items || [];
}

export async function installRegistryPackage(
  packageId: string,
  version?: string,
): Promise<InstalledPackageRecord[]> {
  const data = await fetchJson<{ installed_packages: InstalledPackageRecord[] }>("/api/packages/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ package_id: packageId, version }),
  });
  return data.installed_packages || [];
}

export async function importPackageSource(request: string | PackageImportRequest): Promise<PackageImportResult> {
  const payload = typeof request === "string" ? { source_id: request } : request;
  return fetchJson<PackageImportResult>("/api/packages/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function upgradeInstalledPackage(
  packageId: string,
  targetVersion?: string,
): Promise<InstalledPackageRecord[]> {
  const data = await fetchJson<{ updated_packages: InstalledPackageRecord[] }>(`/api/packages/${packageId}/upgrade`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_version: targetVersion }),
  });
  return data.updated_packages || [];
}

export async function rollbackInstalledPackage(packageId: string): Promise<InstalledPackageRecord[]> {
  const data = await fetchJson<{ updated_packages: InstalledPackageRecord[] }>(`/api/packages/${packageId}/rollback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  return data.updated_packages || [];
}

export async function comparePackageVersions(
  packageId: string,
  fromVersion: string,
  toVersion: string,
): Promise<PackageVersionCompareResult> {
  const params = new URLSearchParams({ from_version: fromVersion, to_version: toVersion });
  return fetchJson<PackageVersionCompareResult>(`/api/packages/${packageId}/compare?${params.toString()}`);
}

export async function toggleInstalledPackage(
  packageId: string,
  enabled: boolean,
): Promise<InstalledPackageRecord> {
  const data = await fetchJson<{ item: InstalledPackageRecord }>(`/api/packages/${packageId}/toggle`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  return data.item;
}

export async function getPackageExecutionLogs(
  packageId: string,
  options?: { status?: string; limit?: number },
): Promise<PackageExecutionLogRecord[]> {
  const params = new URLSearchParams({ package_id: packageId });
  if (options?.status) params.set("status", options.status);
  if (options?.limit) params.set("limit", String(options.limit));
  const data = await fetchJson<{ items: PackageExecutionLogRecord[] }>(
    `/api/packages/execution-logs?${params.toString()}`,
  );
  return data.items || [];
}

export async function getPackageArtifactVariants(
  packageId: string,
  options?: { presentationId?: string; assetId?: string },
): Promise<ArtifactVariantRecord[]> {
  const params = new URLSearchParams({ package_id: packageId });
  if (options?.presentationId) params.set("presentation_id", options.presentationId);
  if (options?.assetId) params.set("asset_id", options.assetId);
  const data = await fetchJson<{ items: ArtifactVariantRecord[] }>(
    `/api/packages/artifact-variants?${params.toString()}`,
  );
  return data.items || [];
}

export function getPackageKindLabel(kind: PackageKind): string {
  const labels: Record<PackageKind, string> = {
    foundation: "基础契约",
    workflow: "工作流",
    skill: "Skill 包",
    theme: "主题包",
    tool_adapter: "工具适配器",
  };
  return labels[kind] || kind;
}

export function getPermissionLabel(name: string): string {
  const labels: Record<string, string> = {
    "asset.read": "读公共空间",
    "asset.write": "写公共空间",
    "document.parse": "解析文档",
    "model.invoke": "调用模型",
    "pptx.render": "渲染 PPTX",
    "preview.render": "渲染预览",
    "registry.read": "读注册表",
    "settings.write": "改设置",
    "web.fetch": "联网访问",
  };
  return labels[name] || name;
}

export function getPackageStatusLabel(item: InstalledPackageRecord): string {
  if (!item.is_enabled) return "已禁用";
  if (item.status === "rolled_back") return "已回滚";
  if (item.status === "upgraded") return "已升级";
  return "已启用";
}

export function getPackageStatusTone(item: InstalledPackageRecord): string {
  if (!item.is_enabled) return "bg-gray-100 text-gray-600";
  if (item.status === "rolled_back") return "bg-amber-50 text-amber-700";
  if (item.status === "upgraded") return "bg-blue-50 text-blue-700";
  return "bg-green-50 text-green-700";
}

export function matchesPackageSearch(manifest: PackageManifest, searchTerm: string): boolean {
  const keyword = searchTerm.trim().toLowerCase();
  if (!keyword) return true;

  const haystacks = [
    manifest.package_id,
    manifest.display_name,
    manifest.description,
    manifest.publisher,
    ...manifest.tags,
    ...manifest.capabilities,
  ];
  return haystacks.some((value) => value?.toLowerCase().includes(keyword));
}

export function normalizePackageFileUrl(url?: string | null): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/")) return url;
  return `/${url}`;
}