"use client";

import { useEffect, useMemo, useState } from "react";
import { FileText, ListChecks, Presentation, Sparkles, X } from "lucide-react";
import {
  QUALITY_THEME_OPTIONS,
  type QualityGenerateAttachment,
  type QualityGenerateBrief,
} from "@/lib/qualityGeneration";

interface QualityGenerateDialogProps {
  open: boolean;
  attachments: QualityGenerateAttachment[];
  onClose: () => void;
  onSubmit: (brief: QualityGenerateBrief) => Promise<boolean> | boolean;
}

interface QualityBriefFormState {
  title: string;
  topic: string;
  audience: string;
  goal: string;
  deliverable: QualityGenerateBrief["deliverable"];
  main_slide_count: number;
  appendix_slide_count: number;
  theme_id: string;
  tone: string;
  must_include_text: string;
  reference_urls_text: string;
  notes: string;
}

const DEFAULT_BRIEF: QualityBriefFormState = {
  title: "",
  topic: "",
  audience: "管理层 / 业务负责人",
  goal: "快速讲清楚核心判断、证据与下一步行动",
  deliverable: "report_then_ppt" as const,
  main_slide_count: 8,
  appendix_slide_count: 2,
  theme_id: "tech_dark",
  tone: "专业、清晰、可执行",
  must_include_text: "",
  reference_urls_text: "",
  notes: "",
};

const SUPPORTED_THEME_IDS = new Set(QUALITY_THEME_OPTIONS.map((option) => option.id));

