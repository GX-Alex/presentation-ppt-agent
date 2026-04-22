/**
 * Assets page — 资产管理 + Skill 管理。
 * Route: /assets
 * Sprint 6: 完整资产列表/筛选/搜索/卡片 + Skill Tab。
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Trash2,
  Share2,
  Search,
  RefreshCw,
  Inbox,
} from "lucide-react";
import InstalledPackagesPanel from "@/components/packages/InstalledPackagesPanel";
import SkillManager from "@/components/skills/SkillManager";
import { useToast, ConfirmDialog } from "@/components/ui/Toast";
import AppImage from "@/components/ui/AppImage";
import AssetPreviewModal, { type PreviewAssetItem } from "@/components/assets/AssetPreviewModal";
import { AssetKindIcon } from "@/components/assets/AssetKindIcon";
import {
  getAssetKindLabel,
  resolveAssetKind,
  resolveAssetPreviewImageUrl,
  resolveGalleryCategory,
} from "@/lib/assetTypes";

// ────── 类型定义 ──────

interface AssetItem {
  id: string;
  title: string;
  file_type: string;
  source: string;
  mime_type: string | null;
  file_url: string | null;
  thumbnail_url: string | null;
  file_size: number | null;
  task_id: string | null;
  created_at: string;
  updated_at: string;
}

interface AssetStats {
  [key: string]: number;
}

// ────── 辅助函数 ──────

/** 文件大小格式化 */
function formatSize(bytes: number | null): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

/** 日期格式化 */
function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ────── Tab 配置 ──────

const tabs = ["全部", "文档", "PPT", "代码", "图片", "📦 Packages", "🔌 Skill"];
const tabToType: Record<number, string | null> = {
  0: null,
  1: "document",
  2: "ppt",
  3: "code",
  4: "image",
  5: null,
  6: null,
};

// ────── 主组件 ──────

