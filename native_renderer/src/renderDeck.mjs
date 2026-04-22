import PptxGenJS from "pptxgenjs";

import { applyOoxmlPatches } from "./ooxmlPatch.mjs";

const PX_PER_INCH = 96;
const DEFAULT_LAYOUT_NAME = "GA_NATIVE_LAYOUT";
const DEFAULT_FONT_FACE = "Aptos";
const DEFAULT_MONO_FACE = "Cascadia Code";

function ensureHex(color, fallback = "FFFFFF") {
  if (!color) return fallback;
  return String(color).replace(/^#/, "").toUpperCase();
}

function pxToInches(value, unit = "px") {
  if (typeof value !== "number") return 0;
  if (unit === "pt") return value / 72;
  if (unit === "emu") return value / 914400;
  return value / PX_PER_INCH;
}

function slideUnitConverter(deckSpec) {
  const unit = deckSpec.slide_size?.unit || "px";
  return {
    x: (value) => pxToInches(value, unit),
    y: (value) => pxToInches(value, unit),
    w: (value) => pxToInches(value, unit),
    h: (value) => pxToInches(value, unit),
  };
}

function mapTextRuns(node, theme) {
  if (Array.isArray(node.content?.runs) && node.content.runs.length > 0) {
    return node.content.runs.map((run) => ({
      text: run.text || "",
      options: {
        bold: run.bold,
        italic: run.italic,
        color: ensureHex(run.color, ensureHex(theme.palette.foreground, "1F2937")),
        breakLine: run.breakLine,
        bullet: run.bullet,
        indentLevel: run.indentLevel,
      },
    }));
  }

  return node.content?.text || "";
}

function mapTextOptions(node, deckSpec) {
  const theme = deckSpec.theme;
  const converter = slideUnitConverter(deckSpec);
  const style = node.style || {};
  const role = node.role || "body";
  const fontFace = style.fontFace || (role.includes("code") ? theme.typography.mono_font || DEFAULT_MONO_FACE : role.includes("title") || role.includes("headline") ? theme.typography.heading_font || DEFAULT_FONT_FACE : theme.typography.body_font || DEFAULT_FONT_FACE);

  return {
    x: converter.x(node.bbox.x),
    y: converter.y(node.bbox.y),
    w: converter.w(node.bbox.w),
    h: converter.h(node.bbox.h),
    fontFace,
    fontSize: style.fontSize || (role.includes("title") ? 24 : role.includes("headline") ? 22 : 16),
    bold: style.bold ?? (role.includes("title") || role.includes("headline")),
    italic: style.italic ?? false,
    margin: style.margin ?? 0.08,
    fit: style.fit || "shrink",
    valign: style.valign || "top",
    align: style.align || "left",
    color: ensureHex(style.color, ensureHex(theme.palette.foreground, "1F2937")),
    breakLine: style.breakLine,
    fill: style.fillColor ? { color: ensureHex(style.fillColor) } : undefined,
    bullet: style.bullet,
    transparency: style.transparency,
    line: style.lineColor
      ? {
          color: ensureHex(style.lineColor),
          width: style.lineWidth || 1,
        }
      : undefined,
  };
}

function renderTextNode(slide, node, deckSpec) {
  slide.addText(mapTextRuns(node, deckSpec.theme), mapTextOptions(node, deckSpec));
}

function renderImageNode(slide, node, deckSpec, warnings) {
  const converter = slideUnitConverter(deckSpec);
  const imageSource = node.content?.data || node.content?.path || node.content?.src;
  if (!imageSource) {
    warnings.push(`slide=${node.node_id}: image node missing path/data/src`);
    return;
  }

  const imageOptions = {
    x: converter.x(node.bbox.x),
    y: converter.y(node.bbox.y),
    w: converter.w(node.bbox.w),
    h: converter.h(node.bbox.h),
    altText: node.content?.alt || node.role || node.node_id,
  };

  if (node.content?.data) {
    slide.addImage({ ...imageOptions, data: node.content.data });
    return;
  }

  slide.addImage({ ...imageOptions, path: imageSource });
}

function resolveShapeType(pptx, shapeType) {
  const normalized = String(shapeType || "roundedRect").toLowerCase();
  const mapping = {
    rect: pptx.shapes.RECTANGLE,
    rectangle: pptx.shapes.RECTANGLE,
    roundedrect: pptx.shapes.ROUNDED_RECTANGLE,
    roundedrectangle: pptx.shapes.ROUNDED_RECTANGLE,
  };
  return mapping[normalized] || pptx.shapes.ROUNDED_RECTANGLE;
}

function renderShapeNode(slide, pptx, node, deckSpec) {
  const converter = slideUnitConverter(deckSpec);
  const shapeType = resolveShapeType(pptx, node.content?.shapeType);
  slide.addShape(shapeType, {
    x: converter.x(node.bbox.x),
    y: converter.y(node.bbox.y),
    w: converter.w(node.bbox.w),
    h: converter.h(node.bbox.h),
    fill: { color: ensureHex(node.style?.fillColor, ensureHex(deckSpec.theme.palette.accent, "2563EB")) },
    line: node.style?.lineColor
      ? { color: ensureHex(node.style.lineColor), width: node.style.lineWidth || 1 }
      : { color: ensureHex(node.style?.fillColor, ensureHex(deckSpec.theme.palette.accent, "2563EB")), transparency: 100 },
    transparency: node.style?.transparency || 0,
  });
}

function renderTableNode(slide, node, deckSpec, warnings) {
  const converter = slideUnitConverter(deckSpec);
  const rows = Array.isArray(node.content?.rows) ? node.content.rows : [];
  if (rows.length === 0) {
    warnings.push(`slide=${node.node_id}: table node missing rows`);
    return;
  }

  const headerRows = Number(node.content?.headerRows || 0);
  const style = node.style || {};
  const mappedRows = rows.map((row, rowIndex) =>
    row.map((cell) => ({
      text: cell == null ? "" : String(cell),
      options: rowIndex < headerRows
        ? {
            bold: true,
            color: ensureHex(style.headerColor, ensureHex(deckSpec.theme?.palette?.background, "FFFFFF")),
            fill: { color: ensureHex(style.headerFillColor, ensureHex(deckSpec.theme?.palette?.accent, "2563EB")) },
            align: "center",
            valign: "mid",
          }
        : {
            color: ensureHex(style.color, ensureHex(deckSpec.theme?.palette?.foreground, "1F2937")),
            fill: style.fillColor ? { color: ensureHex(style.fillColor) } : undefined,
            align: "left",
            valign: "mid",
          },
    }))
  );

  slide.addTable(mappedRows, {
    x: converter.x(node.bbox.x),
    y: converter.y(node.bbox.y),
    w: converter.w(node.bbox.w),
    border: {
      pt: style.lineWidth || 1,
      color: ensureHex(style.lineColor, ensureHex(deckSpec.theme?.palette?.muted, "94A3B8")),
    },
    color: ensureHex(style.color, ensureHex(deckSpec.theme?.palette?.foreground, "1F2937")),
    fontFace: deckSpec.theme?.typography?.body_font || DEFAULT_FONT_FACE,
    fontSize: style.fontSize || 12,
    margin: 0.05,
    autoFit: false,
    colW: Array.isArray(node.content?.colWidths)
      ? node.content.colWidths.map((value) => converter.w(value))
      : undefined,
  });
}

function resolveChartType(pptx, chartType) {
  const normalized = String(chartType || "bar").toLowerCase();
  const mapping = {
    area: pptx.charts.AREA,
    bar: pptx.charts.BAR,
    column: pptx.charts.BAR,
    doughnut: pptx.charts.DOUGHNUT,
    line: pptx.charts.LINE,
    pie: pptx.charts.PIE,
  };
  return mapping[normalized] || pptx.charts.BAR;
}

function renderChartNode(slide, pptx, node, deckSpec, warnings) {
  const converter = slideUnitConverter(deckSpec);
  const categories = Array.isArray(node.content?.categories) ? node.content.categories : [];
  const series = Array.isArray(node.content?.series) ? node.content.series : [];
  if (categories.length === 0 || series.length === 0) {
    warnings.push(`slide=${node.node_id}: chart node missing categories/series`);
    return;
  }

  const chartType = String(node.content?.chartType || "bar").toLowerCase();
  const data = series.map((item, index) => ({
    name: item.name || `Series ${index + 1}`,
    labels: Array.isArray(item.labels) && item.labels.length > 0 ? item.labels : categories,
    values: Array.isArray(item.values) ? item.values : [],
  }));
  const style = node.style || {};

  slide.addChart(resolveChartType(pptx, chartType), data, {
    x: converter.x(node.bbox.x),
    y: converter.y(node.bbox.y),
    w: converter.w(node.bbox.w),
    h: converter.h(node.bbox.h),
    barDir: chartType === "column" ? "col" : "bar",
    catAxisLabelColor: ensureHex(style.color, ensureHex(deckSpec.theme?.palette?.foreground, "1F2937")),
    valAxisLabelColor: ensureHex(style.color, ensureHex(deckSpec.theme?.palette?.foreground, "1F2937")),
    chartColors: [ensureHex(deckSpec.theme?.palette?.accent, "2563EB")],
    dataLabelPosition: chartType === "bar" || chartType === "column" ? "outEnd" : undefined,
    gridLine: { color: ensureHex(style.lineColor, ensureHex(deckSpec.theme?.palette?.muted, "94A3B8")) },
    legendPos: "b",
    showLegend: node.content?.showLegend ?? data.length > 1,
    showTitle: false,
    showValue: node.content?.showValue ?? false,
  });
}

function renderNode(slide, pptx, node, deckSpec, warnings) {
  if (node.kind === "text") {
    renderTextNode(slide, node, deckSpec);
  } else if (node.kind === "image") {
    renderImageNode(slide, node, deckSpec, warnings);
  } else if (node.kind === "table") {
    renderTableNode(slide, node, deckSpec, warnings);
  } else if (node.kind === "chart") {
    renderChartNode(slide, pptx, node, deckSpec, warnings);
  } else if (node.kind === "shape") {
    renderShapeNode(slide, pptx, node, deckSpec);
  } else if (node.kind !== "group") {
    warnings.push(`slide=${node.node_id}: unsupported node kind ${node.kind}`);
  }

  if (Array.isArray(node.children)) {
    node.children.forEach((child) => renderNode(slide, pptx, child, deckSpec, warnings));
  }
}

export async function renderDeckToBuffer(deckSpec, renderOptions = {}) {
  const pptx = new PptxGenJS();
  const width = pxToInches(deckSpec.slide_size.width, deckSpec.slide_size.unit);
  const height = pxToInches(deckSpec.slide_size.height, deckSpec.slide_size.unit);
  const warnings = [];

  pptx.defineLayout({ name: DEFAULT_LAYOUT_NAME, width, height });
  pptx.layout = DEFAULT_LAYOUT_NAME;
  pptx.author = renderOptions.author || "GeneralAgent Native Renderer";
  pptx.company = renderOptions.company || "GeneralAgent";
  pptx.subject = renderOptions.subject || deckSpec.subtitle || deckSpec.title;
  pptx.title = deckSpec.title;
  pptx.lang = renderOptions.lang || "zh-CN";
  pptx.theme = {
    headFontFace: deckSpec.theme?.typography?.heading_font || DEFAULT_FONT_FACE,
    bodyFontFace: deckSpec.theme?.typography?.body_font || DEFAULT_FONT_FACE,
    lang: renderOptions.lang || "zh-CN",
  };

  deckSpec.slides.forEach((slideSpec, index) => {
    const slide = pptx.addSlide({ bkgd: ensureHex(deckSpec.theme?.palette?.background, "FFFFFF") });
    slide.color = ensureHex(deckSpec.theme?.palette?.foreground, "1F2937");
    slide.addNotes(slideSpec.notes || `Generated from DeckSpec slide ${index + 1}`);
    slide.slideNumber = {
      x: width - 0.8,
      y: height - 0.35,
      fontSize: 10,
      color: ensureHex(deckSpec.theme?.palette?.muted, "64748B"),
    };

    slideSpec.nodes.forEach((node) => renderNode(slide, pptx, node, deckSpec, warnings));
  });

  let buffer = await pptx.write({ outputType: "nodebuffer" });
  buffer = await applyOoxmlPatches(buffer, deckSpec, renderOptions);

  return {
    buffer,
    meta: {
      renderer: "generalagent-native-renderer",
      slideCount: deckSpec.slides.length,
      warnings,
    },
  };
}