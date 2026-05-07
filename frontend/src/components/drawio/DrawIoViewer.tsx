"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useDiagramStore } from "@/stores/diagramStore";
import { prepareDiagramXmlForViewer, BLANK_XML } from "@/lib/diagramXml";
import { getDrawIoEmbedUrl } from "@/lib/drawio";
import { useWebSocket } from "@/hooks/useWebSocket";

const DRAWIO_INIT_TIMEOUT_MS = 12000;

interface DrawIoMessagePayload {
  event?: "configure" | "init" | "autosave" | "save" | "exit";
  xml?: string;
  exit?: boolean;
  source?: string;
}

function parseDrawIoMessage(data: unknown): DrawIoMessagePayload | null {
  if (typeof data === "string") {
    try {
      const parsed = JSON.parse(data) as unknown;
      return parsed && typeof parsed === "object" ? (parsed as DrawIoMessagePayload) : null;
    } catch {
      return null;
    }
  }

  if (data && typeof data === "object") {
    return data as DrawIoMessagePayload;
  }

  return null;
}

export function DrawIoViewer({ embedded = false }: { embedded?: boolean }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const drawIoUrl = useMemo(() => getDrawIoEmbedUrl(), []);
  const [iframeReady, setIframeReady] = useState(false);
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const { sendDiagramAutosave } = useWebSocket();
  const artifactContent = useChatStore((s) => s.artifactContent);
  const taskId = useChatStore((s) => s.taskId);
  const setArtifactContent = useChatStore((s) => s.setArtifactContent);
  const setCurrentArtifactType = useChatStore((s) => s.setCurrentArtifactType);
  const diagramXml = useDiagramStore((s) => s.xml);
  const updateDiagramXml = useDiagramStore((s) => s.updateXml);
  const lastLoadedXml = useRef<string>("");

  useEffect(() => {
    setIframeReady(false);
    setIframeLoaded(false);
    setLoadError(null);
  }, [reloadKey]);

  // 初始化消息监听
  useEffect(() => {
    const handleMessage = (e: MessageEvent) => {
      if (iframeRef.current?.contentWindow && e.source !== iframeRef.current.contentWindow) {
        return;
      }

      const msg = parseDrawIoMessage(e.data);
      if (!msg || msg.source === "react-devtools-bridge") {
        return;
      }

      if (msg.event === "configure") {
        iframeRef.current?.contentWindow?.postMessage(
          JSON.stringify({
            action: "configure",
            config: { compressXml: false },
          }),
          "*"
        );
      } else if (msg.event === "init") {
        setIframeReady(true);
        setLoadError(null);

        const prepared = prepareDiagramXmlForViewer(diagramXml || artifactContent || BLANK_XML);
        if (prepared.error) {
          setLoadError(prepared.error);
        }
        const initialXml = prepared.xml || BLANK_XML;
        lastLoadedXml.current = initialXml;
        iframeRef.current?.contentWindow?.postMessage(
          JSON.stringify({
            action: "load",
            autosave: 1,
            xml: initialXml,
          }),
          "*"
        );

        // 延迟发送 resize action，让 Draw.io 适应容器大小
        setTimeout(() => {
          iframeRef.current?.contentWindow?.postMessage(
            JSON.stringify({ action: "resize" }),
            "*"
          );
        }, 300);
      } else if (msg.event === "autosave" || msg.event === "save") {
        if (typeof msg.xml !== "string") {
          return;
        }

        const prepared = prepareDiagramXmlForViewer(msg.xml);
        lastLoadedXml.current = prepared.xml;
        updateDiagramXml(prepared.xml, { syncStatus: "dirty" });
        setArtifactContent(prepared.xml);
        sendDiagramAutosave(prepared.xml, taskId || undefined);

        if (msg.event === "save") {
          iframeRef.current?.contentWindow?.postMessage(
            JSON.stringify({
              action: "status",
              message: "所有更改已保存",
              modified: false,
            }),
            "*"
          );

          if (msg.exit) {
            setCurrentArtifactType("none");
          }
        }
      } else if (msg.event === "exit") {
        setCurrentArtifactType("none");
      }
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [artifactContent, diagramXml, sendDiagramAutosave, setArtifactContent, setCurrentArtifactType, taskId, updateDiagramXml]);

  useEffect(() => {
    if (iframeReady) {
      return;
    }

    const timer = window.setTimeout(() => {
      setLoadError(
        iframeLoaded
          ? "Draw.io 编辑器已响应，但初始化消息未完成。请重试；如果仍失败，可配置内部 diagrams.net 地址。"
          : "当前无法连接 Draw.io 服务。请检查网络、代理，或使用内部部署的 diagrams.net 地址。"
      );
    }, DRAWIO_INIT_TIMEOUT_MS);

    return () => window.clearTimeout(timer);
  }, [iframeLoaded, iframeReady, reloadKey]);

  const handleRetry = () => {
    setReloadKey((value) => value + 1);
  };

  const handleOpenExternal = () => {
    window.open(drawIoUrl, "_blank", "noopener,noreferrer");
  };

  // 当外部 artifactContent 更新且不等于 iframe 中目前的内容时加载
  useEffect(() => {
    const nextXml = diagramXml || artifactContent;
    if (iframeReady && nextXml && nextXml !== lastLoadedXml.current) {
      const prepared = prepareDiagramXmlForViewer(nextXml);
      lastLoadedXml.current = prepared.xml;
      iframeRef.current?.contentWindow?.postMessage(
        JSON.stringify({
          action: "load",
          autosave: 1,
          xml: prepared.xml,
        }),
        "*"
      );
    }
  }, [artifactContent, diagramXml, iframeReady]);

  return (
    <div
      className={embedded
        ? "absolute inset-0 overflow-hidden bg-white"
        : "flex-1 min-h-0 w-full h-full relative border border-gray-200 shadow-sm rounded-2xl overflow-hidden bg-white"}
    >
      {!iframeReady && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-50 z-10">
          <div className="max-w-md px-6 text-center">
            <span className="text-4xl">📐</span>
            <p className="mt-2 text-sm font-medium text-gray-600">
              {loadError ?? "Draw.io 画布加载中..."}
            </p>
            {loadError && (
              <div className="mt-4 flex items-center justify-center gap-3">
                <button
                  type="button"
                  onClick={handleRetry}
                  className="rounded-full border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition hover:border-gray-400 hover:bg-white"
                >
                  重试
                </button>
                <button
                  type="button"
                  onClick={handleOpenExternal}
                  className="rounded-full border border-blue-200 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700 transition hover:border-blue-300 hover:bg-blue-100"
                >
                  新窗口打开
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      <iframe
        key={reloadKey}
        ref={iframeRef}
        className="w-full h-full border-0"
        src={drawIoUrl}
        title="Draw.io Editor"
        onLoad={() => setIframeLoaded(true)}
      />
    </div>
  );
}
