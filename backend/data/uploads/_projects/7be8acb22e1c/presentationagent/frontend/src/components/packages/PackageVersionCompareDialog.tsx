"use client";

import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";

import {
  comparePackageVersions,
  type PackageDependency,
  type PackagePermission,
  type PackageVersionCompareResult,
} from "@/lib/packages";

interface PackageVersionCompareDialogProps {
  open: boolean;
  packageId: string | null;
  displayName: string | null;
  fromVersion: string | null;
  toVersion: string | null;
  onClose: () => void;
}

function PermissionPills({ items }: { items: PackagePermission[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">无</p>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span
          key={`${item.name}-${item.rationale}`}
          title={item.rationale}
          className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-700 ring-1 ring-gray-200"
        >
          {item.name}
        </span>
      ))}
    </div>
  );
}

function DependencyPills({ items }: { items: PackageDependency[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">无</p>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span
          key={`${item.package_id}-${item.version_constraint}`}
          className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-700 ring-1 ring-gray-200"
        >
          {item.package_id} {item.version_constraint}
        </span>
      ))}
    </div>
  );
}

function StringPills({ items }: { items: string[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-gray-400">无</p>;
  }

  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span key={item} className="rounded-full bg-white px-2.5 py-1 text-xs text-gray-700 ring-1 ring-gray-200">
          {item}
        </span>
      ))}
    </div>
  );
}

export default function PackageVersionCompareDialog({
  open,
  packageId,
  displayName,
  fromVersion,
  toVersion,
  onClose,
}: PackageVersionCompareDialogProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PackageVersionCompareResult | null>(null);

  useEffect(() => {
    if (!open || !packageId || !fromVersion || !toVersion) {
      setResult(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;

    const loadCompare = async () => {
      try {
        setLoading(true);
        setError(null);
        const data = await comparePackageVersions(packageId, fromVersion, toVersion);
        if (!cancelled) {
          setResult(data);
        }
      } catch (fetchError) {
        if (!cancelled) {
          setError(fetchError instanceof Error ? fetchError.message : "版本对比加载失败");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadCompare();
    return () => {
      cancelled = true;
    };
  }, [fromVersion, open, packageId, toVersion]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-3xl overflow-hidden rounded-[28px] border border-white/60 bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-gray-100 px-6 py-5">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-400">版本对比</p>
            <h2 className="mt-1 text-xl font-semibold text-gray-900">{displayName || packageId}</h2>
            <p className="mt-2 text-sm text-gray-500">
              {fromVersion ? `v${fromVersion}` : "-"} → {toVersion ? `v${toVersion}` : "-"}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700"
            title="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="max-h-[75vh] overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center gap-3 py-20 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载版本差异...
            </div>
          ) : error ? (
            <div className="rounded-2xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          ) : result ? (
            <div className="space-y-5">
              <div className="rounded-2xl border border-blue-100 bg-blue-50/80 p-4">
                <p className="text-sm font-medium text-blue-900">
                  {result.direction === "rollback" ? "回滚差异" : result.direction === "same" ? "相同版本" : "升级差异"}
                </p>
                <p className="mt-2 text-sm text-blue-800">{result.release_notes || "此版本没有额外发布说明。"}</p>
                {result.upgrade_notes ? <p className="mt-2 text-sm text-blue-700">升级提示: {result.upgrade_notes}</p> : null}
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">新增能力</h3>
                  <div className="mt-3">
                    <StringPills items={result.added_capabilities} />
                  </div>
                </section>
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">移除能力</h3>
                  <div className="mt-3">
                    <StringPills items={result.removed_capabilities} />
                  </div>
                </section>
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">新增权限</h3>
                  <div className="mt-3">
                    <PermissionPills items={result.added_permissions} />
                  </div>
                </section>
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">移除权限</h3>
                  <div className="mt-3">
                    <PermissionPills items={result.removed_permissions} />
                  </div>
                </section>
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">新增依赖</h3>
                  <div className="mt-3">
                    <DependencyPills items={result.added_dependencies} />
                  </div>
                </section>
                <section className="rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
                  <h3 className="text-sm font-semibold text-gray-900">移除依赖</h3>
                  <div className="mt-3">
                    <DependencyPills items={result.removed_dependencies} />
                  </div>
                </section>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}