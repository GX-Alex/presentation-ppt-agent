"""
PDF 解析 API 路由模块

本模块定义了银行流水 PDF/图片解析相关的 HTTP 接口，由 main.py 挂载到 /api/v1/parse。

接口：
1. POST /detect     — 检测文件总页数（及类型标签，仅用于前端展示）
2. POST /parse     — 解析 PDF 或图片银行流水
3. POST /parse-page — 解析单页（用于失败页重试）

解析逻辑（统一）：
- 图片文件：直接读入图片字节，按页调用视觉模型。
- PDF 文件：一律先 convert_pages_to_images 转成 PNG，再按页调用视觉模型。
  不区分文本型/扫描型，所有 PDF 均通过「转图 → 视觉模型」同一条路径解析。
多页时：首页用完整 prompt（含表头），后续页用继承表头 prompt。单页失败重试 3 次。
"""

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.parsers.pdf_parser import PdfAnalyzer, filter_non_transaction_rows
from app.parsers.prompts import (
    DEFAULT_VL_PARSE_PROMPT,
    DEFAULT_VL_PARSE_PROMPT_FOLLOWING_PAGE,
    VL_PARSE_MULTI_IMAGE_PROMPT,
)
from app.providers import get_provider
from app.utils import maybe_compress_image, validate_statement_file_path, is_image_path

logger = logging.getLogger(__name__)
router = APIRouter()

# 模型调用失败时重试次数：重试 3 次后仍失败才算该页真正失败
MODEL_CALL_MAX_RETRIES = 3
# 重试间隔基数（秒），指数退避：1s, 2s, 4s
RETRY_DELAY_BASE = 1.0
# 单文件内并行解析的页数上限
PARSE_PAGE_PARALLELISM = 6

def _compress_threshold() -> int:
    return getattr(settings, "image_compress_threshold", 0) or 0


# ============================================================================
# 请求/响应模型
# ============================================================================


class DetectRequest(BaseModel):
    """检测请求"""
    file_path: str = Field(..., description="文件绝对路径")


class ParseRequest(BaseModel):
    """解析请求"""
    file_path: str = Field(..., description="文件绝对路径")
    pages: Optional[list[int]] = Field(None, description="指定页码列表，为空则解析全部")
    callback_url: Optional[str] = Field(None, description="进度回调 URL（预留）")
    prompt_content: Optional[str] = Field(None, description="自定义 Prompt 内容（来自模版），为空则用默认")
    prompt_following: Optional[str] = Field(None, description="后续页 Prompt（无表头场景），为空则用默认")


class ParsePageRequest(BaseModel):
    """单页解析请求"""
    file_path: str = Field(..., description="文件绝对路径")
    page_number: int = Field(..., ge=1, description="页码（从 1 开始）")
    prompt_content: Optional[str] = Field(None, description="首页 Prompt，为空则用默认")
    prompt_following: Optional[str] = Field(None, description="后续页 Prompt，为空则用默认")


class ParseMultiRequest(BaseModel):
    """多文件一次性解析请求"""
    file_paths: list[str] = Field(..., description="文件绝对路径列表")
    prompt_content: Optional[str] = Field(None, description="自定义 Prompt，为空则用多图专用默认")


# ============================================================================
# API 实现
# ============================================================================


