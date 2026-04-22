export interface QualityGenerateAttachment {
  asset_id: string;
  filename: string;
  file_type?: string;
  mime_type?: string;
  file_url: string;
}

export interface QualityGenerateBrief {
  title: string;
  topic: string;
  audience: string;
  goal: string;
  deliverable: "ppt" | "report_then_ppt";
  slide_count: number;
  main_slide_count: number;
  appendix_slide_count: number;
  theme_id: string;
  tone: string;
  must_include: string[];
  appendix: boolean;
  notes: string;
  attachments: QualityGenerateAttachment[];
  reference_urls: string[];
}

export interface WebDeckGenerateBrief {
  topic: string;
  title?: string;
  audience?: string;
  goal?: string;
  deliverable?: "ppt" | "report_then_ppt";
  page_count?: number;
  main_slide_count?: number;
  appendix_slide_count?: number;
  theme_id?: string;
  tone?: string;
  style?: string;
  must_cover?: string;
  must_include?: string[];
  materials?: string;
  extra?: string;
  notes?: string;
  attachments?: QualityGenerateAttachment[];
  reference_urls?: string[];
}

export const QUALITY_THEME_OPTIONS = [
  { id: "tech_dark", label: "科技深色" },
  { id: "business_light", label: "商务简洁" },
  { id: "academic", label: "学术米黄" },
  { id: "midnight_executive", label: "午夜行政" },
  { id: "forest_nature", label: "森林自然" },
  { id: "coral_energy", label: "珊瑚活力" },
  { id: "charcoal_minimal", label: "炭灰极简" },
  { id: "teal_trust", label: "青绿信任" },
];

export function formatQualityBriefMessage(brief: QualityGenerateBrief): string {
  const lines = [
    `请按高质量流程生成 ${brief.deliverable === "report_then_ppt" ? "先报告后PPT" : "PPT"}：${brief.title || brief.topic}`,
    `主题：${brief.topic}`,
    `受众：${brief.audience}`,
    `目标：${brief.goal}`,
    `页数：主文 ${brief.main_slide_count} 页 + 附录 ${brief.appendix_slide_count} 页 = 共 ${brief.slide_count} 页`,
    `风格：${brief.theme_id} / ${brief.tone}`,
  ];

  if (brief.must_include.length > 0) {
    lines.push(`必须覆盖：${brief.must_include.join("；")}`);
  }
  if (brief.notes.trim()) {
    lines.push(`补充要求：${brief.notes.trim()}`);
  }
  if (brief.attachments.length > 0) {
    lines.push(`参考材料：${brief.attachments.map((item) => item.filename).join("；")}`);
  }
  if (brief.reference_urls.length > 0) {
    lines.push(`网页来源：${brief.reference_urls.join("；")}`);
  }

  return lines.join("\n");
}

export function toWebDeckGenerateBrief(brief: QualityGenerateBrief): WebDeckGenerateBrief {
  const materialLines = [
    ...brief.reference_urls,
    ...brief.attachments.map((item) => `${item.filename}: ${item.file_url}`),
  ];

  const extraLines = [
    brief.title.trim() ? `标题偏好：${brief.title.trim()}` : "",
    brief.goal.trim() ? `沟通目标：${brief.goal.trim()}` : "",
    `生成策略：${brief.deliverable === "report_then_ppt" ? "先报告后 Web Deck" : "直接生成 Web Deck"}`,
    `页数规划：主文 ${brief.main_slide_count} 页${brief.appendix_slide_count > 0 ? `，附录 ${brief.appendix_slide_count} 页` : ""}`,
    brief.notes.trim() ? `补充要求：${brief.notes.trim()}` : "",
  ].filter(Boolean);

  return {
    topic: brief.topic.trim(),
    title: brief.title.trim() || undefined,
    audience: brief.audience.trim() || undefined,
    goal: brief.goal.trim() || undefined,
    deliverable: brief.deliverable,
    page_count: brief.slide_count,
    main_slide_count: brief.main_slide_count,
    appendix_slide_count: brief.appendix_slide_count,
    theme_id: brief.theme_id,
    tone: brief.tone,
    style: [brief.theme_id, brief.tone].filter(Boolean).join(" / ") || undefined,
    must_cover: brief.must_include.join("；") || undefined,
    must_include: brief.must_include,
    materials: materialLines.join("\n") || undefined,
    extra: extraLines.join("\n") || undefined,
    notes: brief.notes.trim() || undefined,
    attachments: brief.attachments,
    reference_urls: brief.reference_urls,
  };
}
