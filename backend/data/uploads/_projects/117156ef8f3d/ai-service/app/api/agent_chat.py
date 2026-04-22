"""
智能体问答 API
"""
import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.parsers.prompts import (
    AGENT_SYSTEM_PROMPT,
    STATEMENT_QUERY_PROMPT,
    SKILL_FROM_NL_PROMPT,
)
from app.providers import get_provider
from app.utils import extract_json_raw

logger = logging.getLogger(__name__)
router = APIRouter()

# API 单字符串最大约 20M 字符，截断上下文避免超限
_MAX_CONTEXT_CHARS = 15_000_000


def _truncate_for_api(text: str, label: str = "数据") -> str:
    """若文本超长则截断并附加说明，避免 API 20M 限制"""
    if len(text) <= _MAX_CONTEXT_CHARS:
        return text
    logger.warning("[agent] %s超长已截断 | 原长=%d | 截断后=%d", label, len(text), _MAX_CONTEXT_CHARS)
    return text[:_MAX_CONTEXT_CHARS] + f"\n\n...（已截断，原 {label} 共 {len(text)} 字符）"


def _parse_reasoning_and_answer(text: str) -> tuple[str, str]:
    """解析 [思考] 和 [回答] 块，返回 (reasoning, answer)"""
    reasoning = ""
    answer = text
    m_think = re.search(r"\[思考\]\s*([\s\S]*?)\s*\[/思考\]", text, re.IGNORECASE)
    m_answer = re.search(r"\[回答\]\s*([\s\S]*?)\s*\[/回答\]", text, re.IGNORECASE)
    if m_think:
        reasoning = m_think.group(1).strip()
    if m_answer:
        answer = m_answer.group(1).strip()
    elif not reasoning:
        answer = text
    else:
        answer = text.replace(m_think.group(0), "").strip()
    if not answer and reasoning:
        answer = reasoning
    return (reasoning, answer or text)


def _extract_json(text: str) -> dict | None:
    """从模型输出中提取 JSON 对象，非 dict 返回 None"""
    raw = extract_json_raw(text)
    return raw if isinstance(raw, dict) else None


class AgentChatRequest(BaseModel):
    context: dict = Field(..., description="上下文数据")
    question: str = Field(..., description="用户问题")


class StatementQueryRequest(BaseModel):
    question: str = Field(..., description="用户问题")
    subject_name: str = Field("", description="主体名称")


class SkillFromNLRequest(BaseModel):
    description: str = Field(..., description="自然语言描述的需求")


class ChatWithSqlRequest(BaseModel):
    system_prompt: str = Field(..., description="系统提示词（来自 prompt_template AGENT_QA）")
    question: str = Field(..., description="用户问题")
    subject_id: int = Field(..., description="主体 ID")
    subject_name: str = Field("", description="主体名称")


class AnswerWithDataRequest(BaseModel):
    system_prompt: str = Field(..., description="系统提示词")
    question: str = Field(..., description="用户问题")
    query_results: list = Field(..., description="SQL 查询结果")


def _extract_need_query(text: str) -> dict | None:
    """从模型输出中提取 needQuery 块"""
    data = _extract_json(text)
    if data and data.get("needQuery") is True and data.get("sql"):
        return data
    return None


@router.post("/chat-with-sql", summary="智能体问答（SQL 驱动）")
async def chat_with_sql(request: ChatWithSqlRequest) -> dict:
    """
    使用 system_prompt 作为系统提示，根据问题生成 SQL 或直接回答。
    若 AI 输出 needQuery+sql，则返回给后端执行；否则解析 [思考][回答] 返回 answer。
    """
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    provider = get_provider()
    user_msg = f"""当前主体：{request.subject_name or '未知'}（ID: {request.subject_id}）

用户问题：{request.question}

请根据系统提示中的数据库 schema 和问题，如需查数据则输出 JSON 块：
```json
{{"needQuery":true,"sql":"SELECT ... WHERE f.subject_id = ?","reason":"查询原因"}}
```
否则按 [思考]...[/思考] 和 [回答]...[/回答] 格式直接回答。"""

    try:
        raw = await provider.chat(request.system_prompt, user_msg)
        raw = raw.strip()

        # 优先检查是否请求执行 SQL
        need_query = _extract_need_query(raw)
        if need_query:
            return {
                "needQuery": True,
                "sql": need_query.get("sql", ""),
                "reason": need_query.get("reason", ""),
                "answer": None,
                "reasoning": None,
            }

        # 否则解析 [思考][回答]
        reasoning, answer = _parse_reasoning_and_answer(raw)
        return {
            "needQuery": False,
            "sql": None,
            "reason": None,
            "answer": answer,
            "reasoning": reasoning,
        }
    except Exception as e:
        logger.exception("[agent] chat-with-sql 失败 | error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer-with-data", summary="基于查询结果生成回答")
