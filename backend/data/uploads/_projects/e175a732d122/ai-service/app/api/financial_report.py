"""
财报解析 API：解析客户上传的财报（PDF/图片），输出 Markdown，用于与流水联合分析。
"""
import logging
import os
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.parsers.pdf_parser import PdfAnalyzer
from app.parsers.prompts import FINANCIAL_REPORT_PARSE_PROMPT
from app.providers import get_provider
from app.utils import maybe_compress_image, validate_statement_file_path, is_image_path

logger = logging.getLogger(__name__)
router = APIRouter()

_REPORT_PERIOD_PATTERN = re.compile(
    r"报告期[：:]\s*([\d\-]+|[\d]{4}-Q\d)", re.IGNORECASE
)


def _compress_threshold() -> int:
    return getattr(settings, "image_compress_threshold", 0) or 0


def _extract_report_period(markdown: str) -> str | None:
    """从 Markdown 文本中提取报告期"""
    if not markdown or not markdown.strip():
        return None
    m = _REPORT_PERIOD_PATTERN.search(markdown)
    return m.group(1).strip() if m else None


class ParseFinancialReportRequest(BaseModel):
    file_path: str = Field(..., description="文件绝对路径")
    report_type: str | None = Field(None, description="INCOME_STATEMENT/BALANCE_SHEET，不传则自动识别")
    prompt_content: str | None = Field(None, description="财报解析 Prompt，来自 prompt_template，不传则用默认")


@router.post("/parse", summary="解析财报")
async def parse_financial_report(request: ParseFinancialReportRequest) -> dict:
    """解析客户上传的财报（支持 PDF、JPG、PNG），输出 Markdown 格式完整内容，用于与流水联合分析"""
    if not validate_statement_file_path(request.file_path):
        raise HTTPException(status_code=400, detail="文件路径无效或格式不支持")
    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    prompt = (request.prompt_content or "").strip() or FINANCIAL_REPORT_PARSE_PROMPT
    logger.info("[financial-report] 解析开始 | file_path=%s | report_type=%s", request.file_path, request.report_type)
    provider = get_provider()
    th = _compress_threshold()
    try:
        if is_image_path(request.file_path):
            with open(request.file_path, "rb") as f:
                img, mime = maybe_compress_image(f.read(), request.file_path, threshold=th)
        else:
            images = PdfAnalyzer.convert_pages_to_images(request.file_path)
            img, mime = (
                maybe_compress_image(images[0], None, "image/png", threshold=th)
                if images
                else (None, "image/png")
            )

        if img is None:
            raise HTTPException(status_code=400, detail="未提取到有效页面")

        # 取第一页解析，输出 Markdown
        response = await provider.vision(prompt, img, mime_type=mime)
        content = (response or "").strip()
        if not content:
            raise HTTPException(status_code=500, detail="解析结果为空")

        report_period = _extract_report_period(content)
        result = {
            "content": content,
            "report_period": report_period,
        }
        logger.info("[financial-report] 解析完成 | file_path=%s | report_period=%s", request.file_path, report_period)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[financial-report] 解析失败 | file_path=%s | error=%s", request.file_path, str(e))
        raise HTTPException(status_code=500, detail=str(e))
