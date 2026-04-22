"""
提示词动态加载器 — 从 Dify 平台实时获取提示词，带 TTL 缓存和降级策略

工作流：
  1. 首次调用 → 请求 Dify API → 缓存 10 分钟
  2. 缓存未过期 → 直接返回缓存
  3. Dify 不可用 → 优先使用旧缓存（即使过期），无缓存则降级到硬编码提示词
  4. DIFY_BASE_URL 为空 → 直接使用硬编码提示词（纯本地模式）
"""
import asyncio
import time
import logging
import httpx
from typing import Optional

from app.config import (
    DIFY_BASE_URL,
    DIFY_EXTRACT_TRANSACTIONS_API_KEY,
    DIFY_EXTRACT_METADATA_API_KEY,
    PROMPT_CACHE_TTL,
)

logger = logging.getLogger("transaction_ocr")

# ══════════════════════════════════════════════════════════════
#  硬编码兜底提示词（Dify 不可用时使用）
# ══════════════════════════════════════════════════════════════

_FALLBACK_EXTRACT_TRANSACTIONS = """## 核心规则（必读！）
### 收支识别（不同银行格式不同）
1. **分列格式**：有「借方发生额」「贷方发生额」或「收入/贷方」「支出/借方」时，借方→支出，贷方→收入，另一列填 null
2. **单列正负号**：正数→收入，负数→支出（取绝对值）
3. **金额**：与图片完全一致，不四舍五入；正负号仅表示收支方向
- 金额读数技巧：
  - 数字0/6/8/9极易混淆，尤其在手写或模糊时
  - 小数点前后的0容易被忽略或误读
  - 金额末位为0时尤其要核对是否为6/8/9误读

### 表头解析
- **合并单元格**：顶层+子列语义融合。例：「发生额」+「借方」→「支出」；「交易对手信息」+「对手机构」→「对手机构信息」
- **斜杠拆分**：如「对方户名/账号」→拆成「对方账户名称」「对方账户号码」两列
- 如果某些图片没有表头需从有表头的图片中推测表结构

### 日期时间规则
**日期**：统一为 YYYY-MM-DD；若只有月日，从表头起止日期补全，校验日期合法性，不能出现2023-13-01这类。
**时间**：统一为 HH:MM:SS；若为「2024-01-15 14:30:00」形式，拆成交易日期和交易时间两列，绝对不能出现非时间格式（HH:MM:SS）的内容。

### 其余规则
*真实连续交易金额重复行保留**。
**脏数据过滤**：跳过「承前」行，示例 
— 跳过这类行：| 承前 | | | | 47,780.06 | | ...  ← 跳过，不输出。
**字段完整性**：表头固定 15 列，顺序不变，一列不少：
`流水号 | 交易日期 | 交易时间 | 对方账户名称 | 支出 | 收入 | 账户余额 | 币种 | 对方账户号码 | 对方开户行 | 交易渠道 | 交易类型 | 交易用途 | 摘要 | 附言 `。
**金额格式**：保留两位小数；去掉千分位逗号；去掉货币符号（¥、￥等）。
**异常**：倾斜、模糊、无表头时，根据列数据特征和金融常识推断列含义；多行排版时合并字段值。

## 输出要求
- 使用标准 Markdown 表格，直接以表格开头，无前缀说明
**示例：**
| 流水号 | 交易日期 | 交易时间 | 对方账户名称 | 支出 | 收入 | 账户余额 | 币种 | 对方账户号码 | 对方开户行 | 交易渠道 | 交易类型 | 交易用途 | 摘要 | 附言 |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| | 2023-10-01 | | | | 2000.00 | 20000.00 | 人民币 | | | | | | | |
"""

_FALLBACK_EXTRACT_METADATA = """从提供的银行对账单图片中，仅从表头区域提取"客户名称"和"客户账号"和"账户所属机构"三个字段。请严格按以下规则处理： "客户名称"、"客户账号"、"账户所属机构"可能有其他别名，例如：户名、账户号、开户机构等等
若字段不存在或为空，则返回 null；输出必须为标准 JSON 格式。 不解析正文交易明细，仅聚焦表头。 示例输出： {"客户名称": "宁波涌畔建筑设计咨询有限公司", "客户账号": "634313601"，"账户所属机构"："中国民生银行股份有限公司"}"""


# ══════════════════════════════════════════════════════════════
#  缓存结构
# ══════════════════════════════════════════════════════════════

class _CacheEntry:
    __slots__ = ("text", "expires_at")

    def __init__(self, text: str, ttl: int):
        self.text = text
        self.expires_at = time.monotonic() + ttl

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


# key → _CacheEntry（可能已过期，用于降级）
_cache: dict[str, _CacheEntry] = {}

# 每个 prompt 独立的锁，防止冷启动时并发击穿 Dify
_fetch_locks: dict[str, asyncio.Lock] = {}


def _get_lock(prompt_name: str) -> asyncio.Lock:
    if prompt_name not in _fetch_locks:
        _fetch_locks[prompt_name] = asyncio.Lock()
    return _fetch_locks[prompt_name]


# Dify App 注册表：名称 → API Key
_DIFY_APPS: dict[str, str] = {
    "extract_transactions": DIFY_EXTRACT_TRANSACTIONS_API_KEY,
    "extract_metadata": DIFY_EXTRACT_METADATA_API_KEY,
}