@router.post(
    "/detect",
    summary="检测文件",
    description="获取文件总页数及类型标签（仅展示用）；解析时所有 PDF 均转图再识别",
)
async def detect_file(request: DetectRequest) -> dict:
    """
    返回总页数和类型标签（pdfType 仅用于前端展示，解析流程不据此分支）。
    图片：totalPages=1, pdfType=SCANNED。PDF：detect_pdf_type 得到 total_pages 与 pdf_type。
    """
    if not validate_statement_file_path(request.file_path):
        raise HTTPException(status_code=400, detail="文件路径无效或格式不支持")

    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info("[detect] 检测开始 | file_path=%s", request.file_path)
    try:
        if is_image_path(request.file_path):
            logger.info("[detect] 检测完成 | file_path=%s | totalPages=1 | pdfType=SCANNED", request.file_path)
            return {"totalPages": 1, "pdfType": "SCANNED"}
        result = PdfAnalyzer.detect_pdf_type(request.file_path)
        total_pages = result.get("total_pages", 0)
        pdf_type = result.get("pdf_type", "UNKNOWN")
        logger.info("[detect] 检测完成 | file_path=%s | totalPages=%d | pdfType=%s", request.file_path, total_pages, pdf_type)
        return {"totalPages": total_pages, "pdfType": pdf_type}
    except Exception as e:
        logger.exception("[detect] 检测失败 | file_path=%s | error=%s", request.file_path, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/parse",
    summary="解析流水",
    description="解析 PDF 或图片银行流水；PDF 一律先转图再按页调用视觉模型",
)
async def parse_pdf(request: ParseRequest) -> dict:
    """
    解析 PDF 或图片。图片直接读入；PDF 先 convert_pages_to_images 转成 PNG，再逐页 parse_image_page。
    多页时首页用完整 prompt，后续页继承表头。
    """
    if not validate_statement_file_path(request.file_path):
        raise HTTPException(status_code=400, detail="文件路径无效或格式不支持")

    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info("[parse] 解析开始 | file_path=%s | pages=%s", request.file_path, request.pages)
    ai_provider = get_provider()
    all_transactions = []
    errors = []
    parsed_count = 0

    try:
        if is_image_path(request.file_path):
            with open(request.file_path, "rb") as f:
                image_bytes = f.read()
            image_bytes, mime_type = maybe_compress_image(
                image_bytes, request.file_path, threshold=_compress_threshold()
            )
            images = [image_bytes]
            total_pages = 1
            logger.info("[parse] 图片文件 | file_path=%s | 共 1 张", request.file_path)
        else:
            # 所有 PDF 均转图后再解析，不区分文本型/扫描型
            pages = request.pages
            images = PdfAnalyzer.convert_pages_to_images(request.file_path, pages=pages)
            total_pages = len(images)
            logger.info("[parse] PDF 转图完成 | file_path=%s | 共 %d 张图片", request.file_path, total_pages)
            mime_type = "image/png"  # PDF 转出的为 PNG
            # PDF 转图可能很大，压缩后发送避免 base64 超 API 20M 限制
            images = [
                maybe_compress_image(img, None, mime_type, threshold=_compress_threshold())[0]
                for img in images
            ]

        if not images:
            return {
                "transactions": [],
                "totalPages": total_pages,
                "parsedPages": 0,
                "errors": ["未提取到有效页面"],
            }

        # 第一页使用完整 prompt（含表头识别），后续页使用继承表头的 prompt
        prompt_first = request.prompt_content or DEFAULT_VL_PARSE_PROMPT
        prompt_following = request.prompt_following or DEFAULT_VL_PARSE_PROMPT_FOLLOWING_PAGE

        async def parse_one_page(
            page_num: int,
            image_bytes: bytes,
            prompt: str,
            sem: asyncio.Semaphore,
        ) -> tuple[int, list[dict], dict | None, str | None]:
            """解析单页（带重试），返回 (page_num, txs, meta, error_msg)。在 sem 控制下并行。"""
            async with sem:
                last_error = None
                for attempt in range(1, MODEL_CALL_MAX_RETRIES + 2):
                    try:
                        txs, meta = await PdfAnalyzer.parse_image_page(
                            image_bytes, ai_provider, prompt, mime_type=mime_type
                        )
                        return (page_num, txs, meta, None)
                    except Exception as e:
                        last_error = e
                        logger.warning(
                            "[parse] 第 %d 页解析失败 第 %d/%d 次 | file_path=%s | error=%s",
                            page_num, attempt, MODEL_CALL_MAX_RETRIES + 1, request.file_path, str(e),
                        )
                        if attempt <= MODEL_CALL_MAX_RETRIES:
                            delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                            await asyncio.sleep(delay)
                err_msg = f"第 {page_num} 页解析失败（已重试 {MODEL_CALL_MAX_RETRIES} 次）: {str(last_error)}"
                return (page_num, [], None, err_msg)

        sem = asyncio.Semaphore(min(PARSE_PAGE_PARALLELISM, total_pages))
        tasks = [
            parse_one_page(
                page_idx + 1,
                image_bytes,
                prompt_first if page_idx == 0 else prompt_following,
                sem,
            )
            for page_idx, image_bytes in enumerate(images)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        # 按页码排序后合并，保证顺序一致
        results.sort(key=lambda r: r[0])
        first_page_metadata = None
        for page_num, txs, meta, err_msg in results:
            if err_msg:
                errors.append(err_msg)
                logger.warning(
                    "[parse] 单页解析最终失败 | page=%d | file_path=%s | error=%s",
                    page_num, request.file_path, err_msg,
                )
                continue
            if page_num == 1 and meta:
                first_page_metadata = meta
            for t in txs:
                t["pageNumber"] = page_num
            all_transactions.extend(txs)
            parsed_count += 1

        # 余额校验
        all_transactions = PdfAnalyzer.ensure_balance_ok(all_transactions)

        # 转换为 Java 后端期望的格式（camelCase），兼容 tx_date/tx_time
        tx_list = [_to_camel_tx(t) for t in all_transactions]

        result = {
            "transactions": tx_list,
            "totalPages": total_pages,
            "parsedPages": parsed_count,
            "errors": errors,
        }
        if first_page_metadata:
            result["metadata"] = first_page_metadata
        logger.info(
            "[parse] 解析完成 | file_path=%s | total_pages=%d | parsed=%d | transactions=%d | errors=%d",
            request.file_path, total_pages, parsed_count, len(tx_list), len(errors),
        )
        return result
    except Exception as e:
        logger.exception("[parse] 解析失败 | file_path=%s | error=%s", request.file_path, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/parse-page",
    summary="解析单页",
    description="解析 PDF 单页或图片，用于失败重试",
)
async def parse_single_page(request: ParsePageRequest) -> dict:
    """解析指定单页"""
    if not validate_statement_file_path(request.file_path):
        raise HTTPException(status_code=400, detail="文件路径无效或格式不支持")

    if not os.path.exists(request.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    logger.info("[parse-page] 单页解析开始 | file_path=%s | page_number=%d", request.file_path, request.page_number)
    ai_provider = get_provider()

    try:
        if is_image_path(request.file_path):
            if request.page_number != 1:
                raise HTTPException(status_code=400, detail="图片文件仅有一页")
            with open(request.file_path, "rb") as f:
                image_bytes = f.read()
            image_bytes, mime_type = maybe_compress_image(
                image_bytes, request.file_path, threshold=_compress_threshold()
            )
        else:
            # PDF 转该页为图后再解析
            images = PdfAnalyzer.convert_pages_to_images(
                request.file_path, pages=[request.page_number]
            )
            if not images:
                raise HTTPException(status_code=400, detail="指定页码超出范围")
            logger.info("[parse-page] PDF 转图完成 | file_path=%s | 第 %d 页", request.file_path, request.page_number)
            image_bytes, mime_type = maybe_compress_image(
                images[0], None, "image/png", threshold=_compress_threshold()
            )

        logger.info("[parse-page] 开始解析第 %d 张 | file_path=%s", request.page_number, request.file_path)
        prompt_first = request.prompt_content or DEFAULT_VL_PARSE_PROMPT
        prompt_following = request.prompt_following or DEFAULT_VL_PARSE_PROMPT_FOLLOWING_PAGE
        prompt = prompt_first if request.page_number == 1 else prompt_following

        last_error = None
        for attempt in range(1, MODEL_CALL_MAX_RETRIES + 2):
            try:
                txs, meta = await PdfAnalyzer.parse_image_page(
                    image_bytes, ai_provider, prompt, mime_type=mime_type
                )
                break
            except Exception as e:
                last_error = e
                logger.warning(
                    "[parse-page] 第 %d 页解析失败 第 %d/%d 次 | file_path=%s | error=%s",
                    request.page_number, attempt, MODEL_CALL_MAX_RETRIES + 1, request.file_path, str(e),
                )
                if attempt <= MODEL_CALL_MAX_RETRIES:
                    delay = RETRY_DELAY_BASE * (2 ** (attempt - 1))
                    logger.info("[parse-page] 等待 %.1f 秒后重试...", delay)
                    await asyncio.sleep(delay)
        else:
            logger.error(
                "[parse-page] 第 %d 页解析最终失败（已重试 %d 次）| file_path=%s | error=%s",
                request.page_number, MODEL_CALL_MAX_RETRIES, request.file_path, str(last_error),
            )
            raise HTTPException(
                status_code=500,
                detail=f"第 {request.page_number} 页解析失败（已重试 {MODEL_CALL_MAX_RETRIES} 次）: {last_error}",
            )

        txs = PdfAnalyzer.ensure_balance_ok(txs)
        for t in txs:
            t["pageNumber"] = request.page_number
        tx_list = [_to_camel_tx(t) for t in txs]

        logger.info("[parse-page] 第 %d 张解析完成 | file_path=%s | transactions=%d", request.page_number, request.file_path, len(tx_list))
        result = {
            "transactions": tx_list,
            "totalPages": 1,
            "parsedPages": 1,
            "errors": [],
        }
        if request.page_number == 1 and meta:
            result["metadata"] = meta
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[parse-page] 单页解析失败 | file_path=%s | error=%s", request.file_path, str(e))
        raise HTTPException(status_code=500, detail=str(e))


def _collect_images_with_meta(
    file_paths: list[str],
) -> tuple[list[tuple[int, int, bytes]], list[int]]:
    """
    将多个文件转为图片列表，返回 (file_idx, page_num, image_bytes) 及每文件页数。
    """
    all_images: list[tuple[int, int, bytes]] = []
    pages_per_file: list[int] = []

    for file_idx, path in enumerate(file_paths):
        if not validate_statement_file_path(path):
            logger.warning("[parse-multi] 跳过无效路径 | path=%s", path)
            pages_per_file.append(0)
            continue
        if not os.path.exists(path):
            logger.warning("[parse-multi] 文件不存在 | path=%s", path)
            pages_per_file.append(0)
            continue

        if is_image_path(path):
            with open(path, "rb") as f:
                img = f.read()
            img, _ = maybe_compress_image(img, path, threshold=_compress_threshold())
            all_images.append((file_idx, 1, img))
            pages_per_file.append(1)
        else:
            # PDF 一律转图
            images = PdfAnalyzer.convert_pages_to_images(path)
            for page_num, img in enumerate(images, 1):
                img, _ = maybe_compress_image(
                    img, None, "image/png", threshold=_compress_threshold()
                )
                all_images.append((file_idx, page_num, img))
            pages_per_file.append(len(images))

    return all_images, pages_per_file


def _to_camel_tx(t: dict) -> dict:
    """转换为 Java 后端期望的 camelCase 格式。tx_date 仅日期，tx_time 单独传；透传 pageNumber、seq_no 等扩展字段。"""
    date_val = t.get("tx_date") or t.get("date")
    tx_time = t.get("tx_time")
    if date_val and isinstance(date_val, str):
        date_val = date_val.strip()
        # 若模型返回「日期+时间」合一格式，拆成 tx_date 与 tx_time，避免 tx_time 全为空
        if " " in date_val:
            parts = date_val.split(" ", 1)
            date_val = parts[0]
            if not (tx_time and isinstance(tx_time, str) and tx_time.strip() and tx_time.lower() != "null"):
                tx_time = parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
    if tx_time and isinstance(tx_time, str) and tx_time.strip() and tx_time.lower() != "null":
        tx_time = tx_time.strip()
    else:
        tx_time = None
    base = {
        "tx_date": date_val,
        "summary": t.get("summary"),
        "counterparty": t.get("counterparty"),
        "income": t.get("income"),
        "expense": t.get("expense"),
        "balance": t.get("balance"),
        "isBalanceOk": t.get("is_balance_ok", True),
    }
    if tx_time:
        base["txTime"] = tx_time
    # 透传扩展字段（序号、页码、交易户名等）
    skip = {"date", "tx_date", "summary", "counterparty", "income", "expense", "balance", "is_balance_ok", "tx_time"}
    for k, v in t.items():
        if k not in skip and v is not None:
            base[k] = v
    return base


@router.post(
    "/parse-multi",
    summary="多文件一次性解析",
    description="将多个文件的图片一次性传入大模型，按 sourceIndex 分组返回，减少调用次数",
)
async def parse_multi(request: ParseMultiRequest) -> dict:
    """
    多文件一次性解析

    将多个 PDF/图片转为图片列表，按 max_images_per_request 分批调用 vision_multi，
    返回按文件分组的解析结果，供 Java 后端按 file_id 分别写入。
    """
    if not request.file_paths:
        raise HTTPException(status_code=400, detail="file_paths 不能为空")

    logger.info("[parse-multi] 多文件解析开始 | file_count=%d | paths=%s", len(request.file_paths), request.file_paths[:3])
    all_images, pages_per_file = _collect_images_with_meta(request.file_paths)
    if not all_images:
        return {
            "results": [],
            "errors": ["未提取到有效图片"],
        }

    prompt = request.prompt_content or VL_PARSE_MULTI_IMAGE_PROMPT
    max_per = settings.max_images_per_request
    ai_provider = get_provider()

    # 按文件聚合：file_idx -> [(page_num, transactions, metadata), ...]
    file_results: dict[int, list[tuple[int, list[dict], dict | None]]] = {
        i: [] for i in range(len(request.file_paths))
    }
    errors: list[str] = []

    # 分批调用
    for batch_start in range(0, len(all_images), max_per):
        batch = all_images[batch_start : batch_start + max_per]
        batch_images = [img for (_, _, img) in batch]
        batch_meta = [(fi, pn) for (fi, pn, _) in batch]

        try:
            response = await ai_provider.vision_multi(prompt, batch_images)
            parsed = PdfAnalyzer._extract_json_raw(response)
            if parsed is None:
                errors.append(f"批次 {batch_start // max_per + 1} 返回格式无效")
                continue
            # 兼容：单对象 {"transactions":[...],"metadata":{...}} 视为 sourceIndex=0
            if isinstance(parsed, dict):
                if "transactions" in parsed:
                    parsed = [{"sourceIndex": 0, **parsed}]
                else:
                    errors.append(f"批次 {batch_start // max_per + 1} 返回格式无效")
                    continue
            if not isinstance(parsed, list):
                errors.append(f"批次 {batch_start // max_per + 1} 返回格式无效")
                continue

            for item in parsed:
                if not isinstance(item, dict):
                    continue
                si = item.get("sourceIndex")
                txs = item.get("transactions") or []
                meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
                if si is None or si < 0 or si >= len(batch_meta):
                    continue
                file_idx, page_num = batch_meta[si]
                for t in txs:
                    if isinstance(t, dict):
                        t["pageNumber"] = page_num
                file_results[file_idx].append((page_num, txs, meta))

        except Exception as e:
            err_msg = f"批次 {batch_start // max_per + 1} 解析失败: {str(e)}"
            errors.append(err_msg)
            logger.warning("[parse-multi] 批次解析失败 | batch=%d | error=%s", batch_start // max_per + 1, str(e))

    # 按文件聚合交易、按 page 排序、余额校验、提取 metadata
    results = []
    for file_idx in range(len(request.file_paths)):
        page_data = file_results.get(file_idx, [])
        page_data.sort(key=lambda x: x[0])
        all_txs = []
        file_metadata = None
        for _, txs, meta in page_data:
            all_txs.extend(txs)
            if file_metadata is None and meta:
                file_metadata = meta

        for t in all_txs:
            for key in ("income", "expense", "balance"):
                val = t.get(key)
                if val is not None:
                    try:
                        t[key] = float(val)
                    except (ValueError, TypeError):
                        t[key] = None

        all_txs = filter_non_transaction_rows(all_txs)
        all_txs = PdfAnalyzer.ensure_balance_ok(all_txs)
        tx_list = [_to_camel_tx(t) for t in all_txs]

        result_item = {
            "fileIndex": file_idx,
            "transactions": tx_list,
            "totalPages": pages_per_file[file_idx] if file_idx < len(pages_per_file) else 0,
            "parsedPages": len(page_data),
        }
        if file_metadata:
            result_item["metadata"] = file_metadata
        results.append(result_item)

    total_txs = sum(len(r["transactions"]) for r in results)
    logger.info(
        "[parse-multi] 多文件解析完成 | file_count=%d | total_transactions=%d | errors=%d",
        len(results), total_txs, len(errors),
    )
    return {
        "results": results,
        "errors": errors,
    }
