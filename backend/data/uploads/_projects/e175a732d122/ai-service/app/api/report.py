"""
报告生成 API 路由模块

本模块定义了信审报告生成相关的 HTTP 接口，支持通过 SSE（Server-Sent Events）
实现流式输出，前端可以实时展示报告生成进度，提升用户体验。

所有接口注册在 FastAPI Router 下，由 main.py 挂载到 /api/v1/report 前缀。

提供以下接口：
1. POST /generate — 流式生成信审分析报告（SSE 输出）

调用流程（典型场景）：
    Java 后端完成流水解析和统计分析 → 将分析数据发送到本接口
    → AI 模型流式生成报告 → 前端通过 SSE 实时展示生成进度

接口设计原则：
- 使用 SSE（Server-Sent Events）协议实现流式输出，兼容性好
- 支持自定义报告模板（prompt），可针对不同银行、不同业务场景定制
- 错误信息通过 SSE 事件流返回，前端可统一处理
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.parsers.prompts import DEFAULT_REPORT_PROMPT
from app.providers import get_provider

# 模块级日志器，日志中会显示 "app.api.report" 便于按模块过滤
logger = logging.getLogger(__name__)

# 创建 FastAPI 路由器实例
# 注意：prefix 在 main.py 中设置为 /api/v1/report，此处的路径是相对路径
router = APIRouter()


# ============================================================================
# 请求模型定义（Pydantic）
# ============================================================================

class ReportRequest(BaseModel):
    """
    报告生成请求模型

    前端或 Java 后端将银行流水的统计分析数据传入，
    由 AI 模型根据数据生成专业的信审分析报告。

    字段说明：
        analysis_data: 银行流水统计分析数据，字典格式，包含各维度的分析结果。
                       示例：
                       {
                           "total_income": 500000.00,
                           "total_expense": 350000.00,
                           "monthly_stats": [...],
                           "top_counterparties": [...],
                           "risk_indicators": {...}
                       }
        template: 自定义报告模板（Prompt），为 None 时使用默认模板。
                  模板中可使用 {data} 占位符，运行时会被替换为 analysis_data 的 JSON 字符串。
                  适用于针对不同银行、不同业务场景定制报告格式。
    """
    analysis_data: dict = Field(
        ...,
        description="银行流水统计分析数据（JSON 对象）",
    )
    template: Optional[str] = Field(
        default=None,
        description="自定义报告生成 Prompt 模板（覆盖默认值），使用 {data} 占位符",
    )


# ============================================================================
# API 接口定义
# ============================================================================

@router.post(
    "/generate",
    summary="生成分析报告",
    description="根据银行流水分析数据，使用 AI 模型流式生成信审分析报告",
)
async def generate_report(request: ReportRequest):
    """
    流式生成信审分析报告

    接收银行流水的统计分析数据，调用文本大模型以流式方式生成专业的信审报告。
    返回 SSE（Server-Sent Events）格式的流式响应，前端可以通过 EventSource API
    实时接收并展示报告生成进度，实现打字机效果。

    SSE 数据格式说明：
    - 正常数据事件：  data: {"content": "报告文本片段"}\n\n
    - 完成事件：      data: {"content": "", "done": true}\n\n
    - 错误事件：      data: {"error": "错误信息"}\n\n

    请求示例：
        POST /api/v1/report/generate
        {
            "analysis_data": {
                "total_income": 500000.00,
                "total_expense": 350000.00,
                "avg_monthly_income": 41666.67,
                "risk_indicators": {"large_transaction_count": 3}
            },
            "template": null
        }

    响应说明：
        Content-Type: text/event-stream
        每个事件以 "data: " 开头，以 "\n\n" 结尾（SSE 标准格式）
    """
    logger.info(
        "[report] 报告生成开始 | data_fields=%d | custom_template=%s",
        len(request.analysis_data),
        "是" if request.template else "否",
    )

    # 校验分析数据不能为空字典
    if not request.analysis_data:
        raise HTTPException(
            status_code=400,
            detail="分析数据不能为空",
        )

    try:
        # 创建 AI 模型提供商实例
        ai_provider = get_provider()

        # 选择使用的 Prompt 模板：优先使用自定义模板，否则使用默认模板
        prompt_template = request.template or DEFAULT_REPORT_PROMPT

        # 将分析数据序列化为格式化的 JSON 字符串
        # ensure_ascii=False 确保中文字符正常显示（不被转义为 \uXXXX）
        # indent=2 使 JSON 结构清晰，便于大模型理解数据层级关系
        data_json = json.dumps(
            request.analysis_data,
            ensure_ascii=False,
            indent=2,
        )

        # 将 Prompt 模板中的 {data} 占位符替换为实际的分析数据 JSON
        prompt = prompt_template.replace("{data}", data_json)

        logger.info(
            "[report] Prompt 准备完成 | prompt_len=%d | data_json_len=%d",
            len(prompt),
            len(data_json),
        )

        async def event_stream():
            """
            SSE 事件流生成器

            调用 AI 模型的流式接口（stream_chat），逐步接收模型生成的文本片段，
            将每个片段封装为 SSE 标准格式的事件（data: {...}\n\n）并逐个 yield。

            流程：
            1. 调用 ai_provider.stream_chat() 获取异步生成器
            2. 逐个读取生成的文本片段（chunk）
            3. 将每个 chunk 封装为 JSON 并以 SSE 格式输出
            4. 所有 chunk 输出完毕后，发送完成标记事件
            5. 如果过程中发生异常，发送错误事件并终止流
            """
            try:
                # 调用流式文本模型，data_json 作为用户输入内容
                async for chunk in ai_provider.stream_chat(prompt, data_json):
                    # 将文本片段封装为 SSE 事件格式
                    # 使用 JSON 格式确保特殊字符（如换行符）被正确转义
                    event_data = json.dumps(
                        {"content": chunk},
                        ensure_ascii=False,
                    )
                    yield f"data: {event_data}\n\n"

                # 所有内容生成完毕，发送完成标记
                # 前端收到 done=true 后关闭 SSE 连接
                done_data = json.dumps(
                    {"content": "", "done": True},
                    ensure_ascii=False,
                )
                yield f"data: {done_data}\n\n"

                logger.info("[report] 流式输出完成")

            except Exception as e:
                # 流式生成过程中发生异常，通过 SSE 事件通知前端
                logger.error("[report] 流式生成异常 | error=%s", str(e), exc_info=True)
                error_data = json.dumps(
                    {"error": f"报告生成失败: {str(e)}"},
                    ensure_ascii=False,
                )
                yield f"data: {error_data}\n\n"

        # 返回 SSE 格式的流式响应
        # media_type="text/event-stream" 是 SSE 协议规定的 Content-Type
        # 浏览器的 EventSource API 会自动解析此格式
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                # 禁用缓存：确保 SSE 数据实时到达前端，不被代理或浏览器缓存
                "Cache-Control": "no-cache",
                # 保持连接：SSE 需要长连接，不要提前断开
                "Connection": "keep-alive",
                # CORS 相关头：允许前端 JavaScript 读取 SSE 事件数据
                "X-Accel-Buffering": "no",
            },
        )

    except HTTPException:
        # 重新抛出已知的 HTTP 异常（如参数校验失败）
        raise
    except Exception as e:
        logger.error("[report] 服务异常 | error=%s", str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"报告生成服务异常: {str(e)}",
        )
