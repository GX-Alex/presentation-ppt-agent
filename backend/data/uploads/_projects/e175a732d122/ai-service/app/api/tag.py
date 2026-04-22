"""
智能标签分类 API 路由模块

本模块定义了银行流水交易智能分类相关的 HTTP 接口，利用文本大模型对已解析的
交易记录进行语义理解和分类标注。

所有接口注册在 FastAPI Router 下，可由 main.py 挂载到对应前缀。

提供以下接口：
1. POST /classify — 对交易列表进行智能分类，为每笔交易添加类别标签

调用流程（典型场景）：
    PDF 解析完成 → Java 后端获取交易列表 → 调用 /classify 进行智能分类
    → 返回带有 category 标签的交易列表 → 前端展示分类统计和可视化图表

分类标签体系说明：
    标签体系覆盖常见银行流水交易类型，分为收入类和支出类两大类：
    - 收入类：工资收入、经营收入、转账收入、贷款放款、其他收入
    - 支出类：日常消费、房租物业、贷款还款、转账支出、税费社保、投资理财、其他支出

    分类依据：
    - 交易摘要（summary）：包含关键词匹配，如"工资"、"房租"、"还款"等
    - 交易对手方（counterparty）：如"XX公司"、"XX银行"等
    - 交易方向：income 不为 null 归入收入类，expense 不为 null 归入支出类
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.parsers.prompts import DEFAULT_TAG_PROMPT
from app.parsers.pdf_parser import PdfAnalyzer
from app.providers import get_provider

# 模块级日志器，日志中会显示 "app.api.tag" 便于按模块过滤
logger = logging.getLogger(__name__)

# 创建 FastAPI 路由器实例
# 注意：prefix 由 main.py 统一设置，此处路径为相对路径
router = APIRouter()


# ============================================================================
# 请求/响应模型定义（Pydantic）
# ============================================================================

class TagRequest(BaseModel):
    """
    交易智能分类请求模型

    接收已解析的交易记录列表，由 AI 模型对每笔交易进行语义分析和分类标注。

    字段说明：
        transactions: 交易记录列表，每条记录为字典格式，至少包含以下字段：
                      - date (str): 交易日期
                      - summary (str): 交易摘要/备注
                      - counterparty (str): 交易对手方
                      - income (float|None): 收入金额
                      - expense (float|None): 支出金额
                      - balance (float|None): 交易后余额
                      示例：
                      [
                          {"date": "2024-01-15", "summary": "工资", "counterparty": "XX公司",
                           "income": 50000.00, "expense": null, "balance": 150000.00},
                          {"date": "2024-01-20", "summary": "房租", "counterparty": "XX物业",
                           "income": null, "expense": 5000.00, "balance": 145000.00}
                      ]
        prompt: 自定义分类 Prompt 模板（覆盖默认值），为 None 时使用默认标签体系。
                模板中可使用 {transactions} 占位符，运行时会被替换为交易列表的 JSON 字符串。
                适用于需要自定义分类标签体系的场景。
    """
    transactions: list[dict] = Field(
        ...,
        description="待分类的交易记录列表",
        min_length=1,
    )
    prompt: Optional[str] = Field(
        default=None,
        description="自定义分类 Prompt 模板（覆盖默认值），使用 {transactions} 占位符",
    )


# ============================================================================
# API 接口定义
# ============================================================================

@router.post(
    "/classify",
    summary="交易智能分类",
    description="对已解析的银行流水交易记录进行智能分类，为每笔交易添加类别标签",
)
async def classify_transactions(request: TagRequest):
    """
    对交易列表进行智能分类标注

    接收已解析的交易记录列表，调用文本大模型对每笔交易的摘要和对手方信息
    进行语义理解，自动为其分配分类标签（category 字段）。

    分类策略：
    1. 将全部交易记录序列化为 JSON 字符串
    2. 将 JSON 嵌入到分类 Prompt 模板中
    3. 调用文本大模型（如 qwen-max）进行批量分类
    4. 从模型响应中提取带有 category 字段的交易列表
    5. 如果模型返回的记录数与输入不匹配，回退到原始数据并记录警告

    批量处理说明：
    - 当交易记录数量较多（超过 50 条）时，会自动分批处理
    - 每批最多处理 50 条记录，避免超出模型上下文长度限制
    - 分批处理的结果会自动合并后返回

    请求示例：
        POST /api/v1/tag/classify
        {
            "transactions": [
                {"date": "2024-01-15", "summary": "工资", "counterparty": "XX科技公司",
                 "income": 50000.00, "expense": null, "balance": 150000.00},
                {"date": "2024-01-20", "summary": "美团外卖", "counterparty": "美团",
                 "income": null, "expense": 35.00, "balance": 149965.00}
            ]
        }

    响应示例：
        {
            "tagged_transactions": [
                {"date": "2024-01-15", "summary": "工资", "counterparty": "XX科技公司",
                 "income": 50000.00, "expense": null, "balance": 150000.00,
                 "category": "工资收入"},
                {"date": "2024-01-20", "summary": "美团外卖", "counterparty": "美团",
                 "income": null, "expense": 35.00, "balance": 149965.00,
                 "category": "日常消费"}
            ]
        }
    """
    logger.info("[tag] 分类开始 | transactions=%d", len(request.transactions))

    # 校验交易列表不能为空
    if not request.transactions:
        raise HTTPException(
            status_code=400,
            detail="交易记录列表不能为空",
        )

    try:
        # 创建 AI 模型提供商实例
        ai_provider = get_provider()

        # 选择使用的 Prompt 模板：优先使用自定义模板，否则使用默认模板
        prompt_template = request.prompt or DEFAULT_TAG_PROMPT

        # 每批处理的最大交易记录数
        # 控制每次发送给大模型的数据量，避免超出上下文窗口长度限制
        batch_size = 50

        # 存储所有分类完成的交易记录
        all_tagged = []

        # 分批处理交易记录
        for batch_start in range(0, len(request.transactions), batch_size):
            batch_end = min(batch_start + batch_size, len(request.transactions))
            batch = request.transactions[batch_start:batch_end]

            logger.info(
                "[tag] 批次处理中 | batch=%d-%d | total=%d",
                batch_start + 1,
                batch_end,
                len(request.transactions),
            )

            # 将当前批次的交易记录序列化为 JSON 字符串
            # ensure_ascii=False 确保中文摘要和对手方名称正常显示
            # indent=2 使数据结构清晰，便于大模型理解
            transactions_json = json.dumps(
                batch,
                ensure_ascii=False,
                indent=2,
            )

            # 将 Prompt 模板中的 {transactions} 占位符替换为实际交易数据
            filled_prompt = prompt_template.replace("{transactions}", transactions_json)

            # 调用文本大模型进行分类
            response = await ai_provider.chat(filled_prompt, transactions_json)

            # 从模型响应中鲁棒地提取 JSON 数据
            # 复用 PdfAnalyzer 的 JSON 提取方法，处理模型返回格式不一致的问题
            tagged_batch = PdfAnalyzer.extract_json_from_response(response)

            # 校验模型返回的记录数是否与输入一致
            if isinstance(tagged_batch, list) and len(tagged_batch) == len(batch):
                # 模型返回记录数匹配，使用模型分类结果
                all_tagged.extend(tagged_batch)
                logger.info(
                    "[tag] 批次完成 | batch=%d-%d | tagged=%d",
                    batch_start + 1,
                    batch_end,
                    len(tagged_batch),
                )
            elif isinstance(tagged_batch, list) and len(tagged_batch) > 0:
                # 模型返回记录数不匹配但有有效数据，仍然使用（可能模型合并或拆分了某些记录）
                all_tagged.extend(tagged_batch)
                logger.warning(
                    "[tag] 批次记录数不匹配 | input=%d | output=%d | 仍使用模型结果",
                    len(batch),
                    len(tagged_batch),
                )
            else:
                # 模型返回无效数据，回退到原始数据，标记为"未分类"
                logger.warning(
                    "[tag] 批次失败回退 | batch=%d-%d | 标记为未分类",
                    batch_start + 1,
                    batch_end,
                )
                for txn in batch:
                    txn["category"] = "未分类"
                all_tagged.extend(batch)

        logger.info("[tag] 分类完成 | total_tagged=%d", len(all_tagged))

        return {
            "tagged_transactions": all_tagged,
        }

    except HTTPException:
        # 重新抛出已知的 HTTP 异常（如参数校验失败）
        raise
    except Exception as e:
        logger.error("[tag] 服务异常 | error=%s", str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"交易分类服务异常: {str(e)}",
        )
