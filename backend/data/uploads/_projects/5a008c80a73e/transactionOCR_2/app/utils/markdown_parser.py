"""
Markdown 表格 → pandas DataFrame 工具函数
参考 dify_batch_ocr.ipynb Cell 4 实现
"""
import re
import logging
import pandas as pd
import markdown
from io import StringIO

logger = logging.getLogger("transaction_ocr")


def _strip_md_wrapper(md_text: str) -> str:
    """去除 Markdown 代码块包装"""
    md_text = md_text.strip()
    wrapper = "```"
    if md_text.endswith(wrapper):
        if md_text.startswith(wrapper):
            md_text = md_text[len(wrapper):-len(wrapper)]
        elif md_text.startswith(f"{wrapper}markdown"):
            md_text = md_text[len(f"{wrapper}markdown"):-len(wrapper)]
    return md_text


def markdown_to_dataframe(md_text: str, force_str: bool = True) -> pd.DataFrame:
    """
    将 Markdown 表格文本解析为 DataFrame。

    实现参考 markdown-exporter：
      1. 去除代码块包装
      2. 修正首行对齐
      3. markdown → HTML（启用 tables 扩展）
      4. pd.read_html() 解析 HTML 表格
      5. 后处理：fillna("") + 强制 str

    Args:
        md_text:   Markdown 表格文本
        force_str: True 时将所有非 str 列强制转为字符串

    Returns:
        pd.DataFrame；解析失败时返回空 DataFrame
    """
    if not md_text or not str(md_text).strip():
        logger.warning("markdown_to_dataframe: 输入为空")
        return pd.DataFrame()

    try:
        processed = _strip_md_wrapper(str(md_text))

        if not processed.lstrip().startswith("|") and "|" in processed:
            processed = processed.replace("|", "\n|", 1)

        html_str = markdown.markdown(text=processed, extensions=["tables"])

        if "<table>" not in html_str:
            logger.warning("markdown_to_dataframe: 未检测到表格")
            return pd.DataFrame()

        tables = pd.read_html(StringIO(html_str), encoding="utf-8")
        if not tables:
            logger.warning("markdown_to_dataframe: pd.read_html 未解析到表格")
            return pd.DataFrame()

        df = tables[0]
        df = df.fillna("")
        if force_str:
            for col in df.columns:
                if df[col].dtype not in ("object", "string"):
                    df[col] = df[col].astype(str)

        logger.info("Markdown 表格解析成功: %d 行 × %d 列", len(df), len(df.columns))
        return df

    except Exception as e:
        logger.error("markdown_to_dataframe 解析失败: %s", e, exc_info=True)
        return pd.DataFrame()