export default function AssetsPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState(0);
  const [assets, setAssets] = useState<AssetItem[]>([]);
  const [stats, setStats] = useState<AssetStats>({});
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [packageRefreshKey, setPackageRefreshKey] = useState(0);
  const [installedPackageCount, setInstalledPackageCount] = useState(0);
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; assetId: string | null }>({
    open: false,
    assetId: null,
  });
  const [previewAsset, setPreviewAsset] = useState<PreviewAssetItem | null>(null);

  // 加载资产列表
  const loadAssets = useCallback(async () => {
    if (activeTab >= 5) return; // Packages / Skill tab 不走此逻辑
    setLoading(true);
    try {
      const params = new URLSearchParams();
      const fileType = tabToType[activeTab];
      if (fileType) params.set("file_type", fileType);
      if (search.trim()) params.set("search", search.trim());
      params.set("page", String(page));
      params.set("page_size", "20");

      const res = await fetch(`/api/assets/?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setAssets(data.assets || []);
        setTotal(data.total || 0);
      } else {
        toast.error("加载资产列表失败，请稍后重试");
      }
    } catch (err) {
      console.error("[Assets] 加载失败:", err);
      toast.error("网络错误，请检查连接后重试");
    } finally {
      setLoading(false);
    }
  }, [activeTab, search, page, toast]);

  // 加载统计数据
  const loadStats = useCallback(async () => {
    try {
      const [assetRes, packagesRes] = await Promise.all([
        fetch("/api/assets/stats"),
        fetch("/api/packages/installed"),
      ]);

      if (assetRes.ok) {
        const data = await assetRes.json();
        setStats(data.by_type || data.stats || {});
      }

      if (packagesRes.ok) {
        const packageData = await packagesRes.json();
        setInstalledPackageCount((packageData.items || []).length);
      }
    } catch (err) {
      console.error("[Assets] 加载统计失败:", err);
    }
  }, []);

  useEffect(() => {
    loadAssets();
  }, [loadAssets]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // 切换 tab 时重置分页
  const handleTabChange = (i: number) => {
    setActiveTab(i);
    setPage(1);
  };

  const searchPlaceholder =
    activeTab === 5
      ? "搜索已安装 Packages..."
      : activeTab === 6
        ? "搜索 Skill..."
        : "搜索资产...";

  // 删除资产
  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleteConfirm({ open: true, assetId: id });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm.assetId) return;
    try {
      const res = await fetch(`/api/assets/${deleteConfirm.assetId}`, { method: "DELETE" });
      if (res.ok) {
        toast.success("资产文件已删除");
        loadAssets();
        loadStats();
      } else {
        toast.error("删除失败，请稍后重试");
      }
    } catch (err) {
      console.error("[Assets] 删除失败:", err);
      toast.error("网络错误，删除失败");
    } finally {
      setDeleteConfirm({ open: false, assetId: null });
    }
  };

  // 发布到公共空间
  const handlePublish = async (asset: AssetItem, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch("/api/gallery/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: asset.id,
          title: asset.title,
          category: resolveGalleryCategory(asset),
        }),
      });
      if (res.ok) {
        toast.success("已发布到公共空间！其他用户现在可以看到你的作品了");
      } else {
        const data = await res.json().catch(() => ({}));
        toast.error(data.detail || "发布失败，请稍后重试");
      }
    } catch (err) {
      console.error("[Assets] 发布失败:", err);
      toast.error("网络错误，发布失败");
    }
  };

  // 卡片点击 — 优先使用站内预览，避免直接访问 /static 导致的跳转问题
  const handleCardClick = (asset: AssetItem) => {
    const displayKind = resolveAssetKind(asset);
    setPreviewAsset({
      id: asset.id,
      title: asset.title,
      fileType: displayKind,
      mimeType: asset.mime_type,
      fileUrl: asset.file_url,
      thumbnailUrl: asset.thumbnail_url,
      taskId: asset.task_id,
      sourceLabel: asset.source,
    });
  };

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="p-6 h-full overflow-y-auto">
      {/* 标题 + 搜索 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">资产</h1>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder={searchPlaceholder}
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
              className="pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl w-64 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          </div>
          <button
            onClick={() => {
              if (activeTab === 5) {
                setPackageRefreshKey((prev) => prev + 1);
                void loadStats();
                return;
              }
              void loadAssets();
              void loadStats();
            }}
            className="p-2.5 text-gray-500 hover:text-gray-700 rounded-xl hover:bg-gray-100 transition-colors"
            title="刷新"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Tabs（含统计徽标） */}
      <div className="flex gap-1 mb-6 p-1 bg-gray-100 rounded-xl w-fit">
        {tabs.map((tab, i) => {
          const fileType = tabToType[i];
          const count = i === 0
            ? Object.values(stats).reduce((s, n) => s + n, 0)
            : i === 5
              ? installedPackageCount
              : fileType
                ? stats[fileType] || 0
                : null;

          return (
            <button
              key={tab}
              onClick={() => handleTabChange(i)}
              className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-all flex items-center gap-1.5 ${
                i === activeTab
                  ? "bg-white text-primary-600 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab}
              {count !== null && count > 0 && (
                <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                  i === activeTab ? "bg-primary-50 text-primary-600" : "bg-gray-200 text-gray-500"
                }`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Tab 内容 */}
      {activeTab === 5 ? (
        <InstalledPackagesPanel
          search={search}
          refreshKey={packageRefreshKey}
          variant="full"
          onCountChange={setInstalledPackageCount}
        />
      ) : activeTab === 6 ? (
        <SkillManager />
      ) : loading ? (
        <div className="text-center py-20 text-gray-400">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3" />
          <p className="text-sm">加载中...</p>
        </div>
      ) : assets.length === 0 ? (
        <div className="text-center py-20">
          <Inbox className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium text-gray-500 mb-2">资产为空</p>
          <p className="text-sm text-gray-400 max-w-sm mx-auto">
            上传文件或生成内容后，文件会自动沉淀到资产库
          </p>
        </div>
      ) : (
        <>
          {/* 资产卡片网格 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {assets.map((asset) => (
              (() => {
                const previewImageUrl = resolveAssetPreviewImageUrl(asset);
                const displayKind = resolveAssetKind(asset);
                const displayLabel = getAssetKindLabel(displayKind);

                return (
              <div
                key={asset.id}
                onClick={() => handleCardClick(asset)}
                className="bento-card hover:shadow-bento-hover transition-all cursor-pointer group overflow-hidden"
              >
                {/* 缩略图区域 */}
                <div className="relative h-32 bg-gray-50 rounded-t-[20px] flex items-center justify-center overflow-hidden">
                  {previewImageUrl ? (
                    <AppImage
                      src={previewImageUrl}
                      alt={asset.title}
                      fill
                      sizes="(max-width: 640px) 100vw, (max-width: 1280px) 50vw, 25vw"
                      className="object-cover"
                    />
                  ) : (
                    <AssetKindIcon kind={displayKind} className="w-12 h-12" />
                  )}
                </div>

                {/* 信息区域 */}
                <div className="p-3">
                  <h3 className="text-sm font-medium text-gray-800 truncate mb-1" title={asset.title}>
                    {asset.title}
                  </h3>
                  <div className="flex items-center justify-between text-xs text-gray-400">
                    <span className="flex items-center gap-1">
                      <AssetKindIcon kind={displayKind} className="w-3.5 h-3.5" />
                      {displayLabel}
                    </span>
                    <span>{formatSize(asset.file_size)}</span>
                  </div>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-xs text-gray-400">{formatDate(asset.created_at)}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{asset.source}</span>
                  </div>

                  {/* 操作按钮 */}
                  <div className="flex mt-2 pt-2 border-t border-gray-100 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => handlePublish(asset, e)}
                      className="flex items-center gap-1 text-xs text-blue-500 hover:text-blue-700 mr-auto"
                      title="发布到公共空间"
                    >
                      <Share2 className="w-3.5 h-3.5" />
                      发布
                    </button>
                    <button
                      onClick={(e) => handleDelete(asset.id, e)}
                      className="flex items-center gap-1 text-xs text-red-400 hover:text-red-600"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
                );
              })()
            ))}
          </div>

          {/* 分页 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-6">
              <button
                disabled={page <= 1}
                onClick={() => setPage(page - 1)}
                className="px-3 py-1.5 text-sm border border-gray-200 rounded-xl disabled:opacity-40 hover:bg-gray-50 transition-colors"
              >
                上一页
              </button>
              <span className="text-sm text-gray-500">
                {page} / {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage(page + 1)}
                className="px-3 py-1.5 text-sm border border-gray-200 rounded-xl disabled:opacity-40 hover:bg-gray-50 transition-colors"
              >
                下一页
              </button>
            </div>
          )}
        </>
      )}

      {/* 删除确认对话框 */}
      <ConfirmDialog
        open={deleteConfirm.open}
        title="确认删除"
        message="确定要删除此资产文件吗？此操作不可撤销。"
        confirmText="删除"
        cancelText="取消"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirm({ open: false, assetId: null })}
        type="error"
      />

      <AssetPreviewModal
        open={!!previewAsset}
        item={previewAsset}
        onClose={() => setPreviewAsset(null)}
      />
    </div>
  );
}
