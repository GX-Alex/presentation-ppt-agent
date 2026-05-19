const BLANK_XML = `<mxfile><diagram id="blank" name="Page-1"><mxGraphModel dx="1000" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel></diagram></mxfile>`;

const ARTIFACT_RE = /<general-artifact\s+type="drawio">([\s\S]*?)<\/general-artifact>/i;
const CODE_FENCE_RE = /```(?:xml|drawio)?\s*\n([\s\S]*?)\n```/i;

export function extractDiagramXml(raw: string | null | undefined): string {
  const content = (raw || "").trim();
  if (!content) {
    return "";
  }

  const artifactMatch = content.match(ARTIFACT_RE);
  if (artifactMatch) {
    return artifactMatch[1].trim();
  }

  const codeMatch = content.match(CODE_FENCE_RE);
  if (codeMatch) {
    return codeMatch[1].trim();
  }

  return content;
}

export function isMxCellFragmentComplete(fragment: string): boolean {
  const trimmed = fragment.trim();
  if (!trimmed) {
    return false;
  }
  if (typeof DOMParser === "undefined") {
    return true;
  }
  const parser = new DOMParser();
  const doc = parser.parseFromString(`<fragment>${trimmed}</fragment>`, "application/xml");
  return doc.getElementsByTagName("parsererror").length === 0;
}

export function wrapMxCellsWithMxfile(fragment: string): string {
  return BLANK_XML.replace(
    "</root>",
    `${fragment.trim()}</root>`
  );
}

export function isMinimalDiagram(xml: string): boolean {
  const normalized = extractDiagramXml(xml);
  return normalized.includes("<mxfile") || normalized.includes("<mxGraphModel") || normalized.includes("<mxCell");
}

function fixGeometryAsAttribute(xml: string): string {
  // Remove existing as attribute (wrong value), then add correct one
  return xml
    .replace(/<mxGeometry\b([^>]*?)\s+as="[^"]*"/g, "<mxGeometry$1")
    .replace(/<mxGeometry\b(?![^>]*\bas="geometry")/g, '<mxGeometry as="geometry"');
}

export function prepareDiagramXmlForViewer(raw: string | null | undefined): { xml: string; fixed: boolean; error?: string } {
  const extracted = extractDiagramXml(raw);
  if (!extracted) {
    return { xml: BLANK_XML, fixed: false };
  }

  if (extracted.includes("<mxfile")) {
    return { xml: fixGeometryAsAttribute(extracted), fixed: false };
  }

  if (extracted.includes("<mxGraphModel")) {
    return {
      xml: fixGeometryAsAttribute(`<mxfile><diagram id="viewer" name="Page-1">${extracted}</diagram></mxfile>`),
      fixed: true,
    };
  }

  if (extracted.includes("<mxCell") && isMxCellFragmentComplete(extracted)) {
    return { xml: fixGeometryAsAttribute(wrapMxCellsWithMxfile(extracted)), fixed: true };
  }

  return {
    xml: BLANK_XML,
    fixed: false,
    error: "draw.io XML 不完整，已回退到空白画布。",
  };
}

export { BLANK_XML };