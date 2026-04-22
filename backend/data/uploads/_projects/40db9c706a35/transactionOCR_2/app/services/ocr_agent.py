"""
流水提取 Agent 核心流程 — LangGraph 实现
参考「账单提取核心.yml」Dify DSL 的工作流逻辑：

  START
    ├── LLM 2: 从图片提取交易流水 → Markdown 表格
    ├── LLM 3: 从图片提取客户元数据 → JSON
    └── 代码执行: 合并结果
  END

使用 LangGraph 编排两个 LLM 节点并行执行，然后合并结果。
LLM 通过 OpenAI 兼容接口调用阿里云百炼 Qwen-VL。
"""
import json
import re
import logging
import operator
from typing import TypedDict, Optional, Annotated, List

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END

from app.config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_EXTRACT_MODEL,
    LLM_META_MODEL,
    LLM_ENABLE_THINKING,
    LLM_EXTRACT_TEMPERATURE,
    LLM_META_TEMPERATURE,
    REQUEST_TIMEOUT,
)
from app.services.prompt_loader import get_prompt

logger = logging.getLogger("transaction_ocr")


def _mask_data_url(text: str, max_b64_len: int = 80) -> str:
    """将 base64 data URL 的 base64 部分截断，避免日志暴增"""
    return re.sub(
        r"(data:[^;]+;base64,)([A-Za-z0-9+/=]{" + str(max_b64_len) + r"})[A-Za-z0-9+/=]*",
        r"\1\2...[TRUNCATED]",
        text,
    )


# ══════════════════════════════════════════════════════════════
#  Prompt — 运行时从 Dify 动态拉取（TTL 10 分钟），失败自动降级到内置文本
#  修改提示词请在 Dify 平台操作，无需重启服务
#  兜底提示词在 app/services/prompt_loader.py 中维护
# ══════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════
#  LangGraph State
# ══════════════════════════════════════════════════════════════

def _concat_errors(a: list[str], b: list[str]) -> list[str]:
    return (a or []) + (b or [])


class AgentState(TypedDict):
    image_urls: List[str]          # 图片 URL 数组（支持多图一次请求）
    transactions_md: Optional[str]
    metadata_json: Optional[str]
    merged_result: Optional[str]
    errors: Annotated[list[str], _concat_errors]
    # 分块并发控制字段
    header_only_first: Optional[bool]  # True=第1张图仅作表头参考，不提取其交易数据
    skip_metadata: Optional[bool]      # True=跳过元数据提取节点（非首块使用）


# ══════════════════════════════════════════════════════════════
#  LLM 实例（OpenAI 兼容方式调用百炼）
# ══════════════════════════════════════════════════════════════

def _get_llm(model: str, temperature: float = 0.1, max_tokens: int = None) -> ChatOpenAI:
    """创建 LLM 实例，Qwen3 系列自动添加非思考模式参数"""
    from app.config import LLM_EXTRACT_MAX_TOKENS
    
    # 使用 LLM_EXTRACT_MAX_TOKENS 作为 max_tokens 默认值
    if max_tokens is None:
        max_tokens = LLM_EXTRACT_MAX_TOKENS
    
    kwargs = dict(
        model=model,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=REQUEST_TIMEOUT,
    )
    # Qwen3 系列支持 enable_thinking 控制思考模式
    # 非思考模式：输出更稳定、速度更快，适合结构化信息提取
    if not LLM_ENABLE_THINKING:
        kwargs["extra_body"] = {"enable_thinking": False}
    return ChatOpenAI(**kwargs)


# ══════════════════════════════════════════════════════════════
#  节点函数
# ══════════════════════════════════════════════════════════════

