"use client";

import { BrainCircuit, Boxes, Download, Palette, Power, RefreshCw, ShieldCheck, Wrench, Workflow } from "lucide-react";

import {
  type InstalledPackageRecord,
  type PackageKind,
  type PackageManifest,
  getPackageKindLabel,
  getPackageStatusLabel,
  getPackageStatusTone,
  getPermissionLabel,
} from "@/lib/packages";

type ActionTone = "primary" | "neutral" | "ghost";

interface PackageAction {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: ActionTone;
  icon?: "download" | "power" | "refresh";
}

interface PackageVersionInfo {
  latestVersion?: string | null;
  previousVersion?: string | null;
  availableVersions?: string[];
  upgradeAvailable?: boolean;
}

interface PackageCardProps {
  manifest: PackageManifest;
  installed?: InstalledPackageRecord | null;
  primaryAction?: PackageAction;
  footerActions?: PackageAction[];
  versionInfo?: PackageVersionInfo;
  compact?: boolean;
  detailSlot?: React.ReactNode;
}

function KindIcon({ kind, className }: { kind: PackageKind; className?: string }) {
  const cls = className || "w-4 h-4";

  switch (kind) {
    case "foundation":
      return <Boxes className={`${cls} text-slate-600`} />;
    case "workflow":
      return <Workflow className={`${cls} text-blue-600`} />;
    case "skill":
      return <BrainCircuit className={`${cls} text-violet-600`} />;
    case "theme":
      return <Palette className={`${cls} text-rose-600`} />;
    case "tool_adapter":
      return <Wrench className={`${cls} text-emerald-600`} />;
    default:
      return <Boxes className={`${cls} text-slate-600`} />;
  }
}

