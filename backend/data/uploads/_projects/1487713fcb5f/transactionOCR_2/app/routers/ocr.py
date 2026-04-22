"""
/ocr 路由 — 接收上游 POST 请求，立即回应受理，后台异步处理完成后主动回调上游
"""
import asyncio
import base64
import logging
from pathlib import Path
from typing import List

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse

from app.models import OCRAckResponse, OCRCallbackPayload, OCRRequest, OCRResponse
from app.config import CALLBACK_URL, MAX_WORKERS, CHUNK_SIZE, RETRY_COUNT, RETRY_DELAY, BALANCE_CORRECTION_TOLERANCE, MAX_CHUNK_WORKERS, REQUEST_TIMEOUT
from app.services.url_fixer import extract_remote_urls
from app.services.file_handler import (
    detect_file_type,
    download_file,
    pdf_to_images,
    image_to_base64_url,
)
from app.services.ocr_agent import run_ocr_agent
from app.services.data_processor import (
    process_agent_result,
    merge_dataframes,
    dataframe_to_csv_string,
)
from app.services.balance_corrector import apply_balance_correction

import pandas as pd

logger = logging.getLogger("transaction_ocr")

router = APIRouter()

# CSV 文件落盘目录（静态文件服务通过 /downloads 路径暴露）
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)


def _save_csv(order_no: str, csv_string: str) -> str:
    """
    将 CSV 字符串保存到 downloads/{order_no}.csv，返回访问路径（/downloads/xxx.csv）。
    文件名中的非法字符替换为 _。
    """
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in order_no)
    file_path = DOWNLOADS_DIR / f"{safe_name}.csv"
    file_path.write_bytes(csv_string.encode("utf-8-sig"))
    return f"/downloads/{safe_name}.csv"


async def _do_callback(payload: OCRCallbackPayload) -> None:
    """
    处理完成后向上游固定回调地址 POST 结果（multipart/form-data 格式）。
    打印回调请求和响应的原始报文。
    CALLBACK_URL 为空时跳过回调。
    """
    if not CALLBACK_URL:
        logger.info("[Callback] CALLBACK_URL 未配置，跳过回调")
        return

    payload_dict = payload.model_dump()

    # 构造 multipart/form-data 字段
    # 文本字段：(None, 字符串值) → Content-Disposition: form-data; name="field"
    # 注意参数名映射：orderNO→orderNo, csvFile→file
    multipart_fields: dict = {
        "orderNo": (None, str(payload_dict.get("orderNO") or "")),
        "csvUrl": (None, str(payload_dict.get("csvUrl") or "")),
        "custName": (None, str(payload_dict.get("custName") or "")),
        "companyName": (None, str(payload_dict.get("companyName") or "")),
        "accountNo": (None, str(payload_dict.get("accountNo") or "")),
        "accountName": (None, str(payload_dict.get("accountName") or "")),
    }

    # file：base64 解码 → 作为 CSV 文件字段上传
    # Content-Disposition: form-data; name="file"; filename="result.csv"
    csv_b64 = payload_dict.get("csvFile") or ""
    if csv_b64:
        csv_bytes = base64.b64decode(csv_b64)
        multipart_fields["file"] = ("result.csv", csv_bytes, "text/csv")
        csv_desc = f"<CSV 文件 {len(csv_bytes)} bytes>"
    else:
        multipart_fields["file"] = ("result.csv", b"", "text/csv")
        csv_desc = "<空>"

    import json
    log_info = {
        k: (csv_desc if k == "file" else v[1])
        for k, v in multipart_fields.items()
    }
    logger.info(
        "[Callback] 回调请求报文(multipart/form-data) → %s\n%s",
        CALLBACK_URL,
        json.dumps(log_info, ensure_ascii=False, indent=2),
    )

    # 超时配置：连接10秒，读取60秒，写入60秒，池10秒
    # 关闭长连接复用，避免 F5 断连坑
    timeout = httpx.Timeout(
        connect=10.0,
        read=60.0,
        write=60.0,
        pool=10.0,
    )
    limits = httpx.Limits(
        max_keepalive_connections=0,
        max_connections=50,
    )

    # 重试配置：第1次1秒，第2次3秒，第3次5秒
    retry_delays = [1, 3, 5]

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                limits=limits,
                follow_redirects=True,
            ) as client:
                resp = await client.post(CALLBACK_URL, files=multipart_fields)
            # 收到响应，判断成功/失败
            if resp.status_code < 400:
                logger.info("[Callback] 回调成功(第%d次): status=%d", attempt + 1, resp.status_code)
            else:
                logger.error("[Callback] 回调失败(第%d次): status=%d, body=%s", attempt + 1, resp.status_code, resp.text[:500])
            return  # 收到响应，无论成功失败都停止重试
        except Exception as e:
            if attempt < 2:
                logger.warning("[Callback] 回调失败(第%d次): %s, %d秒后重试", attempt + 1, e, retry_delays[attempt])
                await asyncio.sleep(retry_delays[attempt])
            else:
                logger.error("[Callback] 回调彻底失败(共重试3次): %s", e, exc_info=True)


