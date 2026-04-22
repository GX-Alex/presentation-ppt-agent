"""
General Agent Platform — 后端入口
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（优先从项目根目录加载）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()  # fallback: 当前目录或默认搜索

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.health import router as health_router
from app.api.tasks import router as tasks_router
from app.api.files import router as files_router
from app.api.assets import router as assets_router
from app.api.skills import router as skills_router
from app.api.gallery import router as gallery_router
from app.api.memory import router as memory_router
from app.api.packages import router as packages_router
from app.api.presentations import router as presentations_router
from app.api.webdeck import router as webdeck_router
from app.ws.chat_handler import router as ws_router
from app.models.database import async_session, init_db
from app.core.tool_dispatch import auto_discover_tools
from app.core.error_handling import (
    RequestTimeoutMiddleware,
    ErrorHandlingMiddleware,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
BACKEND_ROOT = Path(__file__).resolve().parent
RELOAD_EXCLUDES = [
    "data/*",
    ".venv/*",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "*.db",
    "*.db-*",
    "*.sqlite",
    "*.sqlite-*",
]
# Scope hot-reload to the app source directory only (avoids scanning .venv / node_modules)
RELOAD_DIRS = ["app"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动与关闭。"""
    # 启动: 初始化数据库
    await init_db()
    logger.info("✅ 数据库初始化完成")

    # 启动: 自动发现并注册所有 Tool
    auto_discover_tools()
    logger.info("✅ Tool 注册完成")

    # 启动: 加载系统 Skill
    from app.services.skill_service import load_system_skills
    load_system_skills()
    logger.info("✅ 系统 Skill 加载完成")

    # 启动: 物化内置 Plugin Registry
    try:
        from app.services.plugin_registry import ensure_plugin_registry_seeded
        async with async_session() as session:
            await ensure_plugin_registry_seeded(session)
        logger.info("✅ Plugin Registry 初始化完成")
    except Exception as e:
        logger.warning(f"⚠️ Plugin Registry 初始化失败: {e}")

    # 启动: 初始化 Playwright 浏览器池（用于 PDF/PPTX 导出）
    try:
        from app.services.browser_pool import init_pool
        await init_pool()
        logger.info("✅ Playwright 浏览器池初始化完成")
    except Exception as e:
        # 浏览器池初始化失败不阻止应用启动（导出功能降级）
        logger.warning(f"⚠️ Playwright 浏览器池初始化失败（导出功能不可用）: {e}")

    yield

    # 关闭: 清理 Playwright 浏览器池
    try:
        from app.services.browser_pool import close_pool
        await close_pool()
        logger.info("✅ Playwright 浏览器池已关闭")
    except Exception as e:
        logger.warning(f"⚠️ 关闭 Playwright 浏览器池出错: {e}")

    # 关闭: 清理资源
    logger.info("👋 正在关闭服务")


app = FastAPI(
    title="General Agent Platform",
    version="0.1.0",
    description="通用智能体平台 — 一阶段聚焦 PPT/文档生成",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sprint 7: 全局错误处理 + 请求超时中间件
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(RequestTimeoutMiddleware, timeout=300)

# Static files (uploads, exports)
os.makedirs(BACKEND_ROOT / "data" / "uploads", exist_ok=True)
os.makedirs(BACKEND_ROOT / "data" / "exports", exist_ok=True)
app.mount("/static", StaticFiles(directory=str(BACKEND_ROOT / "data")), name="static")

# REST API routes
app.include_router(health_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(assets_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(gallery_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(packages_router, prefix="/api")
app.include_router(presentations_router, prefix="/api")
app.include_router(webdeck_router, prefix="/api")

# WebSocket
app.include_router(ws_router)


def _get_uvicorn_run_kwargs() -> dict[str, object]:
    """构建开发/生产通用的 uvicorn 启动参数。"""
    reload_enabled = os.getenv("ENV", "development") == "development"
    kwargs: dict[str, object] = {
        "app": "main:app",
        "host": "0.0.0.0",
        "port": 8002,
        "reload": reload_enabled,
    }
    if reload_enabled:
        kwargs["reload_dirs"] = RELOAD_DIRS
        kwargs["reload_includes"] = ["*.py"]
        kwargs["reload_excludes"] = RELOAD_EXCLUDES
    return kwargs


if __name__ == "__main__":
    import uvicorn

    run_kwargs = _get_uvicorn_run_kwargs()
    if run_kwargs.get("reload"):
        logger.info("[main] Uvicorn reload enabled: dirs=%s excludes=%s", RELOAD_DIRS, RELOAD_EXCLUDES)
    uvicorn.run(**run_kwargs)
