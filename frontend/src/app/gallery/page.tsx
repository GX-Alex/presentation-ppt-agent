/**
 * Gallery page — 公共画廊（浏览/Fork/发布）。
 * Route: /gallery
 * Sprint 6: 完整画廊功能 — 分类/卡片/预览/Fork。
 */
"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Eye,
  GitFork,
  Star,
  Search,
  RefreshCw,
  ImageIcon,
} from "lucide-react";
import { useToast } from "@/components/ui/Toast";
import AppImage from "@/components/ui/AppImage";
import AssetPreviewModal, { type PreviewAssetItem } from "@/components/assets/AssetPreviewModal";
import { AssetKindIcon } from "@/components/assets/AssetKindIcon";
import {
  getAssetKindLabel,
  resolveAssetKind,
  resolveAssetPreviewImageUrl,
} from "@/lib/assetTypes";

// ────── 类型定义 ──────

interface GalleryItemData {
  id: string;
  asset_id: string;
  author_id: string;
  category: string;
  title: string | null;
  description: string | null;
  preview_url: string | null;
  is_featured: boolean;
  remix_count: number;
  view_count: number;
  version: number;
  license: string;
  published_at: string | null;
  file_type?: string;
  file_url?: string;
  thumbnail_url?: string;
}

// ────── 辅助函数 ──────

/** 分类中文名 */
function catLabel(cat: string): string {
  const m: Record<string, string> = {
    ppt: "PPT",
    research: "研究",
    code: "代码",
    skill: "Skill",
    other: "其他",
  };
  return m[cat] || cat;
}

// ────── Tab 配置 ──────

const tabs = ["推荐", "PPT", "研究", "代码", "🔌 Skill", "其他"];
const tabToCategory: Record<number, string | null> = {
  0: null,        // 全部 / 推荐
  1: "ppt",
  2: "research",
  3: "code",
  4: "skill",
  5: "other",
};
const sortOptions = [
  { value: "newest", label: "最新发布" },
  { value: "popular", label: "最多浏览" },
  { value: "remix", label: "最多 Fork" },
];

// ────── 主组件 ──────