async def _process_single_image(
    image_url: str,
    account_no: str = "",
    account_name: str = "",
    order_no: str = "",
    idx: int = 0,
) -> dict:
    """
    处理单张图片：调用 Agent → 解析结果 → 返回 DataFrame。

    Args:
        image_url: 图片 URL 或 base64 data URL
        account_no: 关联账户号
        account_name: 关联账户名
        idx: 序号（用于日志）

    Returns:
        {"success": bool, "df": DataFrame|None, "url": str, "reason": str}
    """
    try:
        logger.info("[图片 %d] 开始 Agent 提取 (URL 长度: %d 字符)", idx, len(image_url))

        agent_result = await run_ocr_agent([image_url])
        if agent_result is None:
            return {
                "success": False,
                "df": None,
                "url": image_url,
                "reason": "Agent 返回空结果",
            }

        df = process_agent_result(
            agent_json=agent_result,
            image_url=image_url,
            serial_no=order_no,
        )

        if df.empty:
            return {
                "success": False,
                "df": None,
                "url": image_url,
                "reason": "解析结果为空 DataFrame",
            }

        # 如果请求中带了 account_name 且 Agent 没提取到，则补上（account_id 由上游统一覆盖，不在此处处理）
        if account_name and ("name" in df.columns) and df["name"].isna().all():
            df["name"] = account_name

        return {"success": True, "df": df, "url": image_url, "reason": ""}

    except Exception as e:
        logger.error("[图片 %d] 处理失败: %s", idx, e, exc_info=True)
        return {
            "success": False,
            "df": None,
            "url": image_url,
            "reason": str(e),
        }


# ══════════════════════════════════════════════════════════════
#  PDF 分块并发辅助函数
# ══════════════════════════════════════════════════════════════

def _split_into_chunks(
    image_urls: list[str],
    chunk_size: int,
) -> list[tuple[int, list[str], bool]]:
    """
    将图片 URL 列表按 chunk_size 分组。

    Returns:
        list of (chunk_index, urls, header_only_first)
        - chunk 0: image_urls[0:chunk_size], header_only_first=False
        - chunk k≥1: [image_urls[0]] + image_urls[k*chunk_size:(k+1)*chunk_size],
                     header_only_first=True（携带第1页作为表头格式参考）
    """
    if len(image_urls) <= chunk_size:
        return [(0, image_urls, False)]

    chunks = []
    header_page = image_urls[0]
    for k, start in enumerate(range(0, len(image_urls), chunk_size)):
        batch = image_urls[start: start + chunk_size]
        if k == 0:
            chunks.append((0, batch, False))
        else:
            # 非首块：在数组最前面插入第1页作为表头格式参考
            chunks.append((k, [header_page] + batch, True))
    return chunks


