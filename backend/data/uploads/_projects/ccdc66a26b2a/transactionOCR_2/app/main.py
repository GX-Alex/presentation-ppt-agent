"""
FastAPI 应用入口
"""
import re
import time
import json
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from pathlib import Path

from app.routers.ocr import router as ocr_router
from app.logger import logger


# ══════════════════════════════════════════════════════════════
#  原始报文日志中间件
# ══════════════════════════════════════════════════════════════

def _mask_data_url(text: str, max_b64_len: int = 80) -> str:
    """将 base64 data URL 的 base64 部分截断，避免日志暴增。"""
    return re.sub(
        r"(data:[^;]+;base64,)([A-Za-z0-9+/=]{" + str(max_b64_len) + r"})[A-Za-z0-9+/=]*",
        r"\1\2...[TRUNCATED]",
        text,
    )


class RawLoggingMiddleware(BaseHTTPMiddleware):
    """打印上游原始请求报文和服务响应报文（base64 data URL 自动截断）。"""

    async def dispatch(self, request: Request, call_next):
        # ── 读取请求体（Starlette 会缓存，call_next 仍可读） ──
        req_body = await request.body()
        start = time.perf_counter()

        # 只对 /ocr 路径打印原始报文，health/root 不打印
        should_log = request.url.path.startswith("/ocr")

        if should_log:
            try:
                body_str = req_body.decode("utf-8", errors="replace")
                body_masked = _mask_data_url(body_str)
            except Exception:
                body_masked = "<binary>"

            logger.info(
                ">>> 上游请求原始报文\n"
                "  Method : %s %s\n"
                "  Headers: Content-Type=%s\n"
                "  Body   : %s",
                request.method,
                request.url.path,
                request.headers.get("content-type", "-"),
                body_masked[:4000],   # 超长截断到 4000 字符
            )

        # ── 调用实际处理逻辑 ──
        response = await call_next(request)

        # ── 读取响应体 ──
        resp_chunks = []
        async for chunk in response.body_iterator:
            resp_chunks.append(chunk)
        resp_body = b"".join(resp_chunks)
        elapsed_ms = int((time.perf_counter() - start) * 1000)

        if should_log:
            try:
                resp_str = resp_body.decode("utf-8", errors="replace")
                resp_masked = _mask_data_url(resp_str)
            except Exception:
                resp_masked = "<binary>"

            logger.info(
                "<<< 服务响应原始报文\n"
                "  Status : %d  耗时=%dms\n"
                "  Body   : %s",
                response.status_code,
                elapsed_ms,
                resp_masked[:2000],
            )

        return Response(
            content=resp_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

app = FastAPI(
    title="银行交易流水 OCR 智能体服务",
    description="基于 LangGraph + Qwen-VL 的银行流水信息提取服务",
    version="1.0.0",
    default_response_class=JSONResponse,
)

# ── 原始报文日志中间件（最外层，先于 CORS）──
app.add_middleware(RawLoggingMiddleware)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("未捕获的异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )


# ── 注册路由 ──
app.include_router(ocr_router)

# ── 静态文件：CSV 下载目录 ──
downloads_dir = Path("downloads")
downloads_dir.mkdir(exist_ok=True)
app.mount("/downloads", StaticFiles(directory=str(downloads_dir)), name="downloads")


# ── 健康检查 ──
@app.get("/health")
async def health():
    return {"status": "ok", "service": "transaction-ocr-agent"}


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "银行交易流水 OCR 智能体服务",
        "version": "1.0.0",
        "endpoints": {
            "POST /ocr": "银行交易流水 OCR 提取（远程 URL）",
            "POST /ocr/upload": "银行交易流水 OCR 提取（本地上传）",
            "GET /downloads/{filename}": "CSV 文件下载",
            "GET /health": "健康检查",
        },
    }


if __name__ == "__main__":
    import uvicorn
    from app.config import HOST, PORT

    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False)