async def extract_transactions(state: AgentState) -> dict:
    """LLM 2: 从图片数组提取交易流水 Markdown 表格（支持多图一次请求）"""
    image_urls = state["image_urls"]
    header_only_first: bool = state.get("header_only_first") or False
    # 日志中只记录图片数量，不打印完整 URL（避免 base64 暴露）
    logger.info(
        "[Node:extract_transactions] 开始 — 共 %d 张图片，header_only_first=%s",
        len(image_urls), header_only_first,
    )
    try:
        llm = _get_llm(LLM_EXTRACT_MODEL, temperature=LLM_EXTRACT_TEMPERATURE)
        # 构建多图片内容列表
        image_contents = [
            {"type": "image_url", "image_url": {"url": url, "detail": "high"}}
            for url in image_urls
        ]
        # 从 Dify 动态获取提示词（带 TTL 缓存，失败自动降级到内置提示词）
        prompt_text = await get_prompt("extract_transactions")
        # 分块模式：非首块需额外补充"不从第1张提取"的指令
        if header_only_first and len(image_urls) > 1:
            prompt_text += "\n\n【重要】注意：第1张图片仅作为表头格式参考，请不要从第1张图片中提取任何交易记录数据。从第2张图片开始提取实际流水。"
        
        # 用户消息：文本 Prompt 在前，图片在后
        human_content = [
            {"type": "text", "text": prompt_text}
        ] + image_contents
        
        messages = [
            SystemMessage(content="你是一个专业的银行流水提取助手，能从图片中提取结构化的交易流水信息,照接收图片的顺序输出交易记录，输出 Markdown 表格。请严格按照用户提示中的规则执行，不要输出任何多余文字。"),
            HumanMessage(content=human_content),
        ]
        # 打印请求报文（system prompt 全量）
        logger.info(
            "[Node:extract_transactions] LLM请求报文 — model=%s  图片数=%d  system_prompt=\n%s",
            LLM_EXTRACT_MODEL, len(image_urls), prompt_text,
        )
        resp = await llm.ainvoke(messages)
        content = resp.content
        # 打印响应报文（全量）
        logger.info(
            "[Node:extract_transactions] LLM响应报文 — 长度=%d字\n%s",
            len(content), content,
        )
        return {"transactions_md": content}
    except Exception as e:
        logger.error("[Node:extract_transactions] 失败: %s", e, exc_info=True)
        return {"transactions_md": "", "errors": [f"extract_transactions: {e}"]}


async def extract_metadata(state: AgentState) -> dict:
    """LLM 3: 从图片数组中逐张查找含表头的图片，提取客户元数据 JSON"""
    # 分块模式：非首块跳过元数据提取，直接返回空（元数据由首块统一提供）
    if state.get("skip_metadata"):
        logger.info("[Node:extract_metadata] skip_metadata=True，跳过元数据提取")
        return {"metadata_json": "{}"}
    image_urls = state["image_urls"]
    logger.info("[Node:extract_metadata] 开始 — 共 %d 张图片，逐张查找表头", len(image_urls))
    try:
        llm = _get_llm(LLM_META_MODEL, temperature=LLM_META_TEMPERATURE)
        last_content = "{}"
        # 从 Dify 动态获取提示词（带 TTL 缓存，失败自动降级到内置提示词）
        metadata_prompt = await get_prompt("extract_metadata")

        for i, url in enumerate(image_urls):
            # 日志中记录掩码后的 URL
            masked_url = _mask_data_url(url) if url.startswith("data:") else (url[:100] if len(url) > 100 else url)
            messages = [
                SystemMessage(content=metadata_prompt),
                HumanMessage(content=[
                    {"type": "image_url", "image_url": {"url": url, "detail": "high"}},
                ]),
            ]
            logger.debug(
                "[Node:extract_metadata] LLM请求报文 — model=%s  图片=%d/%d  url=%s",
                LLM_META_MODEL, i + 1, len(image_urls), masked_url,
            )
            resp = await llm.ainvoke(messages)
            content = resp.content
            last_content = content
            logger.info(
                "[Node:extract_metadata] 图片 %d/%d LLM响应 — 长度=%d字\n%s",
                i + 1, len(image_urls), len(content), content,
            )

            # 检查是否获得有效元数据（至少一个非 null 字段）
            json_clean = re.sub(r"```(?:json)?\s*|\s*```", "", content.strip())
            try:
                metadata = json.loads(json_clean)
                if any(v is not None for v in metadata.values()):
                    logger.info("[Node:extract_metadata] 图片 %d 包含有效表头，停止查找", i + 1)
                    return {"metadata_json": content}
            except json.JSONDecodeError:
                pass

        # 所有图片均未找到有效元数据，返回最后一次响应
        logger.warning("[Node:extract_metadata] 所有 %d 张图片均未找到有效表头元数据", len(image_urls))
        return {"metadata_json": last_content}
    except Exception as e:
        logger.error("[Node:extract_metadata] 失败: %s", e, exc_info=True)
        return {"metadata_json": "{}", "errors": [f"extract_metadata: {e}"]}