async def _run_chunk_with_retry(
    chunk_index: int,
    image_urls: list[str],
    header_only_first: bool,
    skip_metadata: bool,
    account_no: str,
    account_name: str,
    order_no: str,
    _split_depth: int = 0,
) -> tuple[int, dict]:
    """
    带重试的单块处理。重试失败且系统性截断时，自动二分拆小后递归处理。

    _split_depth: 当前二分拆分深度，最多 MAX_SPLIT_DEPTH 层，防止无限递归。

    Returns:
        (chunk_index, {"success": bool, "df": DataFrame|None, "reason": str})
    """
    MAX_SPLIT_DEPTH = 2
    label = f"chunk-{chunk_index}" if _split_depth == 0 else f"chunk-{chunk_index}(split-{_split_depth})"
    last_reason = ""
    is_truncation = False

    for attempt in range(RETRY_COUNT + 1):
        try:
            if attempt > 0:
                logger.info("[%s] 第 %d 次重试，等待 %ds", label, attempt, RETRY_DELAY)
                await asyncio.sleep(RETRY_DELAY)

            logger.info(
                "[%s] 开始提取: %d 张图片  header_only_first=%s  skip_metadata=%s",
                label, len(image_urls), header_only_first, skip_metadata,
            )
            try:
                agent_result = await asyncio.wait_for(
                    run_ocr_agent(
                        image_urls,
                        header_only_first=header_only_first,
                        skip_metadata=skip_metadata,
                    ),
                    timeout=REQUEST_TIMEOUT + 10,
                )
            except asyncio.TimeoutError:
                last_reason = f"asyncio 层超时（>{REQUEST_TIMEOUT + 10}s），attempt={attempt}"
                logger.warning("[%s] %s", label, last_reason)
                continue
            if agent_result is None:
                last_reason = "Agent 返回空结果"
                logger.warning("[%s] Agent 返回空结果，attempt=%d", label, attempt)
                continue

            df = process_agent_result(
                agent_json=agent_result,
                image_url=f"{label}/{len(image_urls)}张图片",
                serial_no=order_no,
            )
            if df.empty:
                last_reason = "解析结果为空 DataFrame"
                logger.warning("[%s] 解析结果为空，attempt=%d", label, attempt)
                continue

            # 最低行数校验：防止 API 截断响应被误判为成功
            # ⚠️ 只对 transaction_imgs >= 2 的多页块做检测：
            #   - 单页块（transaction_imgs == 1）是原子操作，不可能被上下文截断，
            #     若做阈值检测且无法二分，会导致数据静默丢失（如 PDF 最后一页只有 1-2 行）
            # depth=0（首次）：严格阈值每页 3 行，检测真正的上下文截断
            # depth>0（子块）：宽松阈值每页 1 行，子块是 recovery 路径，
            #   文档密度低的页面不应再次触发假阳性截断，否则会连锁失败导致数据静默丢失
            transaction_imgs = len(image_urls) - (1 if header_only_first else 0)
            if transaction_imgs >= 2:
                rows_per_img = 3 if _split_depth == 0 else 1
                min_expected_rows = transaction_imgs * rows_per_img
                if len(df) < min_expected_rows:
                    last_reason = (
                        f"行数过少({len(df)} < 预期最低{min_expected_rows})，"
                        f"可能是API截断响应(每张图最少{rows_per_img}行)"
                    )
                    logger.warning("[%s] %s，attempt=%d", label, last_reason, attempt)
                    is_truncation = True
                    continue

            # account_id 由上游统一覆盖，不在此处处理
            # chunk-0：用传参 account_name 作为最终兜底（PDF 真实名称优先）
            # chunk-1+：不在此处填充，留 NaN 交给 _process_image_array 的元数据传播统一处理
            #           确保所有 chunk 使用同一份 meta_name（来自 chunk-0 的 PDF 提取结果）
            if chunk_index == 0 and account_name and ("name" in df.columns) and df["name"].isna().all():
                df["name"] = account_name

            logger.info("[%s] 提取成功: %d 行", label, len(df))
            return (chunk_index, {"success": True, "df": df, "reason": ""})

        except Exception as e:
            last_reason = str(e)
            logger.error("[%s] 处理失败 attempt=%d: %s", label, attempt, e, exc_info=True)

    # ── 全部重试失败后：若系统性截断且可继续拆分，二分处理 ──
    # 重试解决偶发网络抖动；二分解决上下文窗口导致的系统性截断
    if is_truncation and _split_depth < MAX_SPLIT_DEPTH:
        # 拆出表头页和事务页
        header_pages = [image_urls[0]] if header_only_first else []
        txn_pages = image_urls[1:] if header_only_first else image_urls[:]

        if len(txn_pages) >= 2:
            mid = len(txn_pages) // 2
            halves = [txn_pages[:mid], txn_pages[mid:]]
            logger.info(
                "[%s] 系统性截断，二分为 %d/%d 张事务页分别重试 (split_depth=%d→%d)",
                label, len(halves[0]), len(halves[1]), _split_depth, _split_depth + 1,
            )
            sub_dfs: list[pd.DataFrame] = []
            for half in halves:
                sub_urls = header_pages + half
                _, sub_result = await _run_chunk_with_retry(
                    chunk_index=chunk_index,
                    image_urls=sub_urls,
                    header_only_first=header_only_first,
                    skip_metadata=skip_metadata,
                    account_no=account_no,
                    account_name=account_name,
                    order_no=order_no,
                    _split_depth=_split_depth + 1,
                )
                if sub_result["success"] and sub_result["df"] is not None:
                    sub_dfs.append(sub_result["df"])

            if sub_dfs:
                merged = pd.concat(sub_dfs, ignore_index=True)
                # 二分合并后去重：基于第一个 half 的指纹移除重复行
                if len(sub_dfs) > 1:
                    fingerprints = _build_dedup_fingerprints(sub_dfs[0])
                    merged = _dedup_by_fingerprints(merged, fingerprints, chunk_index)
                logger.info("[%s] 二分合并完成: %d 行", label, len(merged))
                return (chunk_index, {"success": True, "df": merged, "reason": ""})

    logger.error("[%s] 全部 %d 次尝试均失败: %s", label, RETRY_COUNT + 1, last_reason)
    return (chunk_index, {"success": False, "df": None, "reason": last_reason})


