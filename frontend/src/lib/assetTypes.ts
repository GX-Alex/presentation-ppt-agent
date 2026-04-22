export type AssetDisplayKind = "ppt" | "document" | "code" | "image" | "drawio" | "skill" | "other";

export interface AssetTypeDescriptor {
  title?: string | null;
  category?: string | null;
  fileType?: string | null;
  file_type?: string | null;
  fileUrl?: string | null;
  file_url?: string | null;
  previewUrl?: string | null;
  preview_url?: string | null;
  thumbnailUrl?: string | null;
  thumbnail_url?: string | null;
  mimeType?: string | null;
  mime_type?: string | null;
}

const IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg"]);

function pickString(...values: Array<string | null | undefined>): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

export function getFileExtension(value?: string | null): string {
  if (!value) return "";
  const cleaned = value.split("?")[0]?.split("#")[0] || value;
  const parts = cleaned.split(".");
  return parts.length > 1 ? parts[parts.length - 1].toLowerCase() : "";
}

function getFileType(descriptor: AssetTypeDescriptor): string {
  return pickString(descriptor.fileType, descriptor.file_type).toLowerCase();
}

function getMimeType(descriptor: AssetTypeDescriptor): string {
  return pickString(descriptor.mimeType, descriptor.mime_type).toLowerCase();
}

function getFileUrl(descriptor: AssetTypeDescriptor): string {
  return pickString(descriptor.fileUrl, descriptor.file_url);
}

function getPreviewUrl(descriptor: AssetTypeDescriptor): string {
  return pickString(descriptor.previewUrl, descriptor.preview_url);
}

function getThumbnailUrl(descriptor: AssetTypeDescriptor): string {
  return pickString(descriptor.thumbnailUrl, descriptor.thumbnail_url);
}

export function resolveAssetKind(descriptor: AssetTypeDescriptor): AssetDisplayKind {
  const fileType = getFileType(descriptor);
  const mimeType = getMimeType(descriptor);
  const category = pickString(descriptor.category).toLowerCase();
  const extensions = [
    getFileExtension(getFileUrl(descriptor)),
    getFileExtension(getPreviewUrl(descriptor)),
    getFileExtension(getThumbnailUrl(descriptor)),
    getFileExtension(descriptor.title),
  ].filter(Boolean);

  if (fileType === "drawio" || extensions.includes("drawio")) {
    return "drawio";
  }

  if (fileType === "ppt" || extensions.includes("pptx") || extensions.includes("ppt")) {
    return "ppt";
  }

  if (fileType === "image" || mimeType.startsWith("image/") || extensions.some((ext) => IMAGE_EXTENSIONS.has(ext))) {
    return "image";
  }

  if (fileType === "code") {
    return "code";
  }

  if (fileType === "skill" || category === "skill") {
    return "skill";
  }

  if (fileType === "document") {
    return "document";
  }

  if (category === "ppt") {
    return "ppt";
  }

  if (category === "research") {
    return "document";
  }

  if (category === "code") {
    return "code";
  }

  return "other";
}

export function getAssetKindLabel(input: AssetDisplayKind | AssetTypeDescriptor): string {
  const kind = typeof input === "string" ? input : resolveAssetKind(input);
  const labels: Record<AssetDisplayKind, string> = {
    ppt: "PPT",
    document: "文档",
    code: "代码",
    image: "图片",
    drawio: "draw.io",
    skill: "Skill",
    other: "其他",
  };
  return labels[kind] || kind;
}

export function resolveAssetPreviewImageUrl(descriptor: AssetTypeDescriptor): string | null {
  const thumbnailUrl = getThumbnailUrl(descriptor);
  if (thumbnailUrl) {
    return thumbnailUrl;
  }

  const candidate = getPreviewUrl(descriptor) || getFileUrl(descriptor);
  if (!candidate) {
    return null;
  }

  const mimeType = getMimeType(descriptor);
  const ext = getFileExtension(candidate);
  if (mimeType.startsWith("image/") || IMAGE_EXTENSIONS.has(ext) || resolveAssetKind(descriptor) === "image") {
    return candidate;
  }

  return null;
}

export function resolveGalleryCategory(descriptor: AssetTypeDescriptor): string {
  const kind = resolveAssetKind(descriptor);
  if (kind === "ppt") return "ppt";
  if (kind === "document") return "research";
  if (kind === "code") return "code";
  if (kind === "skill") return "skill";
  return "other";
}