def merge_results(state: AgentState) -> dict:
    """代码执行 2: 合并流水 Markdown + 元数据 JSON → 最终 JSON"""
    logger.info("[Node:merge_results] 开始合并")
    logger.debug(
        "[Node:merge_results] 输入 transactions_md(前200)=%s",
        (state.get("transactions_md") or "")[:200],
    )
    logger.debug(
        "[Node:merge_results] 输入 metadata_json=%s",
        state.get("metadata_json", ""),
    )
    try:
        markdown_text = state.get("transactions_md", "")
        json_text = state.get("metadata_json", "{}")

        # 清理 JSON 包装
        json_clean = re.sub(r"```(?:json)?\s*|\s*```", "", json_text.strip())
        try:
            metadata = json.loads(json_clean)
        except json.JSONDecodeError:
            logger.warning("元数据 JSON 解析失败，使用空字典。原文: %s", json_clean[:200])
            metadata = {}

        result = {
            **metadata,
            "transactions": markdown_text.strip(),
        }

        merged_str = json.dumps(result, ensure_ascii=False, indent=2)
        logger.info(
            "[Node:merge_results] 合并完成 — 共%d字\n%s",
            len(merged_str), merged_str[:500],
        )
        return {"merged_result": merged_str}
    except Exception as e:
        logger.error("merge_results 失败: %s", e, exc_info=True)
        return {"merged_result": None, "errors": [f"merge_results: {e}"]}


# ══════════════════════════════════════════════════════════════
#  构建 LangGraph 工作流
# ══════════════════════════════════════════════════════════════

def build_ocr_graph() -> StateGraph:
    """
    构建 OCR Agent Graph：

    START ─┬─► extract_transactions ─┐
           └─► extract_metadata     ─┤
                                     └─► merge_results ─► END
    """
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("extract_transactions", extract_transactions)
    graph.add_node("extract_metadata", extract_metadata)
    graph.add_node("merge_results", merge_results)

    # START → 两个 LLM 节点（并行 fan-out）
    graph.add_edge(START, "extract_transactions")
    graph.add_edge(START, "extract_metadata")

    # 两个 LLM 节点 → merge（fan-in）
    graph.add_edge("extract_transactions", "merge_results")
    graph.add_edge("extract_metadata", "merge_results")

    # merge → END
    graph.add_edge("merge_results", END)

    return graph


# 编译后的可执行工作流（模块级单例）
_compiled_graph = None


def get_ocr_agent():
    """获取编译后的 OCR Agent（懒加载单例）"""
    global _compiled_graph
    if _compiled_graph is None:
        g = build_ocr_graph()
        _compiled_graph = g.compile()
        logger.info("OCR Agent Graph 编译完成")
    return _compiled_graph


async def run_ocr_agent(
    image_urls: List[str],
    header_only_first: bool = False,
    skip_metadata: bool = False,
) -> Optional[dict]:
    """
    执行 OCR Agent，输入图片 URL / base64 data URL 数组，
    一次性将所有图片发送给 VLM，返回包含 transactions 和客户元数据的字典。

    Args:
        image_urls: 图片 URL 或 base64 data URL 列表（单张或多张）
        header_only_first: True=第1张图仅作表头格式参考，不提取其交易数据（分块非首块使用）
        skip_metadata: True=跳过元数据提取节点（分块非首块使用）

    Returns:
        dict: {"客户名称": ..., "客户账号": ..., "账户所属机构": ..., "transactions": "..."}
        None: 执行失败
    """
    agent = get_ocr_agent()
    logger.info(
        "[OCR Agent] 启动 — 共 %d 张图片  header_only_first=%s  skip_metadata=%s",
        len(image_urls), header_only_first, skip_metadata,
    )
    try:
        result = await agent.ainvoke({
            "image_urls": image_urls,
            "header_only_first": header_only_first,
            "skip_metadata": skip_metadata,
        })
        errors = result.get("errors") or []
        if errors:
            logger.warning("[OCR Agent] 节点错误: %s", errors)
        merged = result.get("merged_result")
        if merged:
            parsed = json.loads(merged)
            logger.info("[OCR Agent] 完成 — 字段: %s", list(parsed.keys()))
            return parsed
        logger.warning("[OCR Agent] 返回空结果")
        return None
    except Exception as e:
        logger.error("[OCR Agent] run_ocr_agent 失败: %s", e, exc_info=True)
        return None