def _build_dedup_fingerprints(df: "pd.DataFrame") -> list:
    """
    从 chunk 0 的 DataFrame 构建去重指纹列表。
    指纹 = (trans_date, trans_time, trans_amt, account_balance)，NaN 统一转 ''。
    全部字段均为空的行不加入指纹集合（避免空行互相干扰）。
    """
    fingerprints: list = []
    cols = ["trans_date", "trans_time", "trans_amt", "account_balance"]
    for _, row in df.iterrows():
        key = tuple(
            str(row[c]).strip() if c in df.columns and pd.notna(row.get(c)) else ""
            for c in cols
        )
        if any(v != "" for v in key):  # 至少一个字段非空才加入指纹
            fingerprints.append(key)
    return fingerprints


def _dedup_by_fingerprints(df: "pd.DataFrame", fingerprints: list, chunk_index: int) -> "pd.DataFrame":
    """
    从 df 中移除与 fingerprints 中匹配的行（去除第1页重复提取的数据）。
    匹配规则：4字段中至少3个相同即视为重复。
    全部指纹字段均为空的行跳过检查，不删除。
    """
    cols = ["trans_date", "trans_time", "trans_amt", "account_balance"]
    before = len(df)

    def _count_matching_fields(row_key, fp_key):
        """统计两个元组中相同字段的数量"""
        return sum(1 for a, b in zip(row_key, fp_key) if a == b)

    def _is_duplicate(row):
        row_key = tuple(
            str(row[c]).strip() if c in df.columns and pd.notna(row.get(c)) else ""
            for c in cols
        )
        if not any(v != "" for v in row_key):
            return False  # 全空行，不删除
        # 检查是否与指纹库中任意一项有 >=3 个字段相同
        for fp_key in fingerprints:
            if _count_matching_fields(row_key, fp_key) >= 3:
                return True
        return False

    mask = df.apply(_is_duplicate, axis=1)
    result = df[~mask].reset_index(drop=True)
    removed = before - len(result)
    if removed > 0:
        logger.info("[chunk-%d] 去重 %d 行（3/4字段重复）", chunk_index, removed)
    return result


