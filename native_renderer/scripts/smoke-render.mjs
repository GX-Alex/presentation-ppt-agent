import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { renderDeckToBuffer } from "../src/renderDeck.mjs";

const sampleDeck = {
  deck_id: "smoke-deck-001",
  schema_version: "1.0.0",
  revision: 1,
  artifact_mode: "native_pptx_first",
  title: "GeneralAgent Native Renderer Smoke Test",
  subtitle: "P1 service validation",
  theme: {
    theme_id: "tech_dark",
    palette: {
      background: "#0F172A",
      foreground: "#E2E8F0",
      accent: "#38BDF8",
      muted: "#94A3B8"
    },
    typography: {
      heading_font: "Aptos Display",
      body_font: "Aptos",
      mono_font: "Cascadia Code"
    },
    spacing: {
      base_unit: 8,
      section_gap: 24,
      item_gap: 12
    },
    custom: {}
  },
  slide_size: { width: 1280, height: 720, unit: "px" },
  slides: [
    {
      slide_id: "slide-1",
      title: "Cover",
      page_type: "cover",
      layout_id: "cover.hero",
      notes: "Smoke render slide",
      metadata: {},
      nodes: [
        {
          node_id: "title-1",
          kind: "text",
          role: "title",
          bbox: { x: 96, y: 96, w: 960, h: 120 },
          content: { text: "Native Renderer 已接通" },
          style: { fontSize: 28, color: "#FFFFFF" },
          children: []
        },
        {
          node_id: "body-1",
          kind: "text",
          role: "body",
          bbox: { x: 96, y: 240, w: 960, h: 180 },
          content: {
            runs: [
              { text: "Node + PptxGenJS 承担 PPTX 渲染，", options: { breakLine: true } },
              { text: "Python 继续负责编排、权限、存储与任务状态。" }
            ]
          },
          style: { fontSize: 16, color: "#E2E8F0" },
          children: []
        },
        {
          node_id: "shape-1",
          kind: "shape",
          role: "accent_panel",
          bbox: { x: 84, y: 84, w: 1120, h: 420 },
          content: {},
          style: { fillColor: "#1E293B", transparency: 15 },
          children: []
        }
      ]
    }
  ],
  source_assets: [],
  metadata: { tags: ["smoke", "native-renderer"] }
};

const { buffer, meta } = await renderDeckToBuffer(sampleDeck, {
  author: "GeneralAgent Smoke Test",
  company: "GeneralAgent",
});

const outputPath = resolve(process.cwd(), "smoke-output.pptx");
await writeFile(outputPath, buffer);
console.log(JSON.stringify({ ok: true, outputPath, meta }, null, 2));