export default function GalleryPage() {
  const router = useRouter();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState(0);
  const [items, setItems] = useState<GalleryItemData[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState("newest");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [previewItem, setPreviewItem] = useState<PreviewAssetItem | null>(null);

  // 加载画廊列表
  const loadGallery = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      const category = tabToCategory[activeTab];
      if (category) params.set("category", category);
      if (activeTab === 0) params.set("featured", "true"); // 推荐 tab 只显示推荐
      if (search.trim()) params.set("search", search.trim());
      params.set("sort", sort);
      params.set("page", String(page));
      params.set("page_size", "20");

      const res = await fetch(`/api/gallery/?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        const initialItems = data.items || [];
        setItems(initialItems);
        setTotal(data.total || 0);

        // 推荐 tab 如果没有推荐项，回退到全部
        if (activeTab === 0 && initialItems.length === 0) {
          const res2 = await fetch(`/api/gallery/?sort=${sort}&page=${page}&page_size=20`);
          if (res2.ok) {
            const data2 = await res2.json();
            if (data2.items?.length > 0) {
              setItems(data2.items);
              setTotal(data2.total || 0);
            }
          }
        }
      } else {
        toast.error("加载公共空间失败，请稍后重试");
      }
    } catch (err) {
      console.error("[Gallery] 加载失败:", err);
      toast.error("网络错误，请检查连接后重试");
    } finally {
      setLoading(false);
    }
  }, [activeTab, search, sort, page, toast]);

  useEffect(() => {
    loadGallery();
  }, [loadGallery]);

  const handleTabChange = (i: number) => {
    setActiveTab(i);
    setPage(1);
  };

  const searchPlaceholder = "搜索作品...";

  // Fork 操作
  const handleFork = async (itemId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const res = await fetch(`/api/gallery/${itemId}/fork`, { method: "POST" });
      if (res.ok) {
        await res.json();
        toast.success("Fork 成功，已添加到你的资产");
        // 刷新列表以更新 remix_count
        void loadGallery();
        // 跳转到公共空间页查看
        router.push("/assets");
      } else {
        const data = await res.json().catch(() => ({}));
        toast.error(data.detail || "Fork 失败，请稍后重试");
      }
    } catch (err) {
      console.error("[Gallery] Fork 失败:", err);
      toast.error("网络错误，Fork 失败");
    }
  };

  // 卡片点击 — 查看详情（增加浏览数）
  const handleCardClick = async (item: GalleryItemData) => {
    try {
      // 获取详情（自动增加浏览计数）
      const res = await fetch(`/api/gallery/${item.id}`);
      if (res.ok) {
        const detail = await res.json();
        const displayItem = {
          title: detail.title || item.title || "无标题",
          category: detail.category || item.category,
          file_type: detail.file_type || item.file_type,
          file_url: detail.file_url || item.file_url || null,
          preview_url: detail.preview_url || item.preview_url || null,
          thumbnail_url: detail.thumbnail_url || item.thumbnail_url || null,
        };
        setPreviewItem({
          id: detail.id || item.id,
          title: detail.title || item.title || "无标题",
          fileType: resolveAssetKind(displayItem),
          fileUrl: detail.file_url || item.file_url || null,
          thumbnailUrl: detail.thumbnail_url || item.thumbnail_url || null,
          description: detail.description || item.description || null,
          sourceLabel: catLabel(detail.category || item.category || "other"),
        });
      }
    } catch (err) {
      console.error("[Gallery] 获取详情失败:", err);
      toast.error("加载作品预览失败，请稍后重试");
    }
  };

  const totalPages = Math.ceil(total / 20);

  return (
    <div className="p-6 h-full overflow-y-auto">
      {/* 标题 + 搜索 + 排序 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">公共空间</h1>
        <div className="flex items-center gap-3">
          <select
            value={sort}
            onChange={(e) => { setSort(e.target.value); setPage(1); }}
            className="px-3 py-2.5 border border-gray-200 rounded-xl text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
          >
            {sortOptions.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder={searchPlaceholder}
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              className="pl-9 pr-4 py-2.5 border border-gray-200 rounded-xl w-56 text-sm bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          </div>
          <button
            onClick={() => {
              void loadGallery();
            }}
            className="p-2.5 text-gray-500 hover:text-gray-700 rounded-xl hover:bg-gray-100 transition-colors"
            title="刷新"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 p-1 bg-gray-100 rounded-xl w-fit">
        {tabs.map((tab, i) => (
          <button
            key={tab}
            onClick={() => handleTabChange(i)}
            className={`px-4 py-1.5 text-sm font-medium rounded-lg transition-all ${
              i === activeTab
                ? "bg-white text-primary-600 shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* 内容区域 */}
      {loading ? (
        <div className="text-center py-20 text-gray-400">
          <RefreshCw className="w-8 h-8 animate-spin mx-auto mb-3" />
          <p className="text-sm">加载中...</p>
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-20">
          <ImageIcon className="w-16 h-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium text-gray-500 mb-2">暂无作品</p>
          <p className="text-sm text-gray-400 max-w-sm mx-auto">
            发布你的资产文件到公共空间，让更多人看到你的创作
          </p>
        </div>
      ) : (
        <>
          {/* 卡片网格 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {items.map((item) => (
              (() => {
                const previewImageUrl = resolveAssetPreviewImageUrl(item);
                const displayKind = resolveAssetKind(item);
                const displayLabel = getAssetKindLabel(displayKind);

                return (
              <div
                key={item.id}
                onClick={() => handleCardClick(item)}
                className="bento-card hover:shadow-bento-hover transition-all cursor-pointer group overflow-hidden"
              >
                {/* 预览图 */}
                <div className="h-36 bg-gray-50 rounded-t-[20px] flex items-center justify-center overflow-hidden relative">
                  {previewImageUrl ? (
                    <AppImage
                      src={previewImageUrl}
                      alt={item.title || "作品预览图"}
                      fill
                      sizes="(max-width: 640px) 100vw, (max-width: 1280px) 50vw, 25vw"
                      className="object-cover"
                    />
                  ) : (
                    <AssetKindIcon kind={displayKind} className="w-12 h-12" />
                  )}
                  {/* 推荐标记 */}
                  {item.is_featured && (
                    <span className="absolute top-2 right-2 bg-yellow-400 text-yellow-900 text-xs font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                      <Star className="w-3 h-3" /> 推荐
                    </span>
                  )}
                </div>

                {/* 信息 */}
                <div className="p-3">
                  <h3 className="text-sm font-medium text-gray-800 truncate mb-1" title={item.title || ""}>
                    {item.title || "无标题"}
                  </h3>
                  {item.description && (
                    <p className="text-xs text-gray-500 line-clamp-2 mb-2">{item.description}</p>
                  )}

                  {/* 统计 */}
                  <div className="flex items-center gap-3 text-xs text-gray-400 mb-2">
                    <span className="flex items-center gap-1">
                      <Eye className="w-3.5 h-3.5" /> {item.view_count}
                    </span>
                    <span className="flex items-center gap-1">
                      <GitFork className="w-3.5 h-3.5" /> {item.remix_count}
                    </span>
                    <span className="flex items-center gap-1">
                      <AssetKindIcon kind={displayKind} className="w-3.5 h-3.5" />
                      {displayLabel}
                    </span>
                  </div>

                  {/* 底部操作 */}
                  <div className="flex items-center justify-between pt-2 border-t border-gray-100">
                    <span className="text-xs text-gray-400">
                      v{item.version} · {item.license}
                    </span>
                    <button
                      onClick={(e) => handleFork(item.id, e)}
                      className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-800 font-medium"
                    >
                      <GitFork className="w-3.5 h-3.5" />
                      Fork
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

      <AssetPreviewModal
        open={!!previewItem}
        item={previewItem}
        onClose={() => setPreviewItem(null)}
      />
    </div>
  );
}