async def answer_with_data(request: AnswerWithDataRequest) -> dict:
    """根据 SQL 查询结果和用户问题，生成最终回答"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    provider = get_provider()
    results_json = json.dumps(request.query_results, ensure_ascii=False, indent=2)
    results_json = _truncate_for_api(results_json, "查询结果")
    user_msg = f"""【查询结果】
{results_json}

【用户问题】
{request.question}

请基于以上查询结果，按 [思考]...[/思考] 和 [回答]...[/回答] 格式输出回答。"""

    try:
        raw = await provider.chat(request.system_prompt, user_msg)
        raw = raw.strip()
        reasoning, answer = _parse_reasoning_and_answer(raw)
        return {"answer": answer, "reasoning": reasoning}
    except Exception as e:
        logger.exception("[agent] answer-with-data 失败 | error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/answer-with-data-stream", summary="基于查询结果流式生成回答")
async def answer_with_data_stream(request: AnswerWithDataRequest):
    """根据 SQL 查询结果和用户问题，流式生成最终回答（SSE）"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    from fastapi.responses import StreamingResponse

    provider = get_provider()
    results_json = json.dumps(request.query_results, ensure_ascii=False, indent=2)
    results_json = _truncate_for_api(results_json, "查询结果")
    user_msg = f"""【查询结果】
{results_json}

【用户问题】
{request.question}

请基于以上查询结果，按 [思考]...[/思考] 和 [回答]...[/回答] 格式输出回答。"""

    async def event_stream():
        try:
            async for chunk in provider.stream_chat(request.system_prompt, user_msg):
                event_data = json.dumps({"content": chunk}, ensure_ascii=False)
                yield f"data: {event_data}\n\n"
            yield f"data: {json.dumps({'content': '', 'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("[agent] answer-with-data-stream 失败 | error=%s", str(e))
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat", summary="智能体问答（旧版，基于上下文）")
async def agent_chat(request: AgentChatRequest) -> dict:
    """基于上下文回答用户问题"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    provider = get_provider()
    try:
        context_json = json.dumps(request.context, ensure_ascii=False, indent=2)
        context_json = _truncate_for_api(context_json, "上下文")
        prompt = f"""请根据以下上下文数据回答用户问题。

【上下文数据】
{context_json}

【用户问题】
{request.question}

请按 [思考]...[/思考] 和 [回答]...[/回答] 格式输出。"""
        raw = await provider.chat(AGENT_SYSTEM_PROMPT, prompt)
        raw = raw.strip()
        reasoning, answer = _parse_reasoning_and_answer(raw)
        return {
            "answer": answer,
            "reasoning": reasoning,
            "question": request.question,
        }
    except Exception as e:
        logger.exception("[agent] 智能体问答失败 | error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/statement-query", summary="问题→计算规格")
async def statement_query(request: StatementQueryRequest) -> dict:
    """根据用户问题和主体名称，生成流水计算规格"""
    if not request.question or not request.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    provider = get_provider()
    try:
        prompt = STATEMENT_QUERY_PROMPT.format(subject_name=request.subject_name or "未知")
        prompt += f"\n\n用户问题：{request.question}\n\n请输出 JSON："
        raw = await provider.chat("你是一个数据查询规格生成器，只输出 JSON。", prompt)
        data = _extract_json(raw)
        if data is None:
            return {"needComputation": False, "reason": "无法解析规格"}
        if data.get("needComputation") is False:
            return {"needComputation": False}
        return {"needComputation": True, "spec": data.get("spec", data)}
    except Exception as e:
        logger.exception("[agent] statement-query 失败 | error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skill-from-nl", summary="自然语言→Skill 配置")
async def skill_from_nl(request: SkillFromNLRequest) -> dict:
    """将自然语言需求解析为 Skill 配置"""
    if not request.description or not request.description.strip():
        raise HTTPException(status_code=400, detail="需求描述不能为空")

    provider = get_provider()
    try:
        prompt = SKILL_FROM_NL_PROMPT + f"\n\n用户需求：{request.description}\n\n请输出 JSON："
        raw = await provider.chat("你是一个 Skill 配置解析器，只输出 JSON。", prompt)
        data = _extract_json(raw)
        if data is None:
            raise HTTPException(status_code=400, detail="无法解析为 Skill 配置，请重新描述")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[agent] skill-from-nl 失败 | error=%s", str(e))
        raise HTTPException(status_code=500, detail=str(e))
