"""
Presentations API — 演示文稿管理接口。
  - GET /presentations/themes — 获取可用主题列表
  - GET /presentations/:id — 获取完整演示文稿（含幻灯片）
  - GET /presentations/task/:task_id — 通过任务 ID 获取演示文稿
  - GET /presentations/:id/html — 获取组装后的完整 reveal.js HTML
  - PUT /presentations/:id/outline — 更新大纲
    - POST /presentations/:id/export/:format — 导出 (html/pdf/pptx-faithful/pptx-editable)
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import get_session
from app.services import ppt_service
from app.services import export_service
from app.services.browser_pool import is_pool_ready
from app.services.package_runtime import DEFAULT_RUNTIME_USER_ID
from app.services.pptx_roundtrip_service import import_pptx_as_presentation
from app.services.theme_manager import get_theme_list

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/presentations", tags=["presentations"])


class PptxRoundTripImportRequest(BaseModel):
    asset_id: str | None = Field(default=None, min_length=3, max_length=127)
    file_url: str | None = Field(default=None, min_length=3, max_length=1024)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    theme_id: str | None = Field(default=None, min_length=3, max_length=127)
    task_id: str | None = Field(default=None, min_length=3, max_length=127)
    presentation_id: str | None = Field(default=None, min_length=3, max_length=127)


@router.get("/themes")
async def list_themes():
    """返回所有可用的 PPT 主题。"""
    return {"themes": get_theme_list()}


@router.get("/{presentation_id}")
async def get_presentation(
    presentation_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取完整演示文稿数据（含幻灯片列表）。"""
    data = await ppt_service.get_presentation(session, presentation_id)
    if not data:
        raise HTTPException(status_code=404, detail="演示文稿不存在")
    return data


@router.get("/task/{task_id}")
async def get_presentation_by_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    """通过任务 ID 获取最新的演示文稿。"""
    data = await ppt_service.get_presentation_by_task(session, task_id)
    if not data:
        raise HTTPException(status_code=404, detail="该任务没有关联的演示文稿")
    return data


@router.post("/import/pptx")
async def import_pptx_roundtrip(
    body: PptxRoundTripImportRequest,
    session: AsyncSession = Depends(get_session),
):
    if not body.asset_id and not body.file_url:
        raise HTTPException(status_code=400, detail="必须提供 asset_id 或 file_url")

    try:
        result = await import_pptx_as_presentation(
            session,
            asset_id=body.asset_id,
            file_url=body.file_url,
            title=body.title,
            theme_id=body.theme_id,
            task_id=body.task_id,
            presentation_id=body.presentation_id,
            user_id=DEFAULT_RUNTIME_USER_ID,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"success": True, **result}


@router.get("/{presentation_id}/html")
async def get_presentation_html(
    presentation_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取组装后的完整 reveal.js HTML 页面。"""
    html = await ppt_service.build_full_html(session, presentation_id)
    if not html:
        raise HTTPException(status_code=404, detail="演示文稿不存在或无幻灯片数据")
    return HTMLResponse(content=html, media_type="text/html")


class OutlineUpdateRequest(BaseModel):
    outline: list = Field(..., min_length=1, description="大纲数据列表")


@router.put("/{presentation_id}/outline")
async def update_outline(
    presentation_id: str,
    body: OutlineUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新演示文稿大纲。"""
    success = await ppt_service.update_outline(session, presentation_id, body.outline)
    if not success:
        raise HTTPException(status_code=404, detail="演示文稿不存在")
    return {"success": True, "message": "大纲已更新"}

@router.post("/{presentation_id}/export/{export_format}")
async def export_presentation(
    presentation_id: str,
    export_format: str,
    session: AsyncSession = Depends(get_session),
):
    """
    导出演示文稿。

    Args:
        export_format: html / pdf / pptx-faithful / pptx-editable
    """
    valid_formats = {"html", "pdf", "pptx-faithful", "pptx-editable"}
    if export_format not in valid_formats:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的格式: {export_format}，可用: {', '.join(valid_formats)}"
        )

    # 获取演示文稿数据
    pres_data = await ppt_service.get_presentation(session, presentation_id)
    if not pres_data:
        raise HTTPException(status_code=404, detail="演示文稿不存在")

    title = pres_data.get("title", "演示文稿")
    theme_id = pres_data.get("theme", {}).get("id", "tech_dark")
    slides = pres_data.get("slides", [])

    if not slides:
        raise HTTPException(status_code=400, detail="演示文稿没有幻灯片数据")

    try:
        file_path = await _export_presentation_file(
            session=session,
            presentation_id=presentation_id,
            export_format=export_format,
            slides=slides,
            title=title,
            theme_id=theme_id,
        )

        # 返回下载路径
        return {
            "success": True,
            "format": export_format,
            "file_path": file_path,
            "download_url": f"/static/{file_path}",
        }

    except HTTPException:
        raise
    except RuntimeError as e:
        # Playwright 未初始化等运行时错误
        logger.error(f"[Export] 导出失败: {e}")
        raise HTTPException(status_code=500, detail="导出服务暂不可用，请稍后重试")
    except Exception as e:
        logger.exception(f"[Export] 导出异常: {e}")
        raise HTTPException(status_code=500, detail="导出时发生错误，请稍后重试")


@router.get("/export-capabilities")
async def get_export_capabilities():
    browser_ready = is_pool_ready()

    return {
        "formats": {
            "html": {"available": True, "reason": None},
            "pdf": {
                "available": browser_ready,
                "reason": None if browser_ready else "Playwright 浏览器池未初始化",
            },
            "pptx-faithful": {
                "available": browser_ready,
                "reason": None if browser_ready else "Playwright 浏览器池未初始化",
            },
            "pptx-editable": {"available": True, "reason": None},
        }
    }


@router.post("/{presentation_id}/save-to-assets")
async def save_presentation_to_assets(
    presentation_id: str,
    session: AsyncSession = Depends(get_session),
):
    raise HTTPException(status_code=410, detail="PPT 原生导出已下线，保存至公共空间功能已停用")


@router.post("/{presentation_id}/workflows/native-pptx")
async def run_native_pptx_workflow(
    presentation_id: str,
    body: dict | None = None,
    session: AsyncSession = Depends(get_session),
):
    raise HTTPException(status_code=410, detail="PPT 原生 workflow 已下线")


async def _export_presentation_file(
    *,
    session: AsyncSession,
    presentation_id: str,
    export_format: str,
    slides: list[dict],
    title: str,
    theme_id: str,
) -> str:
    if export_format == "html":
        full_html = await ppt_service.build_full_html(session, presentation_id)
        if not full_html:
            raise HTTPException(status_code=500, detail="HTML 组装失败")
        return await export_service.export_html(full_html, title)

    if export_format == "pdf":
        full_html = await ppt_service.build_full_html(session, presentation_id)
        if not full_html:
            raise HTTPException(status_code=500, detail="HTML 组装失败")
        return await export_service.export_pdf(full_html, title)

    if export_format == "pptx-faithful":
        full_html = await ppt_service.build_full_html(session, presentation_id)
        if not full_html:
            raise HTTPException(status_code=500, detail="HTML 组装失败")
        return await export_service.export_pptx_faithful(full_html, title, len(slides))

    if export_format == "pptx-editable":
        return await export_service.export_pptx_editable(slides, title, theme_id)

    raise HTTPException(status_code=400, detail=f"格式 {export_format} 暂未实现")
