"""
URL 修正服务
参考 dify_batch_ocr.ipynb Cell 3 的 fix_url 实现
"""
import logging
from typing import List

logger = logging.getLogger("transaction_ocr")


def fix_url(raw: str) -> str:
    """不以 / 开头的 URL 补充 /（跳过 data: 和 http(s): 开头的 URL）"""
    s = str(raw).strip()
    if s.startswith("/") or s.startswith("http") or s.startswith("data:"):
        return s
    return "/" + s


def extract_remote_urls(
    remote_urls: List[str],
    account_no: str = "",
    account_name: str = "",
    order_no: str = "",
) -> List[dict]:
    """
    从 remoteUrls 列表中提取并修正 URL。

    返回列表，每个元素包含：
        {
            "url": 修正后的 URL,
            "account_no": 账户号,
            "account_name": 账户名,
            "order_no": 订单号（用于 serial_id），
        }
    """
    result = []
    for url in remote_urls:
        if url and url.strip():
            fixed = fix_url(url)
            result.append({
                "url": fixed,
                "account_no": account_no,
                "account_name": account_name,
                "order_no": order_no,
            })
            logger.debug("URL 修正: %s → %s", url, fixed)
    logger.info("共提取 %d 个 remote_url", len(result))
    return result
