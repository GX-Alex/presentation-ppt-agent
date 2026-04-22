"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import PackageCard from "@/components/packages/PackageCard";
import PackageVersionCompareDialog from "@/components/packages/PackageVersionCompareDialog";
import { useToast } from "@/components/ui/Toast";
import {
  type InstalledPackageRecord,
  type PackageManifest,
  type PackageKind,
  getInstalledPackages,
  getRegistryPackages,
  importPackageSource,
  installRegistryPackage,
  matchesPackageSearch,
  toggleInstalledPackage,
  upgradeInstalledPackage,
} from "@/lib/packages";

interface PackageRegistryPanelProps {
  search?: string;
  refreshKey?: number;
}

interface CompareTarget {
  packageId: string;
  displayName: string;
  fromVersion: string;
  toVersion: string;
}

interface CustomImportForm {
  owner: string;
  repo: string;
  ref: string;
  pluginPath: string;
  packageId: string;
  packageKind: Extract<PackageKind, "workflow" | "tool_adapter">;
  relatedSkillPath: string;
  adapterTargets: string;
}

export default function PackageRegistryPanel({
  search = "",
  refreshKey = 0,
}: PackageRegistryPanelProps) {
  const [customImport, setCustomImport] = useState<CustomImportForm>({
    owner: "",
    repo: "",
    ref: "main",
    pluginPath: "",
    packageId: "",
    packageKind: "workflow",
    relatedSkillPath: "",
    adapterTargets: "",
  });
  const toast = useToast();
  const [registryItems, setRegistryItems] = useState<PackageManifest[]>([]);
  const [installedItems, setInstalledItems] = useState<InstalledPackageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [compareTarget, setCompareTarget] = useState<CompareTarget | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [registry, installed] = await Promise.all([
        getRegistryPackages(),
        getInstalledPackages(),
      ]);
      setRegistryItems(registry);
      setInstalledItems(installed);
    } catch (error) {
      console.error("[Packages] 加载注册表失败:", error);
      toast.error("加载 Package 注册表失败");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void loadData();
  }, [loadData, refreshKey]);

  const installedMap = useMemo(
    () => new Map(installedItems.map((item) => [item.package_id, item])),
    [installedItems],
  );

  const filteredItems = useMemo(
    () => registryItems.filter((item) => matchesPackageSearch(item, search)),
    [registryItems, search],
  );

  const handleInstall = useCallback(
    async (packageId: string) => {
      try {
        setBusyId(packageId);
        const installed = await installRegistryPackage(packageId);
        const refreshed = await getInstalledPackages();
        setInstalledItems(refreshed);
        toast.success(`已安装 ${installed.length} 个相关 Package`);
      } catch (error) {
        console.error("[Packages] 安装失败:", error);
        toast.error(error instanceof Error ? error.message : "安装 Package 失败");
      } finally {
        setBusyId(null);
      }
    },
    [toast],
  );

  const handleEnable = useCallback(
    async (packageId: string) => {
      try {
        setBusyId(packageId);
        const updated = await toggleInstalledPackage(packageId, true);
        setInstalledItems((current) =>
          current.map((item) => (item.package_id === updated.package_id ? updated : item)),
        );
        toast.success(`已启用 ${updated.display_name}`);
      } catch (error) {
        console.error("[Packages] 启用失败:", error);
        toast.error(error instanceof Error ? error.message : "启用 Package 失败");
      } finally {
        setBusyId(null);
      }
    },
    [toast],
  );

  const handleUpgrade = useCallback(
    async (item: InstalledPackageRecord) => {
      try {
        setBusyId(item.package_id);
        await upgradeInstalledPackage(item.package_id);
        await loadData();
        toast.success(`已升级 ${item.display_name} 到 v${item.latest_version}`);
      } catch (error) {
        console.error("[Packages] 升级失败:", error);
        toast.error(error instanceof Error ? error.message : "升级 Package 失败");
      } finally {
        setBusyId(null);
      }
    },
    [loadData, toast],
  );

  const handleRemoteImport = useCallback(async () => {
    const sourceId = "minimax.pptx-plugin";
    try {
      setBusyId(sourceId);
      const result = await importPackageSource(sourceId);
      await loadData();
      const importedVersion = result.versions[0] || result.latest_manifest?.version || "最新版本";
      toast.success(`已从 MiniMax 官方源导入 ${importedVersion}`);
    } catch (error) {
      console.error("[Packages] 远端导入失败:", error);
      toast.error(error instanceof Error ? error.message : "远端包源导入失败");
    } finally {
      setBusyId(null);
    }
  }, [loadData, toast]);

  const handleCustomImport = useCallback(async () => {
    if (!customImport.owner.trim() || !customImport.repo.trim() || !customImport.pluginPath.trim()) {
      toast.warning("请至少填写 owner、repo 和 plugin path");
      return;
    }

    const sourceId = `custom:${customImport.owner}/${customImport.repo}/${customImport.pluginPath}`;
    try {
      setBusyId(sourceId);
      const result = await importPackageSource({
        owner: customImport.owner.trim(),
        repo: customImport.repo.trim(),
        ref: customImport.ref.trim() || "main",
        plugin_path: customImport.pluginPath.trim(),
        package_id: customImport.packageId.trim() || undefined,
        package_kind: customImport.packageKind,
        related_skill_path:
          customImport.packageKind === "workflow" && customImport.relatedSkillPath.trim()
            ? customImport.relatedSkillPath.trim()
            : undefined,
        adapter_targets:
          customImport.packageKind === "tool_adapter"
            ? customImport.adapterTargets
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean)
            : undefined,
      });
      await loadData();
      const importedVersion = result.versions[0] || result.latest_manifest?.version || "最新版本";
      toast.success(`已导入 ${result.package_ids[0] || "远端包"} ${importedVersion}`);
    } catch (error) {
      console.error("[Packages] 自定义 GitHub 导入失败:", error);
      toast.error(error instanceof Error ? error.message : "自定义 GitHub 导入失败");
    } finally {
      setBusyId(null);
    }
  }, [customImport, loadData, toast]);

  return (
    <>
      <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Package Registry</h2>
          <p className="mt-1 text-sm text-gray-500">
            浏览官方与兼容包，安装后可在公共空间页启停和查看权限。
          </p>
        </div>
        <button
          onClick={() => void loadData()}
          className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      <div className="rounded-2xl border border-blue-100 bg-gradient-to-br from-blue-50 via-cyan-50 to-white p-4 shadow-sm shadow-blue-100/40">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-900">远端包源导入</p>
            <p className="mt-1 text-sm text-slate-600">
              直接从 MiniMax 官方 GitHub 仓库导入最新的 PPTX plugin 元数据、skills 和 agents。
            </p>
            <p className="mt-2 font-mono text-[11px] text-slate-500">
              MiniMax-AI/skills/plugins/pptx-plugin
            </p>
          </div>
          <button
            onClick={() => void handleRemoteImport()}
            disabled={busyId === "minimax.pptx-plugin"}
            className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busyId === "minimax.pptx-plugin" ? "导入中..." : "导入 MiniMax 官方源"}
          </button>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-sm font-semibold text-slate-900">自定义 GitHub 导入</p>
            <p className="mt-1 text-sm text-slate-600">
              适用于带有 .claude-plugin 配置的开源插件仓库。工作流包填写 plugin 目录；工具适配器额外填写 adapter target。
            </p>
          </div>
          <div className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
            支持 workflow / tool_adapter
          </div>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          <label className="text-xs text-slate-600">
            GitHub Owner
            <input
              value={customImport.owner}
              onChange={(e) => setCustomImport((current) => ({ ...current, owner: e.target.value }))}
              placeholder="MiniMax-AI"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            />
          </label>
          <label className="text-xs text-slate-600">
            Repo
            <input
              value={customImport.repo}
              onChange={(e) => setCustomImport((current) => ({ ...current, repo: e.target.value }))}
              placeholder="skills"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            />
          </label>
          <label className="text-xs text-slate-600">
            Ref
            <input
              value={customImport.ref}
              onChange={(e) => setCustomImport((current) => ({ ...current, ref: e.target.value }))}
              placeholder="main"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            />
          </label>
          <label className="text-xs text-slate-600 md:col-span-2 xl:col-span-1">
            Plugin Path
            <input
              value={customImport.pluginPath}
              onChange={(e) => setCustomImport((current) => ({ ...current, pluginPath: e.target.value }))}
              placeholder="plugins/pptx-plugin"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            />
          </label>
          <label className="text-xs text-slate-600">
            Package Kind
            <select
              value={customImport.packageKind}
              onChange={(e) =>
                setCustomImport((current) => ({
                  ...current,
                  packageKind: e.target.value as CustomImportForm["packageKind"],
                }))
              }
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            >
              <option value="workflow">workflow</option>
              <option value="tool_adapter">tool_adapter</option>
            </select>
          </label>
          <label className="text-xs text-slate-600">
            Package ID
            <input
              value={customImport.packageId}
              onChange={(e) => setCustomImport((current) => ({ ...current, packageId: e.target.value }))}
              placeholder="可选，留空自动生成"
              className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
            />
          </label>
          {customImport.packageKind === "workflow" ? (
            <label className="text-xs text-slate-600 md:col-span-2 xl:col-span-3">
              Related Skill Path
              <input
                value={customImport.relatedSkillPath}
                onChange={(e) => setCustomImport((current) => ({ ...current, relatedSkillPath: e.target.value }))}
                placeholder="可选，例如 skills/pptx-generator"
                className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
              />
            </label>
          ) : (
            <label className="text-xs text-slate-600 md:col-span-2 xl:col-span-3">
              Adapter Targets
              <input
                value={customImport.adapterTargets}
                onChange={(e) => setCustomImport((current) => ({ ...current, adapterTargets: e.target.value }))}
                placeholder="deckspec.v1, render.native_pptx"
                className="mt-1 w-full rounded-xl border border-slate-200 px-3 py-2 text-sm text-slate-900 outline-none focus:border-slate-400"
              />
            </label>
          )}
        </div>

        <div className="mt-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <p className="text-xs text-slate-500">
            目录下需包含 .claude-plugin/plugin.json 或 marketplace.json；tool_adapter 还需要能推导 entrypoints 或 llm_tools。
          </p>
          <button
            onClick={() => void handleCustomImport()}
            disabled={busyId === `custom:${customImport.owner}/${customImport.repo}/${customImport.pluginPath}`}
            className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {busyId === `custom:${customImport.owner}/${customImport.repo}/${customImport.pluginPath}`
              ? "导入中..."
              : "导入 GitHub 包"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="bento-card py-16 text-center text-gray-400">
          <RefreshCw className="mx-auto mb-3 w-8 h-8 animate-spin" />
          <p className="text-sm">正在加载 Package 注册表...</p>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="bento-card p-6 text-center text-sm text-gray-500">
          没有匹配当前搜索条件的 Package。
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {filteredItems.map((manifest) => {
            const installed = installedMap.get(manifest.package_id) || null;
            const isBusy = busyId === manifest.package_id;

            const primaryAction = !installed
              ? {
                  label: "安装",
                  onClick: () => void handleInstall(manifest.package_id),
                  disabled: isBusy,
                  tone: "primary" as const,
                  icon: "download" as const,
                }
              : installed.upgrade_available && installed.latest_version && installed.latest_version !== installed.version
                ? {
                    label: "一键升级",
                    onClick: () => void handleUpgrade(installed),
                    disabled: isBusy,
                    tone: "primary" as const,
                    icon: "refresh" as const,
                  }
              : installed.is_enabled
                ? {
                    label: "已是最新",
                    onClick: () => undefined,
                    disabled: true,
                    tone: "ghost" as const,
                    icon: "power" as const,
                  }
                : {
                    label: "启用",
                    onClick: () => void handleEnable(manifest.package_id),
                    disabled: isBusy,
                    tone: "neutral" as const,
                    icon: "power" as const,
                  };

            return (
              <PackageCard
                key={manifest.package_id}
                manifest={manifest}
                installed={installed}
                primaryAction={primaryAction}
                versionInfo={{
                  latestVersion: installed?.latest_version || manifest.version,
                  previousVersion: installed?.previous_version,
                  availableVersions: installed?.available_versions,
                  upgradeAvailable: installed?.upgrade_available,
                }}
                footerActions={
                  installed && installed.latest_version && installed.latest_version !== installed.version
                    ? [
                        {
                          label: "版本对比",
                          onClick: () =>
                            setCompareTarget({
                              packageId: manifest.package_id,
                              displayName: manifest.display_name,
                              fromVersion: installed.version,
                              toVersion: installed.latest_version || manifest.version,
                            }),
                          tone: "neutral" as const,
                        },
                      ]
                    : []
                }
              />
            );
          })}
        </div>
      )}
      </div>

      <PackageVersionCompareDialog
        open={!!compareTarget}
        packageId={compareTarget?.packageId || null}
        displayName={compareTarget?.displayName || null}
        fromVersion={compareTarget?.fromVersion || null}
        toVersion={compareTarget?.toVersion || null}
        onClose={() => setCompareTarget(null)}
      />
    </>
  );
}