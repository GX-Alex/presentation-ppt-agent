import JSZip from "jszip";

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function upsertSimpleTag(xml, tagName, value) {
  const escapedValue = escapeXml(value);
  const tagPattern = new RegExp(`<${tagName}>([\\s\\S]*?)</${tagName}>`);
  if (tagPattern.test(xml)) {
    return xml.replace(tagPattern, `<${tagName}>${escapedValue}</${tagName}>`);
  }

  return xml.replace("</cp:coreProperties>", `  <${tagName}>${escapedValue}</${tagName}>\n</cp:coreProperties>`);
}

export async function applyOoxmlPatches(buffer, deckSpec, renderOptions = {}) {
  const zip = await JSZip.loadAsync(buffer);
  const coreEntry = zip.file("docProps/core.xml");
  if (!coreEntry) {
    return buffer;
  }

  let coreXml = await coreEntry.async("string");
  const rendererName = renderOptions.author || "GeneralAgent Native Renderer";
  const keywords = [
    "generalagent",
    "native-pptx",
    deckSpec.theme?.theme_id || "theme",
    ...(Array.isArray(deckSpec.metadata?.tags) ? deckSpec.metadata.tags : []),
  ]
    .filter(Boolean)
    .join(", ");

  coreXml = upsertSimpleTag(coreXml, "dc:creator", rendererName);
  coreXml = upsertSimpleTag(coreXml, "cp:lastModifiedBy", rendererName);
  coreXml = upsertSimpleTag(coreXml, "dc:title", deckSpec.title || "GeneralAgent Deck");
  coreXml = upsertSimpleTag(coreXml, "dc:description", renderOptions.subject || deckSpec.subtitle || deckSpec.title || "");
  coreXml = upsertSimpleTag(coreXml, "cp:keywords", keywords);

  zip.file("docProps/core.xml", coreXml);
  return zip.generateAsync({ type: "nodebuffer" });
}