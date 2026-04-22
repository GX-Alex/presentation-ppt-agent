"""
PDF 解析核心逻辑模块

流水解析统一采用「转图 → 视觉模型」：所有 PDF 均先 convert_pages_to_images 转成 PNG，
再逐页 parse_image_page 调用视觉大模型，不区分文本型/扫描型。

PdfAnalyzer 提供：
1. detect_pdf_type()        — 检测 PDF 类型与总页数（仅供 /detect 接口展示，不参与解析分支）
2. convert_pages_to_images() — 将 PDF 页渲染为 PNG（解析 PDF 的必经步骤）
3. parse_image_page()       — 单张图片调用视觉模型识别流水表格
4. ensure_balance_ok()       — 兜底补充 is_balance_ok
5. extract_json_from_response() — 从模型响应中提取 JSON

依赖：fitz (PyMuPDF)、AIProvider。可调参数在模块顶部常量，无硬编码路径。
"""

import json
import logging
import re
from typing import Optional

import fitz  # PyMuPDF — PDF 文档操作库

from app.providers.base import AIProvider
from app.utils.json_utils import extract_json_raw

# 模块级日志器，日志中会显示 "app.parsers.pdf_parser" 便于按模块过滤
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 非交易行过滤（期初/承前/水前等）：序号或摘要含这些关键词时整行过滤
# ---------------------------------------------------------------------------
NON_TX_KEYWORDS = frozenset([
    "承前", "转下页", "小计", "合计", "期初", "期末", "接上页", "过次页", "转次页",
    "水前", "余额承前", "流水前", "额前",
])


def _safe_float(value) -> Optional[float]:
    """安全地将值转为 float，模型返回的数字可能是 str/int/float/None"""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _is_non_transaction_row(txn: dict) -> bool:
    """
    判断是否为非交易行（期初余额、承前、汇总等），应过滤。
    典型特征：序号列为「水前」「期初」等非数字；或摘要/交易名称为过渡词；或仅有余额无收支无对手方。
    """
    # 1. seq_no 不是正整数：标准交易行序号应为 1,2,3...（允许 "1." / "01" 等格式）
    seq = txn.get("seq_no")
    if seq is not None:
        if isinstance(seq, (int, float)):
            if seq < 1 or int(seq) != seq:
                return True
        else:
            s = str(seq).strip()
            if s:
                if s.isdigit():
                    pass  # 纯数字视为有效序号，继续后续检查
                else:
                    for kw in NON_TX_KEYWORDS:
                        if kw in s:
                            return True
                    try:
                        n = float(s)
                        if n < 1 or n != int(n):
                            return True
                    except (ValueError, TypeError):
                        return True

    # 2. summary、transaction_name、counterparty 包含关键词
    for key in ("summary", "transaction_name", "counterparty"):
        val = txn.get(key)
        if val and isinstance(val, str):
            for kw in NON_TX_KEYWORDS:
                if kw in val:
                    return True

    # 3. 收入支出均为空、仅有余额、且无交易对手/摘要/日期：典型期初余额行
    income = _safe_float(txn.get("income"))
    expense = _safe_float(txn.get("expense"))
    balance = _safe_float(txn.get("balance"))
    if income is None and expense is None and balance is not None:
        if not txn.get("counterparty") and not txn.get("summary") and not txn.get("tx_date"):
            if not txn.get("transaction_name") or any(kw in str(txn.get("transaction_name", "")) for kw in NON_TX_KEYWORDS):
                return True

    return False


def filter_non_transaction_rows(transactions: list[dict]) -> list[dict]:
    """过滤掉期初余额、承前、汇总等非交易行，返回仅含真实交易的列表"""
    if not transactions:
        return transactions
    filtered = [t for t in transactions if not _is_non_transaction_row(t)]
    removed = len(transactions) - len(filtered)
    if removed > 0:
        logger.info("[parser] 过滤非交易行 %d 条（期初/承前/水前等）", removed)
    return filtered

# ============================================================================
# PDF 类型检测相关阈值（可移植：仅依赖这些常量，无硬编码路径）
# ============================================================================
MIN_TEXT_LENGTH_PER_PAGE = 50   # 参与判定的每页最少有效字符数（见 detect_pdf_type）
MIN_CHINESE_RATIO = 0.05        # 中文字符最低占比，用于区分文本型流水
MAX_DETECT_PAGES = 3            # 类型检测最多检查页数
TEXT_SAMPLE_MAX_LENGTH = 500    # 返回给调用方的文本样本最大长度