export function QualityGenerateDialog({ open, attachments, onClose, onSubmit }: QualityGenerateDialogProps) {
  const [form, setForm] = useState(DEFAULT_BRIEF);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const attachmentNames = useMemo(() => attachments.map((item) => item.filename).join("、"), [attachments]);

  useEffect(() => {
    if (!open) {
      setSubmitError(null);
      setIsSubmitting(false);
    }
  }, [open]);

  if (!open) {
    return null;
  }

  const handleSubmit = async () => {
    if (!form.topic.trim()) {
      setSubmitError("请先填写主题");
      return;
    }

    setSubmitError(null);
    setIsSubmitting(true);

    const brief: QualityGenerateBrief = {
      title: form.title.trim(),
      topic: form.topic.trim(),
      audience: form.audience.trim(),
      goal: form.goal.trim(),
      deliverable: form.deliverable,
      slide_count: form.main_slide_count + form.appendix_slide_count,
      main_slide_count: form.main_slide_count,
      appendix_slide_count: form.appendix_slide_count,
      theme_id: SUPPORTED_THEME_IDS.has(form.theme_id) ? form.theme_id : "tech_dark",
      tone: form.tone.trim(),
      must_include: form.must_include_text
        .split(/\n|,|，|;|；/)
        .map((item) => item.trim())
        .filter(Boolean),
      reference_urls: form.reference_urls_text
        .split(/\n|,|，|;|；/)
        .map((item) => item.trim())
        .filter(Boolean),
      appendix: form.appendix_slide_count > 0,
      notes: form.notes.trim(),
      attachments,
    };

    try {
      const submitted = await onSubmit(brief);
      if (!submitted) {
        setSubmitError("提交失败，当前连接未就绪，请稍后重试。");
        return;
      }
      onClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/35 p-4 backdrop-blur-sm md:p-6">
      <div className="flex max-h-[calc(100vh-2rem)] w-full max-w-4xl flex-col overflow-hidden rounded-[28px] border border-slate-200 bg-[linear-gradient(180deg,#fffdf7_0%,#f7fbff_100%)] shadow-[0_30px_80px_-40px_rgba(15,23,42,0.45)] md:max-h-[calc(100vh-4rem)]">
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4 md:px-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-sky-600">Quality Brief</p>
            <h3 className="mt-1 text-lg font-semibold text-slate-900">高质量生成</h3>
            <p className="mt-1 text-sm text-slate-500">先把目标、受众和必须覆盖的信息说清楚，再让系统先出大纲。</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full border border-slate-200 p-2 text-slate-500 transition-colors hover:bg-white hover:text-slate-900"
            title="关闭"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="overflow-y-auto px-5 py-5 md:px-6 md:py-6">
        <div className="grid gap-5 md:grid-cols-[1.3fr,0.9fr]">
          <div className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">主题</span>
              <input
                value={form.topic}
                onChange={(event) => setForm((current) => ({ ...current, topic: event.target.value }))}
                placeholder="例如：AI 客服改造方案、银行本体论变革风险路线图"
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">标题</span>
              <input
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
                placeholder="可选，不填则自动根据主题生成"
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">受众</span>
                <input
                  value={form.audience}
                  onChange={(event) => setForm((current) => ({ ...current, audience: event.target.value }))}
                  className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">主文页数</span>
                <input
                  type="number"
                  min={4}
                  max={50}
                  value={form.main_slide_count}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      main_slide_count: Math.min(50, Math.max(4, Number(event.target.value) || 8)),
                    }))
                  }
                  className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                />
              </label>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-sm font-medium text-slate-700">附录页数</span>
                <input
                  type="number"
                  min={0}
                  max={50}
                  value={form.appendix_slide_count}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      appendix_slide_count: Math.min(50, Math.max(0, Number(event.target.value) || 0)),
                    }))
                  }
                  className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                />
              </label>
              <div className="rounded-[24px] border border-slate-200 bg-white/70 px-4 py-3 shadow-sm">
                <p className="text-xs font-medium uppercase tracking-[0.2em] text-slate-400">生成分层</p>
                <p className="mt-2 text-sm font-medium text-slate-800">
                  主文 {form.main_slide_count} 页
                  {form.appendix_slide_count > 0 ? ` + 附录 ${form.appendix_slide_count} 页` : ""}
                </p>
                <p className="mt-1 text-xs leading-5 text-slate-500">系统会先收束主文结论，再把证据、口径和明细下沉到附录。</p>
              </div>
            </div>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">沟通目标</span>
              <textarea
                value={form.goal}
                onChange={(event) => setForm((current) => ({ ...current, goal: event.target.value }))}
                rows={3}
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">必须覆盖</span>
              <textarea
                value={form.must_include_text}
                onChange={(event) => setForm((current) => ({ ...current, must_include_text: event.target.value }))}
                rows={3}
                placeholder="每行一项，或用中文逗号分隔。例如：业务背景、关键数据、实施路径、风险与缓释"
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">网页来源</span>
              <textarea
                value={form.reference_urls_text}
                onChange={(event) => setForm((current) => ({ ...current, reference_urls_text: event.target.value }))}
                rows={3}
                placeholder="每行一个链接，系统会尝试抓取正文并纳入研究材料。例如：https://example.com/report"
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">补充要求</span>
              <textarea
                value={form.notes}
                onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
                rows={3}
                placeholder="例如：需要偏董事会汇报口吻；重点突出 ROI；少讲技术实现细节"
                className="w-full rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
              />
            </label>
          </div>

          <div className="space-y-4">
            <div className="rounded-[24px] border border-slate-200 bg-white/70 p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                <Sparkles className="h-4 w-4 text-sky-600" />
                生成方式
              </div>
              <div className="mt-3 grid gap-2">
                <button
                  onClick={() => setForm((current) => ({ ...current, deliverable: "report_then_ppt" }))}
                  className={`rounded-2xl border px-4 py-3 text-left transition ${
                    form.deliverable === "report_then_ppt"
                      ? "border-sky-300 bg-sky-50 text-sky-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <FileText className="h-4 w-4" /> 先报告后 PPT
                  </div>
                  <p className="mt-1 text-xs leading-5 opacity-80">先给你一版 Markdown 报告草案，再输出可确认的大纲。</p>
                </button>
                <button
                  onClick={() => setForm((current) => ({ ...current, deliverable: "ppt" }))}
                  className={`rounded-2xl border px-4 py-3 text-left transition ${
                    form.deliverable === "ppt"
                      ? "border-sky-300 bg-sky-50 text-sky-700"
                      : "border-slate-200 bg-white text-slate-600 hover:border-slate-300"
                  }`}
                >
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Presentation className="h-4 w-4" /> 直接出 PPT
                  </div>
                  <p className="mt-1 text-xs leading-5 opacity-80">直接生成待确认的大纲，适合目标明确的场景。</p>
                </button>
              </div>
            </div>

            <div className="rounded-[24px] border border-slate-200 bg-white/70 p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                <ListChecks className="h-4 w-4 text-sky-600" />
                风格控制
              </div>
              <div className="mt-3 space-y-3">
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium uppercase tracking-[0.2em] text-slate-400">主题</span>
                  <select
                    value={form.theme_id}
                    onChange={(event) => setForm((current) => ({ ...current, theme_id: event.target.value }))}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                  >
                    {QUALITY_THEME_OPTIONS.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-xs font-medium uppercase tracking-[0.2em] text-slate-400">表达气质</span>
                  <input
                    value={form.tone}
                    onChange={(event) => setForm((current) => ({ ...current, tone: event.target.value }))}
                    className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                  />
                </label>
                <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700">
                  <p className="font-medium text-slate-800">附录自动生成</p>
                  <p className="mt-1 text-xs leading-5 text-slate-500">
                    当附录页数大于 0 时，系统会把补充证据、口径说明和测算明细自动下沉到附录页。
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-[24px] border border-dashed border-slate-300 bg-slate-50/80 p-4 shadow-sm">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
                <FileText className="h-4 w-4 text-sky-600" />
                参考材料
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {attachments.length > 0
                  ? `本次会一起读取 ${attachments.length} 个附件：${attachmentNames}`
                  : "当前输入栏无附件 — 系统将自动关联对话历史中已上传的附件"}
              </p>
            </div>
          </div>
        </div>
        </div>

        <div className="border-t border-slate-200 bg-white/85 px-5 py-4 backdrop-blur md:px-6">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs leading-5 text-slate-500">提交后会先生成页面级大纲，只有在你确认后才开始真正出幻灯片。</p>
            {submitError ? <p className="mt-2 text-sm text-red-600">{submitError}</p> : null}
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              disabled={isSubmitting}
              className="rounded-2xl border border-slate-200 px-4 py-2.5 text-sm text-slate-600 transition hover:bg-white"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={!form.topic.trim() || isSubmitting}
              className="rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {isSubmitting ? "提交中..." : "确认并提交 Brief"}
            </button>
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