async def _process_image_array(
    image_urls: list[str],
    account_no: str = "",
    account_name: str = "",
    order_no: str = "",
    label: str = "image_array",
) -> dict:
    """
    将图片 URL 数组发送给 VLM 提取交易记录。
    - 当图片数 ≤ CHUNK_SIZE 时，单次请求（原有逻辑）。
    - 当图片数 > CHUNK_SIZE 时，按 CHUNK_SIZE 分块并发处理：
      * 非首块携带第1页作为表头格式参考（header_only_first=True）
      * 非首块跳过元数据提取（skip_metadata=True）
      * 合并时按 chunk_index 顺序排列
      * 对非首块结果做指纹去重，移除第1页重复行
    """
    if not image_urls:
        return {"success": False, "df": None, "url": "", "reason": "图片列表为空"}

    chunks = _split_into_chunks(image_urls, CHUNK_SIZE)

    # ── 单块路径：与原有逻辑等价 ──
    if len(chunks) == 1:
        chunk_index, urls, header_only_first = chunks[0]
        _, result = await _run_chunk_with_retry(
            chunk_index=0,
            image_urls=urls,
            header_only_first=False,
            skip_metadata=False,
            account_no=account_no,
            account_name=account_name,
            order_no=order_no,
        )
        result["url"] = urls[0] if urls else ""
        return result

    # ── 多块并发路径 ──
    logger.info(
        "[%s] PDF 分块处理: %d 页 → %d 块并发 (CHUNK_SIZE=%d)",
        label, len(image_urls), len(chunks), CHUNK_SIZE,
    )

    _chunk_sem = asyncio.Semaphore(MAX_CHUNK_WORKERS)

    async def _run_with_sem(k, urls, hof):
        async with _chunk_sem:
            return await _run_chunk_with_retry(
                chunk_index=k,
                image_urls=urls,
                header_only_first=hof,
                skip_metadata=(k > 0),   # 非首块跳过元数据
                account_no=account_no,
                account_name=account_name,
                order_no=order_no,
            )

    tasks = [_run_with_sem(k, urls, hof) for k, urls, hof in chunks]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # 收集结果，Exception 视为失败
    chunk_results: list[tuple[int, dict]] = []
    for res in raw_results:
        if isinstance(res, Exception):
            logger.error("[%s] chunk gather 异常: %s", label, res)
        else:
            chunk_results.append(res)  # (chunk_index, result_dict)

    # 按 chunk_index 升序排列（保证原 PDF 顺序）
    chunk_results.sort(key=lambda x: x[0])

    successful = [(k, r) for k, r in chunk_results if r["success"] and r["df"] is not None]
    failed_count = len(chunks) - len(successful)

    if not successful:
        return {
            "success": False,
            "df": None,
            "url": image_urls[0],
            "reason": f"所有 {len(chunks)} 块均处理失败",
        }

    if failed_count > 0:
        logger.warning("[%s] %d/%d 块处理失败，继续合并成功块", label, failed_count, len(chunks))

    # 从 chunk 0 建立去重指纹集合
    chunk0_df = next((r["df"] for k, r in successful if k == 0), None)
    fingerprints: list = _build_dedup_fingerprints(chunk0_df) if chunk0_df is not None else []
    logger.info("[%s] chunk-0 指纹集合: %d 条", label, len(fingerprints))

    # 元数据传播：从 chunk 0 取 name / account_id / account_bank 填充其他块空列
    meta_name = ""
    meta_account_no = ""
    meta_bank = ""
    if chunk0_df is not None and not chunk0_df.empty:
        if "name" in chunk0_df.columns:
            meta_name = next((str(v) for v in chunk0_df["name"] if pd.notna(v) and str(v).strip()), "")
        if "account_no" in chunk0_df.columns:
            meta_account_no = next((str(v) for v in chunk0_df["account_no"] if pd.notna(v) and str(v).strip()), "")
        if "account_bank" in chunk0_df.columns:
            meta_bank = next((str(v) for v in chunk0_df["account_bank"] if pd.notna(v) and str(v).strip()), "")

    all_dfs = []
    for k, r in successful:
        df = r["df"]
        if k > 0:
            # 去重：移除与 chunk 0 重叠的行
            df = _dedup_by_fingerprints(df, fingerprints, k)

        # 元数据传播：对所有 chunk（含 chunk-0）的 NaN 行逐个填充
        # 统一用 astype(str) 比较，避免 float64 列 NaN 无法被 == '' 匹配
        if meta_name and "name" in df.columns:
            mask = df["name"].isna() | (df["name"].astype(str).str.strip() == '') | (df["name"].astype(str) == 'nan')
            df["name"] = df["name"].astype(object)
            df.loc[mask, "name"] = meta_name
        if meta_account_no and "account_no" in df.columns:
            mask = df["account_no"].isna() | (df["account_no"].astype(str).str.strip() == '') | (df["account_no"].astype(str) == 'nan')
            df["account_no"] = df["account_no"].astype(object)
            df.loc[mask, "account_no"] = meta_account_no
        if meta_bank and "account_bank" in df.columns:
            mask = df["account_bank"].isna() | (df["account_bank"].astype(str).str.strip() == '') | (df["account_bank"].astype(str) == 'nan')
            df["account_bank"] = df["account_bank"].astype(object)
            df.loc[mask, "account_bank"] = meta_bank

        if k > 0 and df.empty:
            logger.warning("[%s] chunk-%d 去重后为空，跳过", label, k)
            continue
        all_dfs.append(df)

    if not all_dfs:
        return {
            "success": False,
            "df": None,
            "url": image_urls[0],
            "reason": "所有块去重后均为空",
        }

    merged_df = merge_dataframes(all_dfs)
    logger.info("[%s] 分块合并完成: %d 块 → %d 行", label, len(all_dfs), len(merged_df))
    merged_df = apply_balance_correction(merged_df, tolerance=BALANCE_CORRECTION_TOLERANCE)
    return {"success": True, "df": merged_df, "url": image_urls[0], "reason": ""}


