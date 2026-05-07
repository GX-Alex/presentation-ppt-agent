"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useToast } from "@/components/ui/Toast";
import { normalizePageBundle } from "@/lib/webdeck";
import { useDeckStore, type DeckPageData, type DeckPageVersion } from "@/stores/deckStore";

function mapVersionPayload(payload: Array<Record<string, unknown>>): DeckPageVersion[] {
  return payload.map((item) => ({
    version: Number(item.version || 0),
    source: String(item.source || "manual"),
    changeSummary: item.change_summary ? String(item.change_summary) : undefined,
    createdAt: item.created_at ? String(item.created_at) : undefined,
  }));
}

interface DeckPageEditorProps {
  projectId: string;
  page: DeckPageData;
  onClose: () => void;
}

export function DeckPageEditor({ projectId, page, onClose }: DeckPageEditorProps) {
  const toast = useToast();

  const draftHtmlByPageId = useDeckStore((s) => s.draftHtmlByPageId);
  const pageVersionsByPageId = useDeckStore((s) => s.pageVersionsByPageId);
  const isSavingPage = useDeckStore((s) => s.isSavingPage);
  const isLoadingVersions = useDeckStore((s) => s.isLoadingVersions);
  const setPageDraft = useDeckStore((s) => s.setPageDraft);
  const setPageVersions = useDeckStore((s) => s.setPageVersions);
  const setSavingPage = useDeckStore((s) => s.setSavingPage);
  const setLoadingVersions = useDeckStore((s) => s.setLoadingVersions);
  const updatePageHtml = useDeckStore((s) => s.updatePageHtml);
  const setFinalHtml = useDeckStore((s) => s.setFinalHtml);
  const [changeSummary, setChangeSummary] = useState("");
  const [rollbackVersion, setRollbackVersion] = useState<number | null>(null);

  const versions = useMemo(
    () => pageVersionsByPageId[page.id] ?? [],
    [pageVersionsByPageId, page.id],
  );

  const loadVersions = useCallback(async () => {
    setLoadingVersions(true);
    try {
      const response = await fetch(`/api/webdeck/projects/${projectId}/pages/${page.id}/versions`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "加载页面版本失败");
      }
      const mapped = mapVersionPayload(Array.isArray(data) ? data : []);
      setPageVersions(page.id, mapped);
      if (mapped.length > 0) {
        setRollbackVersion(mapped[0].version);
      }
    } catch (error: unknown) {
      toast.error(`版本加载失败: ${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setLoadingVersions(false);
    }
  }, [page.id, projectId, setLoadingVersions, setPageVersions, toast]);

  useEffect(() => {
    if (!draftHtmlByPageId[page.id] && page.html) {
      setPageDraft(page.id, page.html);
    }
  }, [draftHtmlByPageId, page.id, page.html, setPageDraft]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  const draftHtml = useMemo(
    () => draftHtmlByPageId[page.id] ?? page.html ?? "",
    [draftHtmlByPageId, page.id, page.html],
  );

  const handleSave = useCallback(async () => {
    if (!draftHtml.trim()) {
      toast.warning("页面内容不能为空");
      return;
    }

    setSavingPage(true);
    try {
      const response = await fetch(`/api/webdeck/projects/${projectId}/pages/${page.id}/save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          html: draftHtml,
          source: "manual",
          change_summary: changeSummary || undefined,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "保存失败");
      }

      updatePageHtml(page.id, String(data.html || draftHtml), normalizePageBundle(data.page_bundle));
      setFinalHtml(String(data.full_html || ""));
      setPageDraft(page.id, String(data.html || draftHtml));
      await loadVersions();
      toast.success(`页面已保存 (v${Number(data.page_version || 0)})`);
    } catch (error: unknown) {
      toast.error(`保存失败: ${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setSavingPage(false);
    }
  }, [changeSummary, draftHtml, loadVersions, page.id, projectId, setFinalHtml, setPageDraft, setSavingPage, toast, updatePageHtml]);

  const handleRollback = useCallback(async () => {
    if (!rollbackVersion) {
      toast.warning("请选择要回滚的版本");
      return;
    }

    setSavingPage(true);
    try {
      const response = await fetch(`/api/webdeck/projects/${projectId}/pages/${page.id}/versions/${rollbackVersion}/rollback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          change_summary: changeSummary || `回滚到版本 v${rollbackVersion}`,
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "回滚失败");
      }

      updatePageHtml(page.id, String(data.html || ""), normalizePageBundle(data.page_bundle));
      setFinalHtml(String(data.full_html || ""));
      setPageDraft(page.id, String(data.html || ""));
      await loadVersions();
      toast.success(`已回滚到版本 v${rollbackVersion}`);
    } catch (error: unknown) {
      toast.error(`回滚失败: ${error instanceof Error ? error.message : "未知错误"}`);
    } finally {
      setSavingPage(false);
    }
  }, [changeSummary, loadVersions, page.id, projectId, rollbackVersion, setFinalHtml, setPageDraft, setSavingPage, toast, updatePageHtml]);

  return (
    <div className="absolute right-3 top-20 bottom-3 z-30 w-[16.5rem] md:w-[17rem] xl:w-[17.5rem] rounded-2xl border border-slate-200 bg-white/95 shadow-2xl backdrop-blur-sm flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-wider text-slate-400">WebDeck 编辑器</p>
          <p className="text-sm font-semibold text-slate-800 truncate">{page.title}</p>
        </div>
        <button
          onClick={onClose}
          className="h-8 w-8 rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-100"
          title="关闭编辑器"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 text-xs">
        <div className="rounded-2xl border border-slate-200 bg-slate-50/70 px-3 py-3 text-[11px] leading-5 text-slate-600">
          右侧侧栏现在只保留版本回滚与页面保存。当前画布只保留文本和布局编辑，图表与图示编辑已暂时关闭。
        </div>

        <div className="space-y-2">
          <p className="font-semibold text-slate-700">版本管理</p>
          <select
            value={rollbackVersion ?? ""}
            onChange={(event) => setRollbackVersion(Number(event.target.value) || null)}
            className="w-full rounded-lg border border-slate-200 px-2 py-1.5"
            disabled={isLoadingVersions || versions.length === 0}
          >
            {versions.length === 0 ? (
              <option value="">暂无版本</option>
            ) : (
              versions.map((item) => (
                <option key={item.version} value={item.version}>
                  v{item.version} · {item.source}
                </option>
              ))
            )}
          </select>
          <button
            onClick={handleRollback}
            disabled={isSavingPage || versions.length === 0}
            className="w-full rounded-lg border border-amber-200 bg-amber-50 py-1.5 text-amber-700 hover:bg-amber-100 disabled:opacity-50"
          >
            回滚到选中版本
          </button>
        </div>

        <div className="space-y-2">
          <p className="font-semibold text-slate-700">保存说明</p>
          <input
            value={changeSummary}
            onChange={(event) => setChangeSummary(event.target.value)}
            placeholder="例如：调整标题文案与布局"
            className="w-full rounded-lg border border-slate-200 px-2 py-1.5"
          />
        </div>

        <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3 text-[11px] text-slate-500">
          当前草稿长度 {draftHtml.length} 字符。保存时会基于当前画布草稿生成新版本并刷新整稿发布结果。
        </div>
      </div>

      <div className="border-t border-slate-100 px-4 py-3 flex items-center gap-2">
        <button
          onClick={handleSave}
          disabled={isSavingPage}
          className="flex-1 rounded-lg bg-slate-900 py-2 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {isSavingPage ? "保存中..." : "保存页面"}
        </button>
        <button
          onClick={onClose}
          className="rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-600 hover:bg-slate-100"
        >
          关闭
        </button>
      </div>
    </div>
  );
}
