const DEFAULT_DRAWIO_EMBED_BASE = "https://embed.diagrams.net";
const DEFAULT_DRAWIO_VIEWER_BASE = "https://viewer.diagrams.net";

function normalizeBaseUrl(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return (trimmed && trimmed.length > 0 ? trimmed : fallback).replace(/\/$/, "");
}

export function getDrawIoEmbedUrl(): string {
  const baseUrl = normalizeBaseUrl(
    process.env.NEXT_PUBLIC_DRAWIO_EMBED_BASE_URL,
    DEFAULT_DRAWIO_EMBED_BASE
  );
  return `${baseUrl}/?embed=1&ui=min&spin=1&proto=json&configure=1&saveAndExit=1`;
}

export function getDrawIoViewerUrl(fileUrl: string, title: string): string {
  const baseUrl = normalizeBaseUrl(
    process.env.NEXT_PUBLIC_DRAWIO_VIEWER_BASE_URL,
    DEFAULT_DRAWIO_VIEWER_BASE
  );
  return `${baseUrl}/?lightbox=1&highlight=0000ff&edit=_blank&title=${encodeURIComponent(title)}#U${encodeURIComponent(fileUrl)}`;
}