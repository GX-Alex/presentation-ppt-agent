"""
数据处理服务 — Agent 结果 → DataFrame → CSV
参考 dify_batch_ocr.ipynb Cell 6 的 process_dify_result 实现
"""
import io
import logging
from typing import Optional

import pandas as pd
from datetime import datetime

from app.utils.markdown_parser import markdown_to_dataframe
from transaction_mapper import process_transaction_data, df_to_csv_bytes

logger = logging.getLogger("transaction_ocr")


def process_agent_result(
    agent_json: dict,
    image_url: str = "",
    serial_no: str = "",
) -> pd.DataFrame:
    """
    解析 Agent 输出 JSON，完成字段映射，返回处理好的 DataFrame。

    Args:
        agent_json : Agent 输出字典（含客户元数据 + transactions markdown）
        image_url  : 来源图片地址（仅用于日志）
        serial_no  : 对应的交易流水号

    Returns:
        处理后的 DataFrame；解析失败时返回空 DataFrame
    """
    # 1. 提取账户元数据
    account_name = agent_json.get("客户名称") or agent_json.get("account_name") or None
    account_id = agent_json.get("客户账号") or agent_json.get("account_id") or None
    account_bank = agent_json.get("账户所属机构") or agent_json.get("account_bank") or None
    transactions_md = agent_json.get("transactions", "")

    if not str(transactions_md).strip():
        logger.warning("[%s] transactions 字段为空，跳过", serial_no)
        return pd.DataFrame()

    # 2. Markdown → DataFrame → CSV bytes
    df_raw = markdown_to_dataframe(str(transactions_md))
    if df_raw.empty:
        logger.warning("[%s] 未解析到任何表格行，跳过", serial_no)
        return pd.DataFrame()

    csv_bytes = df_raw.to_csv(index=False).encode("utf-8")

    # 3. 套用 transaction_mapper 完整处理逻辑
    df_mapped = process_transaction_data(
        csv_content=csv_bytes,
        account_name=account_name,
        account_id=account_id,
        account_bank=account_bank,
        serial_id=serial_no if serial_no else None,
    )

    logger.info(
        "[%s] %s → 原始 %d 行 → 处理后 %d 行",
        serial_no,
        image_url[:80],
        len(df_raw),
        len(df_mapped),
    )
    return df_mapped


def merge_dataframes(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """
    合并多个 DataFrame，统一行号和时间戳。
    参考 dify_batch_ocr.ipynb Cell 8。
    """
    if not dfs:
        return pd.DataFrame()

    merged = pd.concat(dfs, ignore_index=True)

    # ── 排序已禁用（保持原始行序）──
    # if 'trans_date' in merged.columns:
    #     sort_cols = ['trans_date']
    #     if 'trans_time' in merged.columns and merged['trans_time'].notna().any():
    #         sort_cols.append('trans_time')
    #     merged = merged.sort_values(by=sort_cols, ascending=True, na_position='last').reset_index(drop=True)

    # 重新生成连续行号和时间戳
    merged["rel_line_num"] = range(1, len(merged) + 1)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    merged["create_time"] = now
    merged["update_time"] = now

    logger.info("合并完成: %d 行 × %d 列", len(merged), len(merged.columns))
    return merged


def dataframe_to_csv_string(df: pd.DataFrame) -> str:
    """将 DataFrame 转为 CSV 字符串（UTF-8-SIG 编码以兼容 Excel）"""
    output = io.StringIO()
    df.to_csv(output, index=False, encoding="utf-8-sig")
    return output.getvalue()