async def _process_single_url(url_info: dict, idx: int, total: int) -> list[dict]:
    """
    处理单个 URL：
    - 图片 → 直接调 Agent
    - PDF → 转图片数组 → 逐页调 Agent

    Returns:
        list[dict]: 每页/每张图的处理结果列表
    """
    url = url_info["url"]
    account_no = url_info["account_no"]
    account_name = url_info["account_name"]
    order_no = url_info["order_no"]

    logger.info("[%d/%d] 处理 URL: %s", idx, total, url[:120])

    file_type = detect_file_type(url)
    results = []

    if file_type == "pdf":
        # ── PDF：下载/解码 → 转图片 → 逐页 Agent ──
        try:
            # 如果是 data: URL，直接解码 base64
            if url.startswith("data:"):
                # data:application/pdf;base64,XXXXXX
                _, b64_data = url.split(",", 1)
                pdf_bytes = base64.b64decode(b64_data)
            else:
                pdf_bytes = await download_file(url)
            page_images = await asyncio.to_thread(pdf_to_images, pdf_bytes)
            logger.info("[%d/%d] PDF 共 %d 页", idx, total, len(page_images))

            # 将所有页面转为 data URL 数组，一次性发送给 VLM
            page_data_urls = [image_to_base64_url(img_bytes) for img_bytes in page_images]
            r = await _process_image_array(
                image_urls=page_data_urls,
                account_no=account_no,
                account_name=account_name,
                order_no=order_no,
                label=f"PDF({idx}/{total})",
            )
            results.append(r)

        except Exception as e:
            logger.error("[%d/%d] PDF 下载/转换失败: %s", idx, total, e, exc_info=True)
            results.append(
                {"success": False, "df": None, "url": url, "reason": str(e)}
            )

    else:
        # ── 图片：直接调 Agent（使用原始 URL） ──
        r = await _process_single_image(
            image_url=url,
            account_no=account_no,
            account_name=account_name,
            order_no=order_no,
            idx=idx,
        )
        results.append(r)

    return results


@router.post("/ocr", response_model=OCRAckResponse, summary="银行交易流水 OCR 提取")
async def ocr_extract(request: OCRRequest, background_tasks: BackgroundTasks):
    """
    接收上游请求后立即返回受理应答（202），后台异步处理并回调上游。

    流程：
    1. 校验 remoteUrls，立即返回 {orderNO, message}
    2. 后台任务：提取并修正 URL → 并发 OCR Agent → 合并 CSV → 落盘
    3. 完成后 POST 回调地址，报文含 csvUrl + csvFile(base64)
    """
    order_no = request.orderNO
    logger.info("=== 收到 OCR 请求 orderNO=%s，共 %d 个 URL ===",
                order_no, len(request.remoteUrls))

    # 快速预检查
    if not request.remoteUrls:
        raise HTTPException(status_code=400, detail="请求中没有有效的 remoteUrls")

    # 注册后台任务
    background_tasks.add_task(_background_process, request)

    # 立即返回受理应答
    return JSONResponse(
        status_code=202,
        content=OCRAckResponse(orderNO=order_no).model_dump(),
    )


