"""Health check endpoint."""
import time
from fastapi import APIRouter

router = APIRouter(tags=["health"])

# 应用启动时间（用于计算运行时长）
APP_START_TIME = time.time()


@router.get("/health")
async def health_check():
    """健康检查接口，返回服务状态和基本信息。"""
    uptime = time.time() - APP_START_TIME
    return {
        "status": "ok",
        "service": "presentationagent-backend",
        "version": "0.1.0",
        "uptime_seconds": round(uptime, 1),
    }
