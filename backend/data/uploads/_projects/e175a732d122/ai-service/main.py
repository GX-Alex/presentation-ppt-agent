"""
FastAPI AI 服务入口模块

本模块是整个 AI 服务的启动入口，负责：
1. 创建 FastAPI 应用实例
2. 配置 CORS 跨域中间件（允许前端开发服务器访问）
3. 注册所有 API 路由（解析、报告生成）
4. 提供健康检查端点
5. 启动时打印配置信息供运维确认
"""

import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging_config import setup_logging
from app.api.parse import router as parse_router
from app.api.report import router as report_router
from app.api.tag import router as tag_router
from app.api.financial_report import router as financial_report_router
from app.api.agent_chat import router as agent_chat_router
from app.api.docs import router as docs_router

# 初始化日志配置；可通过环境变量 LOG_LEVEL 覆盖（如 DEBUG）
setup_logging(os.getenv("LOG_LEVEL", "INFO"))

# 创建 FastAPI 应用实例
# title: 服务名称，用于自动生成的 API 文档（Swagger UI）
# description: 服务描述，展示在 API 文档首页
# version: 服务版本号，便于前后端版本对齐
app = FastAPI(
    title="Appolo AI 服务（内部）",
    description="""银行流水智能解析与报告生成服务，由 Java 后端代理调用。用户请通过后端 /api/docs 查看完整文档。""",
    version="1.0.0",
)

# ---------- CORS 跨域配置 ----------
# 允许的前端来源列表：
# - http://localhost:5173  : Vite 前端开发服务器（Vue/React）
# - http://localhost:8080  : Java 后端网关（Spring Boot）
allowed_origins = [
    "http://localhost:5173",
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,       # 允许的来源域名列表
    allow_credentials=True,              # 允许携带 Cookie / Authorization 头
    allow_methods=["*"],                 # 允许所有 HTTP 方法（GET/POST/PUT/DELETE 等）
    allow_headers=["*"],                 # 允许所有请求头
)

# ---------- 注册 API 路由 ----------
# 所有解析相关的接口，前缀 /api/v1/parse
app.include_router(parse_router, prefix="/api/v1/parse", tags=["PDF解析"])
# 所有报告生成相关的接口，前缀 /api/v1/report
app.include_router(report_router, prefix="/api/v1/report", tags=["报告生成"])
# 所有标签分类相关的接口，前缀 /api/v1/tag
app.include_router(tag_router, prefix="/api/v1/tag", tags=["智能标签"])
app.include_router(financial_report_router, prefix="/api/v1/financial-report", tags=["财报解析"])
app.include_router(agent_chat_router, prefix="/api/v1/agent", tags=["智能体问答"])
app.include_router(docs_router)


@app.get("/health", tags=["系统"])
async def health_check():
    """
    健康检查端点

    用于容器编排（Docker/K8s）的存活探针和就绪探针，
    返回服务的基本状态信息。
    """
    return {
        "status": "ok",
        "service": "appolo-ai-service",
        "ai_provider": settings.ai_provider,
    }


@app.on_event("startup")
async def startup_event():
    """
    应用启动事件回调

    在 FastAPI 服务启动完成后自动执行，
    打印当前生效的关键配置项，便于运维人员确认部署环境是否正确。
    """
    import logging
    log = logging.getLogger("main")
    log.info("=" * 50)
    log.info("Appolo AI 服务启动")
    log.info("=" * 50)
    log.info("AI 提供商: %s", settings.ai_provider)
    if settings.ai_provider == "bailian":
        log.info("百炼端点: %s | 模型: %s", settings.bailian_endpoint, settings.bailian_model)
        api_key_display = settings.bailian_api_key[:8] + "****" if settings.bailian_api_key else "未配置"
        log.info("百炼 API Key: %s", api_key_display)
    else:
        log.info("私有化端点: %s | 文本模型: %s | 视觉模型: %s",
                 settings.private_endpoint, settings.private_text_model, settings.private_vl_model)
    log.info("上传目录: %s | 单次最大页数: %d | 解析超时: %ds",
             settings.upload_dir, settings.max_pages_per_request, settings.parse_timeout)
    log.info("=" * 50)


if __name__ == "__main__":
    # 直接运行本文件时启动 uvicorn 服务器
    # host="0.0.0.0" 监听所有网卡，方便容器部署
    # port=9000 服务端口，避免与其他服务冲突
    # reload=True 开发模式下文件变更自动重载
    uvicorn.run("main:app", host="0.0.0.0", port=9000, reload=True)