async def _background_process(request: OCRRequest) -> None:
    """
    后台处理任务：完成全部 OCR 流程后回调上游。
    """
    order_no = request.orderNO
    logger.info("[BG:%s] 后台任务开始", order_no)

    # 1. 提取 URL
    url_infos = extract_remote_urls(
        request.remoteUrls,
        account_no=request.accountNo or "",
        account_name=request.accountName or "",
        order_no=order_no,
    )
    if not url_infos:
        logger.warning("[BG:%s] 没有有效 URL，回调失败结果", order_no)
        await _do_callback(OCRCallbackPayload(
            orderNO=order_no,
            custName=request.custName,
            companyName=request.companyName,
            accountNo=request.accountNo,
            accountName=request.accountName,
        ))
        return

    total = len(url_infos)
    logger.info("[BG:%s] 共 %d 个文件待处理", order_no, total)

    # 2. 区分 PDF 和图片，分别处理
    #    图片：将所有图片 URL 合并为一个数组，统一调用 _process_image_array
    #          → 仅首块提取 metadata，后续分块 skip_metadata=True，避免重复提取
    #    PDF：逐个处理（PDF 内部已有分块并发）
    pdf_infos = [info for info in url_infos if detect_file_type(info["url"]) == "pdf"]
    img_infos = [info for info in url_infos if detect_file_type(info["url"]) != "pdf"]
    logger.info("[BG:%s] PDF %d 个，图片 %d 张", order_no, len(pdf_infos), len(img_infos))

    all_url_results: list = []

    # PDF：并发处理（每个 PDF 内部已使用分块并发）
    if pdf_infos:
        pdf_sem = asyncio.Semaphore(MAX_WORKERS)

        async def process_pdf_with_sem(info, i):
            async with pdf_sem:
                return await _process_single_url(info, i, len(pdf_infos))

        pdf_results = await asyncio.gather(
            *[process_pdf_with_sem(info, i + 1) for i, info in enumerate(pdf_infos)],
            return_exceptions=True,
        )
        all_url_results.extend(pdf_results)

    # 图片：合并为一个数组，一次性调用 _process_image_array
    #       chunk-0 提取 metadata，后续分块自动 skip_metadata=True
    if img_infos:
        first = img_infos[0]
        logger.info("[BG:%s] 下载和转换 %d 张图片为 base64 data URL（统一提取，仅1次 metadata）", order_no, len(img_infos))
        
        # 下载图片 + 转为 base64 data URL（与 PDF 转图片后的处理逻辑保持一致）
        img_data_urls = []
        for i, info in enumerate(img_infos):
            raw_url = info["url"]
            try:
                # 如果已是 data URL，直接使用；否则下载后转为 base64
                if raw_url.startswith("data:"):
                    img_data_urls.append(raw_url)
                    logger.debug("[BG:%s] 图片 %d/%d 已是 data URL", order_no, i+1, len(img_infos))
                else:
                    img_bytes = await download_file(raw_url)
                    # 根据 URL 扩展名猜测 MIME 类型
                    mime_type = "image/png"
                    if ".jpg" in raw_url or ".jpeg" in raw_url:
                        mime_type = "image/jpeg"
                    elif ".gif" in raw_url:
                        mime_type = "image/gif"
                    elif ".webp" in raw_url:
                        mime_type = "image/webp"
                    img_data_url = image_to_base64_url(img_bytes, mime=mime_type)
                    img_data_urls.append(img_data_url)
                    logger.debug("[BG:%s] 图片 %d/%d 下载并转 base64 完成 (%s)", order_no, i+1, len(img_infos), mime_type)
            except Exception as e:
                logger.error("[BG:%s] 图片 %d/%d 下载失败: %s", order_no, i+1, len(img_infos), e)
                all_url_results.append([{"success": False, "df": None, "url": raw_url, "reason": f"图片下载失败: {e}"}])
                return
        
        # 所有图片已转为 data URL，一次性调用 _process_image_array
        try:
            img_r = await _process_image_array(
                image_urls=img_data_urls,
                account_no=first["account_no"],
                account_name=first["account_name"],
                order_no=first["order_no"],
                label="images",
            )
            all_url_results.append([img_r])
        except Exception as e:
            logger.error("[BG:%s] 图片批量处理失败: %s", order_no, e, exc_info=True)
            all_url_results.append([{"success": False, "df": None, "url": img_data_urls[0] if img_data_urls else "", "reason": str(e)}])

    # 3. 收集结果
    all_dfs: List[pd.DataFrame] = []
    failed_files: List[str] = []

    for url_result in all_url_results:
        if isinstance(url_result, Exception):
            failed_files.append(str(url_result))
            continue
        for r in url_result:
            if r["success"] and r["df"] is not None and not r["df"].empty:
                all_dfs.append(r["df"])
            elif not r["success"]:
                failed_files.append(r.get("reason", ""))

    # 4. 合并 + 落盘 CSV + 回调
    if not all_dfs:
        logger.warning("[BG:%s] 所有文件处理失败", order_no)
        await _do_callback(OCRCallbackPayload(
            orderNO=order_no,
            custName=request.custName,
            companyName=request.companyName,
            accountNo=request.accountNo,
            accountName=request.accountName,
        ))
        return

    merged_df = merge_dataframes(all_dfs)
    merged_df = apply_balance_correction(merged_df, tolerance=BALANCE_CORRECTION_TOLERANCE)

    # account_id 固定使用上游传入的 accountNo 覆盖（不论 LLM 是否提取到）
    merged_df["account_id"] = request.accountNo or ""

    csv_string = dataframe_to_csv_string(merged_df)
    csv_url = _save_csv(order_no, csv_string)
    csv_file_b64 = base64.b64encode(csv_string.encode("utf-8-sig")).decode("utf-8")

    logger.info(
        "[BG:%s] 处理完成，共 %d 条记录，%d 个文件失败",
        order_no, len(merged_df), len(failed_files),
    )

    callback_payload = OCRCallbackPayload(
        orderNO=order_no,
        csvUrl=csv_url,
        csvFile=csv_file_b64,
        custName=request.custName,
        companyName=request.companyName,
        accountNo=request.accountNo,
        accountName=request.accountName,
    )
    await _do_callback(callback_payload)


# ══════════════════════════════════════════════════════════════
#  本地文件测试接口（直接上传文件，绕过远程 URL 下载）
# ══════════════════════════════════════════════════════════════