function ActionButton({ action }: { action: PackageAction }) {
  const tone = action.tone || "primary";
  const classes: Record<ActionTone, string> = {
    primary: "bg-primary-600 text-white hover:bg-primary-700 disabled:bg-primary-200 disabled:text-white/70",
    neutral: "bg-gray-900 text-white hover:bg-gray-800 disabled:bg-gray-200 disabled:text-gray-500",
    ghost: "bg-gray-100 text-gray-700 hover:bg-gray-200 disabled:bg-gray-100 disabled:text-gray-400",
  };
  const Icon =
    action.icon === "power"
      ? Power
      : action.icon === "download"
        ? Download
        : action.icon === "refresh"
          ? RefreshCw
          : null;

  return (
    <button
      onClick={action.onClick}
      disabled={action.disabled}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${classes[tone]}`}
    >
      {Icon ? <Icon className="h-3.5 w-3.5" /> : null}
      {action.label}
    </button>
  );
}

export default function PackageCard({
  manifest,
  installed,
  primaryAction,
  footerActions = [],
  versionInfo,
  compact = false,
  detailSlot,
}: PackageCardProps) {
  const permissions = installed?.granted_permissions?.length ? installed.granted_permissions : manifest.permissions;
  const dependencyCount = manifest.dependencies?.length || 0;
  const capabilityList = (manifest.capabilities || []).slice(0, compact ? 2 : 4);
  const hasVersionPanel = Boolean(
    versionInfo &&
      (versionInfo.latestVersion || versionInfo.previousVersion || versionInfo.availableVersions?.length),
  );

  return (
    <div className={`bento-card ${compact ? "p-4" : "p-5"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <KindIcon kind={manifest.kind} />
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-gray-600">
              {getPackageKindLabel(manifest.kind)}
            </span>
            <span className="font-mono text-[11px] text-gray-400">v{installed?.version || manifest.version}</span>
            {installed ? (
              <span className={`rounded-full px-2 py-0.5 ${getPackageStatusTone(installed)}`}>
                {getPackageStatusLabel(installed)}
              </span>
            ) : null}
          </div>

          <div className="mt-2">
            <h3 className="truncate text-sm font-semibold text-gray-900" title={manifest.display_name}>
              {manifest.display_name}
            </h3>
            <p className="mt-1 font-mono text-[11px] text-gray-400">{manifest.package_id}</p>
            <p className={`mt-2 text-sm leading-relaxed text-gray-600 ${compact ? "line-clamp-2" : "line-clamp-3"}`}>
              {manifest.description}
            </p>
          </div>
        </div>

        {primaryAction ? <ActionButton action={primaryAction} /> : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-2 text-xs text-gray-500">
        <span className="rounded-full bg-gray-50 px-2 py-1 ring-1 ring-gray-100">发布方: {manifest.publisher}</span>
        <span className="rounded-full bg-gray-50 px-2 py-1 ring-1 ring-gray-100">权限: {permissions.length}</span>
        <span className="rounded-full bg-gray-50 px-2 py-1 ring-1 ring-gray-100">依赖: {dependencyCount}</span>
        <span className="rounded-full bg-gray-50 px-2 py-1 ring-1 ring-gray-100">
          入口: {manifest.entrypoints?.length || 0}
        </span>
      </div>

      {hasVersionPanel ? (
        <div className="mt-3 rounded-xl border border-slate-100 bg-slate-50/80 p-3">
          <div className="flex flex-wrap gap-2 text-[11px] text-slate-600">
            <span className="rounded-full bg-white px-2 py-1 ring-1 ring-slate-200">
              当前: v{installed?.version || manifest.version}
            </span>
            {versionInfo?.upgradeAvailable && versionInfo.latestVersion ? (
              <span className="rounded-full bg-blue-50 px-2 py-1 text-blue-700 ring-1 ring-blue-100">
                可升级到: v{versionInfo.latestVersion}
              </span>
            ) : null}
            {versionInfo?.previousVersion ? (
              <span className="rounded-full bg-amber-50 px-2 py-1 text-amber-700 ring-1 ring-amber-100">
                可回滚到: v{versionInfo.previousVersion}
              </span>
            ) : null}
          </div>
          {versionInfo?.availableVersions?.length ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {versionInfo.availableVersions.slice(0, compact ? 3 : 5).map((version) => (
                <span
                  key={`${manifest.package_id}-${version}`}
                  className="rounded-full bg-white px-2 py-1 text-[11px] text-slate-600 ring-1 ring-slate-200"
                >
                  v{version}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {capabilityList.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {capabilityList.map((capability) => (
            <span key={capability} className="rounded-full bg-primary-50 px-2 py-1 text-[11px] text-primary-700">
              {capability}
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50/70 p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-gray-500">
          <ShieldCheck className="h-3.5 w-3.5" />
          权限
        </div>
        <div className="flex flex-wrap gap-2">
          {permissions.length > 0 ? (
            permissions.map((permission) => (
              <span
                key={`${manifest.package_id}-${permission.name}`}
                title={permission.rationale}
                className="rounded-full bg-white px-2 py-1 text-[11px] text-gray-700 ring-1 ring-gray-200"
              >
                {getPermissionLabel(permission.name)}
              </span>
            ))
          ) : (
            <span className="text-xs text-gray-400">无额外权限</span>
          )}
        </div>
      </div>

      {footerActions.length > 0 || manifest.dependencies.length > 0 ? (
        <div className="mt-4 flex items-center justify-between gap-3 border-t border-gray-100 pt-3">
          <div className="min-w-0 text-xs text-gray-400">
            {manifest.dependencies.length > 0
              ? `依赖: ${manifest.dependencies.map((dep) => dep.package_id).join(" · ")}`
              : "无强制依赖"}
          </div>
          {footerActions.length > 0 ? (
            <div className="flex flex-wrap items-center justify-end gap-2">
              {footerActions.map((action) => (
                <ActionButton key={`${manifest.package_id}-${action.label}`} action={action} />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {detailSlot ? detailSlot : null}
    </div>
  );
}
