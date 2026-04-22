import express from "express";

import { renderDeckToBuffer } from "./renderDeck.mjs";

const app = express();
const port = Number(process.env.NATIVE_RENDERER_PORT || 4100);

app.use(express.json({ limit: "20mb" }));

app.get("/health", (_req, res) => {
  res.json({ ok: true, service: "generalagent-native-renderer", version: "0.1.0" });
});

app.post("/render/pptx", async (req, res) => {
  try {
    const { deckSpec, options } = req.body || {};
    if (!deckSpec || !Array.isArray(deckSpec.slides)) {
      res.status(400).json({ error: "deckSpec 缺失或不合法" });
      return;
    }

    const { buffer, meta } = await renderDeckToBuffer(deckSpec, options || {});
    res.json({
      fileBase64: buffer.toString("base64"),
      contentType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      meta,
    });
  } catch (error) {
    console.error("[NativeRenderer] render failed", error);
    res.status(500).json({
      error: error instanceof Error ? error.message : "Native renderer failed",
    });
  }
});

app.listen(port, () => {
  console.log(`[NativeRenderer] listening on :${port}`);
});