@router.post("/ocr/upload", response_model=OCRResponse, summary="本地文件上传测试（绕过远程 URL）")
async def ocr_upload(
    files: List[UploadFile] = File(..., description="本地图片或 PDF 文件，支持多文件"),
    order_no: str = Form("LOCAL_TEST", description="业务订单号"),
    account_no: str = Form("", description="账户号（可选）"),
    account_name: str = Form("", description="账户名（可选）"),
    cust_name: str = Form("", description="客户名称（可选）"),
    company_name: str = Form("", description="公司名称（可选）"),
):
    """
    **本地文件全流程测试接口** — 直接上传本地图片/PDF，跳过远程 URL 下载步骤。

    - 支持 jpg / jpeg / png / gif / webp / pdf 格式
    - 支持同时上传多个文件（会合并为一份 CSV 返回）
    - PDF 自动拆分为多页分别识别
    - 返回与 POST /ocr 相同结构（含 csvUrl）

    **用途**：本地验收测试、调试 Agent，无需配置影像平台 URL。
    """
    logger.info("=== 本地上传测试 order_no=%s, 文件数=%d ===", order_no, len(files))

    all_dfs: List[pd.DataFrame] = []
    failed_files: List[dict] = []

    # 预读所有文件内容，区分 PDF 和图片
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif", "webp": "image/webp"}

    pdf_items: list[tuple[str, bytes]] = []    # (filename, bytes)
    img_data_urls: list[str] = []              # 图片 base64 data URL 列表

    for i, upload in enumerate(files):
        filename = upload.filename or f"file_{i+1}"
        try:
            file_bytes = await upload.read()
            if not file_bytes:
                failed_files.append(f"{filename}: 文件内容为空")
                continue
            ftype = detect_file_type(filename)
            if ftype == "pdf":
                pdf_items.append((filename, file_bytes))
            else:
                ext = filename.rsplit(".", 1)[-1].lower()
                mime = mime_map.get(ext, "image/jpeg")
                img_data_urls.append(image_to_base64_url(file_bytes, mime=mime))
        except Exception as e:
            logger.error("[%d/%d][%s] 读取失败: %s", i+1, len(files), filename, e)
            failed_files.append(f"{filename}: {e}")

    logger.info("本地上传: PDF %d 个，图片 %d 张", len(pdf_items), len(img_data_urls))

    # PDF：各自独立处理（每个 PDF 内部已有分块并发）
    async def _process_pdf(filename: str, file_bytes: bytes) -> None:
        try:
            page_images = await asyncio.to_thread(pdf_to_images, file_bytes)
            logger.info("[%s] PDF 共 %d 页", filename, len(page_images))
            page_data_urls = [image_to_base64_url(img_bytes) for img_bytes in page_images]
            r = await _process_image_array(
                image_urls=page_data_urls,
                account_no=account_no,
                account_name=account_name,
                order_no=order_no,
                label=filename,
            )
            if r["success"] and r["df"] is not None:
                all_dfs.append(r["df"])
            else:
                failed_files.append(f"{filename}: {r.get('reason', '')}")
        except Exception as e:
            logger.error("[%s] PDF 处理失败: %s", filename, e, exc_info=True)
            failed_files.append(f"{filename}: {e}")

    if pdf_items:
        await asyncio.gather(*[_process_pdf(fn, fb) for fn, fb in pdf_items])

    # 图片：全部合并为一个数组，一次性调用 _process_image_array
    #       chunk-0 提取 metadata，后续分块自动 skip_metadata=True，仅 1 次 metadata
    if img_data_urls:
        logger.info("合并 %d 张图片统一提取（仅 1 次 metadata）", len(img_data_urls))
        try:
            r = await _process_image_array(
                image_urls=img_data_urls,
                account_no=account_no,
                account_name=account_name,
                order_no=order_no,
                label="images",
            )
            if r["success"] and r["df"] is not None:
                all_dfs.append(r["df"])
            else:
                failed_files.append(f"images: {r.get('reason', '')}")
        except Exception as e:
            logger.error("图片批量处理失败: %s", e, exc_info=True)
            failed_files.append(f"images: {e}")

    csv_url = None
    csv_file_b64 = None
    if all_dfs:
        merged_df = merge_dataframes(all_dfs)
        merged_df = apply_balance_correction(merged_df, tolerance=BALANCE_CORRECTION_TOLERANCE)
        # account_id 固定使用上游传入的 account_no 覆盖（不论 LLM 是否提取到）
        merged_df["account_id"] = account_no or ""
        csv_string = dataframe_to_csv_string(merged_df)
        csv_url = _save_csv(order_no, csv_string)
        csv_file_b64 = base64.b64encode(csv_string.encode("utf-8-sig")).decode("utf-8")
        logger.info("本地上传测试完成: %d 条记录, %d 失败", len(merged_df), len(failed_files))

    return OCRResponse(
        orderNO=order_no,
        csvUrl=csv_url,
        csvFile=csv_file_b64,
        custName=cust_name,
        companyName=company_name,
        accountNo=account_no,
        accountName=account_name,
    )