class PdfAnalyzer:
    """
    PDF 银行流水解析器。所有 PDF 均通过「转图 → 视觉模型」解析，无文本解析分支。

    典型流程：convert_pages_to_images() → 逐页 parse_image_page() → 合并结果 → ensure_balance_ok()。
    detect_pdf_type() 仅用于 /detect 接口返回总页数与类型标签。
    """

    @staticmethod
    def detect_pdf_type(file_path: str) -> dict:
        """
        智能检测 PDF 文件类型

        通过分析 PDF 前几页的文字内容，判断该 PDF 是「文本型」还是「扫描型」：
        - 文本型（TEXT）：PDF 中嵌入了可选中的文本层，可以用 PyMuPDF 直接提取文字
        - 扫描型（SCANNED）：PDF 页面是扫描图片，没有可提取的文本，需要用视觉模型识别
        - 未知型（UNKNOWN）：无法判断类型（如空白 PDF 或加密文件）

        判断逻辑：
        1. 使用 PyMuPDF 打开 PDF，获取总页数
        2. 遍历前 MAX_DETECT_PAGES 页，逐页提取文字
        3. 若每页字符数均 >= MIN_TEXT_LENGTH_PER_PAGE 且总中文字符占比达标，判定为文本型
        4. 否则若总字符数>0 且中文占比 >= MIN_CHINESE_RATIO，仍判为文本型（兼容每页字数不均）
        5. 否则判定为扫描型（需要视觉模型处理）

        参数：
            file_path: PDF 文件的本地绝对路径

        返回：
            字典，包含以下字段：
            - pdf_type (str): "TEXT" / "SCANNED" / "UNKNOWN"
            - total_pages (int): PDF 总页数
            - text_sample (str): 提取的文本样本（最多 500 字符），供调用方预览
            - has_chinese (bool): 是否包含中文字符
            - chinese_ratio (float): 中文字符占总字符的比例

        异常：
            FileNotFoundError: PDF 文件不存在
            fitz.FileDataError: PDF 文件损坏或格式无效
        """
        logger.info("[parser] PDF 类型检测开始 | file_path=%s", file_path)

        # 使用 PyMuPDF 打开 PDF 文件
        doc = fitz.open(file_path)
        total_pages = len(doc)
        logger.info("[parser] PDF 已打开 | total_pages=%d", total_pages)

        # 确定需要检测的页数范围（取总页数和最大检测页数的较小值）
        pages_to_check = min(total_pages, MAX_DETECT_PAGES)
        all_text = ""

        # 逐页提取文字，并记录每页长度（用于「每页达标」判定）
        page_lengths = []
        for page_idx in range(pages_to_check):
            page = doc[page_idx]
            page_text = page.get_text("text")
            page_lengths.append(len(page_text.strip()))
            all_text += page_text
            logger.debug(
                "第 %d 页文字提取完成 — 字符数: %d",
                page_idx + 1,
                page_lengths[-1],
            )

        doc.close()

        all_text = all_text.strip()
        text_length = len(all_text)

        # 统计中文字符数量和占比
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", all_text)
        chinese_count = len(chinese_chars)
        chinese_ratio = chinese_count / text_length if text_length > 0 else 0.0

        logger.info(
            "[parser] 文本分析完成 | chars=%d | chinese=%d | ratio=%.2f%%",
            text_length,
            chinese_count,
            chinese_ratio * 100,
        )

        # 判定：每页均达标则 TEXT；否则总字数+中文占比达标仍判 TEXT（兼容页间不均）
        every_page_ok = all(
            pl >= MIN_TEXT_LENGTH_PER_PAGE for pl in page_lengths
        ) if page_lengths else False
        if every_page_ok and chinese_ratio >= MIN_CHINESE_RATIO:
            pdf_type = "TEXT"
            logger.info("PDF 类型判定: 文本型（TEXT）— 每页文字充足")
        elif text_length >= MIN_TEXT_LENGTH_PER_PAGE * pages_to_check and chinese_ratio >= MIN_CHINESE_RATIO:
            pdf_type = "TEXT"
            logger.info("PDF 类型判定: 文本型（TEXT）— 总文字量充足且含中文")
        elif text_length > 0 and chinese_ratio >= MIN_CHINESE_RATIO:
            # 文字量不多但包含足够中文，仍然当作文本型处理
            # 某些银行流水 PDF 每页文字不多但确实是文本型
            pdf_type = "TEXT"
            logger.info("PDF 类型判定: 文本型（TEXT）— 包含有效中文内容")
        elif text_length == 0:
            # 完全没有提取到文字，大概率是扫描件
            pdf_type = "SCANNED"
            logger.info("PDF 类型判定: 扫描型（SCANNED）— 未检测到文本内容")
        else:
            # 有少量文字但不像有效的银行流水文本（可能是 PDF 元数据残留）
            pdf_type = "SCANNED"
            logger.info(
                "PDF 类型判定: 扫描型（SCANNED）— 文本量不足且中文占比低 (%.2f%%)",
                chinese_ratio * 100,
            )

        # 截取文本样本，供调用方快速预览 PDF 内容
        text_sample = all_text[:TEXT_SAMPLE_MAX_LENGTH]

        return {
            "pdf_type": pdf_type,
            "total_pages": total_pages,
            "text_sample": text_sample,
            "has_chinese": chinese_count > 0,
            "chinese_ratio": round(chinese_ratio, 4),
        }

    @staticmethod
    def convert_pages_to_images(
        file_path: str,
        pages: Optional[list[int]] = None,
        dpi: int = 200,
    ) -> list[bytes]:
        """
        将 PDF 页面渲染为高清 PNG 图片。解析流水时，所有 PDF 均经本方法转图后再送视觉模型。

        使用 PyMuPDF 的 get_pixmap() 将指定页渲染为位图并导出 PNG，供视觉大模型识别表格。

        DPI 参数说明：
        - 150 DPI: 速度快，文件小，适合快速预览（但小字可能模糊）
        - 200 DPI: 推荐值，清晰度和文件大小的最佳平衡点
        - 300 DPI: 高清模式，适合印章和小字密集的扫描件（但文件较大）

        参数：
            file_path: PDF 文件的本地绝对路径
            pages: 需要转换的页码列表（从 1 开始计数）。
                   如果为 None，则转换所有页面。
            dpi: 渲染分辨率（每英寸像素数），默认 200

        返回：
            字节列表，每个元素是一页 PNG 图片的二进制数据（bytes）。
            可以直接传给 AIProvider.vision() 或保存为文件。

        异常：
            FileNotFoundError: PDF 文件不存在
            ValueError: dpi 参数不在合理范围内
        """
        logger.info(
            "[parser] PDF 转图片开始 | file_path=%s | dpi=%d | pages=%s",
            file_path,
            dpi,
            pages if pages else "全部",
        )

        doc = fitz.open(file_path)
        total_pages = len(doc)

        # 确定需要处理的页码范围
        if pages is None:
            page_indices = list(range(total_pages))
        else:
            page_indices = [p - 1 for p in pages if 0 < p <= total_pages]

        # 计算缩放矩阵：PyMuPDF 默认渲染 72 DPI，需要按比例放大
        # 例如 dpi=200 时，zoom = 200/72 ≈ 2.78，即放大约 2.78 倍
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        image_list = []
        for idx in page_indices:
            page = doc[idx]
            # 使用缩放矩阵渲染页面为位图（Pixmap）
            pixmap = page.get_pixmap(matrix=matrix)
            # 将位图导出为 PNG 格式的二进制数据
            png_bytes = pixmap.tobytes("png")
            image_list.append(png_bytes)
            logger.debug(
                "第 %d 页已转换为图片 — 尺寸: %dx%d, 文件大小: %.1fKB",
                idx + 1,
                pixmap.width,
                pixmap.height,
                len(png_bytes) / 1024,
            )

        doc.close()
        logger.info(
            "图片转换完成 — 共转换 %d 页, 总大小: %.1fMB",
            len(image_list),
            sum(len(img) for img in image_list) / (1024 * 1024),
        )
        return image_list

    @staticmethod
    async def parse_image_page(
        image_bytes: bytes,
        ai_provider: AIProvider,
        prompt: str,
        mime_type: str = "image/png",
    ) -> tuple[list[dict], dict | None]:
        """
        使用视觉大模型识别单页银行流水图片

        将 PDF 页面渲染的 PNG 图片发送给视觉大模型（如 qwen-vl-max），
        由模型"看"图片并识别其中的表格数据，转换为结构化的 JSON 交易列表。
        同时提取表格上方的 metadata（银行名称、账号、户名等）。

        返回：
            (transactions, metadata) 元组。解析失败时抛出异常，由上层按「失败重试 3 次」处理。
        """
        logger.info("开始图片解析 — 图片大小: %.1fKB", len(image_bytes) / 1024)

        response = await ai_provider.vision(prompt, image_bytes, mime_type=mime_type)
        logger.debug("视觉模型响应长度: %d 字符", len(response))

        transactions, metadata = PdfAnalyzer.extract_parse_result_with_metadata(response)
        if not isinstance(transactions, list):
            raise ValueError("模型返回结果无法解析为交易列表")

        transactions = filter_non_transaction_rows(transactions)

        for txn in transactions:
            for key in ("income", "expense", "balance"):
                txn[key] = _safe_float(txn.get(key))

        logger.info("图片解析完成 — 提取到 %d 条交易记录", len(transactions))
        return transactions, metadata

    @staticmethod
    def ensure_balance_ok(transactions: list[dict]) -> list[dict]:
        """
        确保每笔交易有 is_balance_ok 字段。
        大模型已在提示词中执行余额连续性校验，此处仅对模型未输出的记录做兜底计算。
        """
        if not transactions:
            return transactions

        for i, txn in enumerate(transactions):
            if "is_balance_ok" in txn:
                continue
            if i == 0:
                txn["is_balance_ok"] = True
                continue
            prev_balance = _safe_float(transactions[i - 1].get("balance"))
            current_balance = _safe_float(txn.get("balance"))
            income = _safe_float(txn.get("income"))
            expense = _safe_float(txn.get("expense"))
            if prev_balance is None or current_balance is None:
                txn["is_balance_ok"] = True
            else:
                expected = prev_balance + (income or 0) - (expense or 0)
                txn["is_balance_ok"] = abs(expected - current_balance) <= 0.01
        return transactions

    @staticmethod
    def extract_parse_result_with_metadata(text: str) -> tuple[list[dict], dict | None]:
        """
        从大模型响应中提取 transactions 和 metadata。
        当模型返回 {"transactions": [...], "metadata": {...}} 时，返回两者；
        否则返回 (transactions_list, None)。
        """
        parsed = PdfAnalyzer._extract_json_raw(text)
        if parsed is None:
            return [], None
        if isinstance(parsed, dict):
            txs = parsed.get("transactions")
            meta = parsed.get("metadata")
            if isinstance(txs, list):
                return txs, meta if isinstance(meta, dict) else None
            # 兼容：仅有 transactions 键
            for v in parsed.values():
                if isinstance(v, list):
                    return v, meta if isinstance(meta, dict) else None
        if isinstance(parsed, list):
            return parsed, None
        return [], None

    @staticmethod
    def _extract_json_raw(text: str) -> list | dict | None:
        """提取 JSON 原始结构（list 或 dict），失败返回 None。委托 app.utils.json_utils。"""
        return extract_json_raw(text)

    @staticmethod
    def extract_json_from_response(text: str) -> list[dict]:
        """
        从大模型响应文本中鲁棒地提取 JSON 数组。

        复用 _extract_json_raw 的多种策略（直接解析、代码块、括号截取），
        然后从解析结果中取出列表：若为 list 直接返回，若为 dict 则取第一个 list 值。
        失败或非列表则返回空列表。
        """
        if not text or not text.strip():
            logger.warning("大模型响应为空，无法提取 JSON")
            return []
        parsed = PdfAnalyzer._extract_json_raw(text)
        if parsed is None:
            logger.warning(
                "无法从大模型响应中提取 JSON — 响应前 200 字符: %s",
                text.strip()[:200],
            )
            return []
        if isinstance(parsed, list):
            logger.debug("JSON 提取成功 — %d 条记录", len(parsed))
            return parsed
        if isinstance(parsed, dict):
            for v in parsed.values():
                if isinstance(v, list):
                    logger.debug("JSON 提取成功（从字典）— %d 条记录", len(v))
                    return v
        return []