# 兜底提示词注册表
_FALLBACKS: dict[str, str] = {
    "extract_transactions": _FALLBACK_EXTRACT_TRANSACTIONS,
    "extract_metadata": _FALLBACK_EXTRACT_METADATA,
}


# ══════════════════════════════════════════════════════════════
#  核心拉取逻辑
# ══════════════════════════════════════════════════════════════

async def _fetch_from_dify(prompt_name: str, api_key: str) -> Optional[str]:
    """
    调用 Dify 文本生成 App API，返回提示词文本。
    失败时返回 None。

    Dify 工作流接口：POST /v1/workflows/run
    请求体：{"inputs": {}, "response_mode": "blocking", "user": "prompt-loader"}
    响应：{"data": {"outputs": {"text": "提示词全文"}, ...}, ...}
    """
    url = f"{DIFY_BASE_URL.rstrip('/')}/v1/workflows/run"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {},
        "response_mode": "blocking",
        "user": "prompt-loader",
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            # 调试：打印原始响应结构（排查 Dify 返回字段名）
            logger.debug("[PromptLoader] Dify 原始响应: prompt=%s body=%s", prompt_name, str(data)[:500])
            # 工作流响应结构：data.outputs.text
            outputs = (data.get("data") or {}).get("outputs") or {}
            answer = (outputs.get("text") or "").strip()
            if not answer:
                logger.warning("[PromptLoader] Dify 返回空提示词: prompt=%s", prompt_name)
                return None
            return answer
    except httpx.TimeoutException:
        logger.warning("[PromptLoader] Dify 请求超时: prompt=%s url=%s", prompt_name, url)
    except httpx.HTTPStatusError as e:
        logger.warning(
            "[PromptLoader] Dify HTTP 错误: prompt=%s status=%d",
            prompt_name, e.response.status_code,
        )
    except Exception as e:
        logger.warning("[PromptLoader] Dify 请求失败: prompt=%s error=%s", prompt_name, e)
    return None


async def get_prompt(prompt_name: str) -> str:
    """
    获取提示词（优先 Dify，带 TTL 缓存，失败降级）。

    降级策略（按优先级）：
      1. 缓存未过期 → 直接返回缓存
      2. Dify 可访问 → 拉取更新缓存 → 返回新提示词
      3. Dify 失败但有旧缓存 → 使用旧缓存（即使已过期）并打印告警
      4. Dify 失败且无缓存 → 返回硬编码兜底提示词

    Args:
        prompt_name: "extract_transactions" 或 "extract_metadata"
    """
    fallback = _FALLBACKS.get(prompt_name, "")
    api_key = _DIFY_APPS.get(prompt_name, "")

    # ── DIFY 未配置：直接用硬编码 ──
    if not DIFY_BASE_URL or not api_key:
        if prompt_name not in _cache:
            logger.info("[PromptLoader] Dify 未配置，使用内置提示词: prompt=%s", prompt_name)
        return fallback

    # ── 缓存命中且未过期（无锁快速路径）──
    entry = _cache.get(prompt_name)
    if entry and not entry.is_expired:
        return entry.text

    # ── 加锁，防止并发冷启动时多个协程同时请求 Dify ──
    async with _get_lock(prompt_name):
        # 二次检查：持锁后缓存可能已被先行协程填充
        entry = _cache.get(prompt_name)
        if entry and not entry.is_expired:
            return entry.text

        # ── 缓存过期或无缓存，尝试从 Dify 拉取 ──
        logger.info("[PromptLoader] 从 Dify 拉取提示词: prompt=%s", prompt_name)
        new_text = await _fetch_from_dify(prompt_name, api_key)

        if new_text:
            _cache[prompt_name] = _CacheEntry(new_text, PROMPT_CACHE_TTL)
            logger.info(
                "[PromptLoader] 提示词已更新: prompt=%s 长度=%d字 TTL=%ds",
                prompt_name, len(new_text), PROMPT_CACHE_TTL,
            )
            return new_text

        # ── Dify 失败：降级处理 ──
        if entry:
            # 有旧缓存，继续使用（延长有效期避免每次都重试）
            entry.expires_at = time.monotonic() + PROMPT_CACHE_TTL
            logger.warning(
                "[PromptLoader] Dify 不可用，继续使用旧缓存: prompt=%s", prompt_name
            )
            return entry.text

        # 无任何缓存，使用硬编码兜底
        logger.warning(
            "[PromptLoader] Dify 不可用且无缓存，使用内置兜底提示词: prompt=%s", prompt_name
        )
        return fallback


def invalidate_cache(prompt_name: Optional[str] = None) -> None:
    """
    手动清除缓存（触发下次调用时强制从 Dify 拉取）。
    prompt_name 为 None 时清除全部缓存。
    """
    if prompt_name:
        _cache.pop(prompt_name, None)
        logger.info("[PromptLoader] 已清除缓存: prompt=%s", prompt_name)
    else:
        _cache.clear()
        logger.info("[PromptLoader] 已清除全部提示词缓存")


def cache_status() -> dict:
    """返回当前缓存状态（用于监控/调试）"""
    now = time.monotonic()
    return {
        name: {
            "cached": True,
            "expired": entry.is_expired,
            "expires_in_seconds": max(0, int(entry.expires_at - now)),
            "text_length": len(entry.text),
        }
        if (entry := _cache.get(name)) else {"cached": False}
        for name in _DIFY_APPS
    }
