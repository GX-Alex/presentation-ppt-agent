"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import PackageActivityPanel from "@/components/packages/PackageActivityPanel";
import PackageCard from "@/components/packages/PackageCard";
import PackageVersionCompareDialog from "@/components/packages/PackageVersionCompareDialog";
import { useToast } from "@/components/ui/Toast";
import {
  type InstalledPackageRecord,
  getInstalledPackages,
  matchesPackageSearch,
  rollbackInstalledPackage,
  toggleInstalledPackage,
  upgradeInstalledPackage,
} from "@/lib/packages";

interface InstalledPackagesPanelProps {
  search?: string;
  refreshKey?: number;
  variant?: "full" | "summary";
  onCountChange?: (count: number) => void;
}

interface CompareTarget {
  packageId: string;
  displayName: string;
  fromVersion: string;
  toVersion: string;
}

export default function InstalledPackagesPanel({
  search = "",
  refreshKey = 0,
  variant = "full",
  onCountChange,
}: InstalledPackagesPanelProps) {
  const toast = useToast();
  const [packages, setPackages] = useState<InstalledPackageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [compareTarget, setCompareTarget] = useState<CompareTarget | null>(null);

  const loadPackages = useCallback(async () => {
    try {
      setLoading(true);
      const items = await getInstalledPackages();
      setPackages(items);
      onCountChange?.(items.length);
    } catch (error) {
      console.error("[Packages] 加载已安装包失败:", error);
      toast.error("加载已安装包失败");
    } finally {
      setLoading(false);
    }
  }, [onCountChange, toast]);

  useEffect(() => {
    void loadPackages();
  }, [loadPackages, refreshKey]);

  const filteredPackages = useMemo(
    () => packages.filter((item) => matchesPackageSearch(item.manifest, search)),
    [packages, search],
  );

  const enabledCount = packages.filter((item) => item.is_enabled).length;

  const handleToggle = useCallback(
    async (item: InstalledPackageRecord, enabled: boolean) => {
      try {
        setBusyId(item.package_id);
        const updated = await toggleInstalledPackage(item.package_id, enabled);
        setPackages((current) =>
          current.map((pkg) => (pkg.package_id === updated.package_id ? updated : pkg)),
        );
        toast.success(enabled ? `已启用 ${item.display_name}` : `已禁用 ${item.display_name}`);
      } catch (error) {
        console.error("[Packages] 切换状态失败:", error);
        toast.error(error instanceof Error ? error.message : "切换包状态失败");
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
        await loadPackages();
        toast.success(`已升级 ${item.display_name} 到 v${item.latest_version}`);
      } catch (error) {
        console.error("[Packages] 升级失败:", error);
        toast.error(error instanceof Error ? error.message : "升级 Package 失败");
      } finally {
        setBusyId(null);
      }
    },
    [loadPackages, toast],
  );

  const handleRollback = useCallback(
    async (item: InstalledPackageRecord) => {
      try {
        setBusyId(item.package_id);
        await rollbackInstalledPackage(item.package_id);
        await loadPackages();
        toast.success(`已回滚 ${item.display_name} 到上一版本`);
      } catch (error) {
        console.error("[Packages] 回滚失败:", error);
        toast.error(error instanceof Error ? error.message : "回滚 Package 失败");
      } finally {
        setBusyId(null);
      }
    },
    [loadPackages, toast],
  );

  const buildCompareTarget = useCallback((item: InstalledPackageRecord): CompareTarget | null => {
    if (item.upgrade_available && item.latest_version && item.latest_version !== item.version) {
      return {
        packageId: item.package_id,
        displayName: item.display_name,
        fromVersion: item.version,
        toVersion: item.latest_version,
      };
    }

    if (item.previous_version && item.previous_version !== item.version) {
      return {
        packageId: item.package_id,
        displayName: item.display_name,
        fromVersion: item.previous_version,
        toVersion: item.version,
      };
    }

    return null;
  }, []);

  return (
    <>
      <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">已安装 Packages</h2>
          <p className="mt-1 text-sm text-gray-500">
            已安装 {packages.length} 个包，当前启用 {enabledCount} 个。
          </p>
        </div>
        <button
          onClick={() => void loadPackages()}
          className="inline-flex items-center gap-1.5 rounded-xl border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {loading ? (
        <div className="bento-card py-16 text-center text-gray-400">
          <RefreshCw className="mx-auto mb-3 w-8 h-8 animate-spin" />
          <p className="text-sm">正在加载已安装包...</p>
        </div>
      ) : filteredPackages.length === 0 ? (
        <div className="bento-card p-6 text-center">
          <p className="text-sm text-gray-500">
            {packages.length === 0 ? "当前还没有安装任何 Package。" : "没有匹配当前搜索条件的已安装 Package。"}
          </p>
          {packages.length === 0 ? (
            <Link
              href="/gallery"
              className="mt-4 inline-flex rounded-xl bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              去公共空间安装
            </Link>
          ) : null}
        </div>
      ) : variant === "summary" ? (
        <div className="space-y-3">
          {filteredPackages.map((item) => (
            <PackageCard
              key={item.package_id}
              manifest={item.manifest}
              installed={item}
              compact
              primaryAction={{
                label: item.is_enabled ? "禁用" : "启用",
                onClick: () => void handleToggle(item, !item.is_enabled),
                disabled: busyId === item.package_id,
                tone: item.is_enabled ? "ghost" : "primary",
                icon: "power",
              }}
              versionInfo={{
                latestVersion: item.latest_version,
                previousVersion: item.previous_version,
                availableVersions: item.available_versions,
                upgradeAvailable: item.upgrade_available,
              }}
              detailSlot={<PackageActivityPanel packageId={item.package_id} compact defaultOpen={false} />}
              footerActions={[
                ...(item.upgrade_available && item.latest_version && item.latest_version !== item.version
                  ? [
                      {
                        label: "一键升级",
                        onClick: () => void handleUpgrade(item),
                        disabled: busyId === item.package_id,
                        tone: "primary" as const,
                        icon: "refresh" as const,
                      },
                    ]
                  : []),
                ...(buildCompareTarget(item)
                  ? [
                      {
                        label:
                          item.upgrade_available && item.latest_version && item.latest_version !== item.version
                            ? "版本对比"
                            : "对比上版",
                        onClick: () => setCompareTarget(buildCompareTarget(item)),
                        tone: "neutral" as const,
                      },
                    ]
                  : []),
                ...(item.previous_version && item.previous_version !== item.version
                  ? [
                      {
                        label: "回滚",
                        onClick: () => void handleRollback(item),
                        disabled: busyId === item.package_id,
                        tone: "ghost" as const,
                      },
                    ]
                  : []),
              ]}
            />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {filteredPackages.map((item) => (
            <PackageCard
              key={item.package_id}
              manifest={item.manifest}
              installed={item}
              primaryAction={{
                label: item.is_enabled ? "禁用" : "启用",
                onClick: () => void handleToggle(item, !item.is_enabled),
                disabled: busyId === item.package_id,
                tone: item.is_enabled ? "ghost" : "primary",
                icon: "power",
              }}
              versionInfo={{
                latestVersion: item.latest_version,
                previousVersion: item.previous_version,
                availableVersions: item.available_versions,
                upgradeAvailable: item.upgrade_available,
              }}
              detailSlot={<PackageActivityPanel packageId={item.package_id} defaultOpen />}
              footerActions={[
                ...(item.upgrade_available && item.latest_version && item.latest_version !== item.version
                  ? [
                      {
                        label: "一键升级",
                        onClick: () => void handleUpgrade(item),
                        disabled: busyId === item.package_id,
                        tone: "primary" as const,
                        icon: "refresh" as const,
                      },
                    ]
                  : []),
                ...(buildCompareTarget(item)
                  ? [
                      {
                        label:
                          item.upgrade_available && item.latest_version && item.latest_version !== item.version
                            ? "版本对比"
                            : "对比上版",
                        onClick: () => setCompareTarget(buildCompareTarget(item)),
                        tone: "neutral" as const,
                      },
                    ]
                  : []),
                ...(item.previous_version && item.previous_version !== item.version
                  ? [
                      {
                        label: "回滚",
                        onClick: () => void handleRollback(item),
                        disabled: busyId === item.package_id,
                        tone: "ghost" as const,
                      },
                    ]
                  : []),
              ]}
            />
          ))}
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