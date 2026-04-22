"""
Playwright 浏览器实例池 — 用于 PDF 导出与截图。
设计要点:
  - 单例 Chromium 浏览器进程，复用避免反复启动
  - Semaphore(max_pages) 控制并发页面数量，防止 OOM
  - 提供 acquire_page / release_page 上下文管理器
  - 在 FastAPI lifespan 中 init / close
"""
import asyncio
import logging
import os

from playwright.async_api import async_playwright, Browser, Page, Playwright

logger = logging.getLogger(__name__)

# 最大并发页面数（通过环境变量可配）
MAX_PAGES = int(os.getenv("BROWSER_POOL_MAX_PAGES", "3"))

# ──────────── 全局单例 ────────────
_playwright: Playwright | None = None
_browser: Browser | None = None
_semaphore: asyncio.Semaphore | None = None
_lock = asyncio.Lock()


def is_pool_ready() -> bool:
    """Return whether the shared browser pool is ready for export tasks."""
    return _browser is not None and _semaphore is not None


async def init_pool() -> None:
    """
    初始化 Playwright 浏览器池。
    在 FastAPI lifespan startup 中调用。
    """
    global _playwright, _browser, _semaphore

    async with _lock:
        if _browser is not None:
            logger.info("[BrowserPool] 浏览器池已初始化，跳过")
            return

        logger.info(f"[BrowserPool] 正在启动 Chromium（max_pages={MAX_PAGES}）...")
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",    # Docker 环境避免 /dev/shm 不足
                "--disable-gpu",
                "--disable-setuid-sandbox",
            ],
        )
        _semaphore = asyncio.Semaphore(MAX_PAGES)
        logger.info("[BrowserPool] ✅ Chromium 浏览器池已就绪")


async def close_pool() -> None:
    """
    关闭浏览器池，释放资源。
    在 FastAPI lifespan shutdown 中调用。
    """
    global _playwright, _browser, _semaphore

    async with _lock:
        if _browser:
            await _browser.close()
            _browser = None
            logger.info("[BrowserPool] 浏览器已关闭")
        if _playwright:
            await _playwright.stop()
            _playwright = None
            logger.info("[BrowserPool] Playwright 已停止")
        _semaphore = None


async def acquire_page() -> Page:
    """
    从浏览器池获取一个新页面（受 Semaphore 限流）。
    调用方必须在使用完毕后调用 release_page(page)。

    Raises:
        RuntimeError: 浏览器池未初始化
    """
    if _browser is None or _semaphore is None:
        raise RuntimeError("[BrowserPool] 浏览器池未初始化，请先调用 init_pool()")

    await _semaphore.acquire()
    try:
        page = await _browser.new_page()
        logger.debug("[BrowserPool] 页面已创建")
        return page
    except Exception:
        _semaphore.release()
        raise


async def release_page(page: Page) -> None:
    """
    释放页面并归还信号量。

    Args:
        page: 要释放的 Playwright 页面
    """
    try:
        await page.close()
        logger.debug("[BrowserPool] 页面已关闭")
    except Exception as e:
        logger.warning(f"[BrowserPool] 关闭页面时出错: {e}")
    finally:
        if _semaphore is not None:
            _semaphore.release()


class managed_page:
    """
    上下文管理器 — 自动获取和释放页面。

    用法:
        async with managed_page() as page:
            await page.goto(url)
            pdf = await page.pdf()
    """

    def __init__(self):
        self.page: Page | None = None

    async def __aenter__(self) -> Page:
        self.page = await acquire_page()
        return self.page

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.page:
            await release_page(self.page)
        return False  # 不吞异常
