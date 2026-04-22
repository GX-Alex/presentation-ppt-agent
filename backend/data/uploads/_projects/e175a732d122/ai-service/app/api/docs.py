"""
文档中心 API（内部服务）

本服务由 Java 后端代理调用，用户应使用后端接口而非直接调用本服务。
此处文档仅供后端开发与运维参考。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["文档中心（内部）"])

# API 资产元数据：业务域、描述、典型用途
API_ASSETS = [
    {
        "id": "parse-detect",
        "path": "/api/v1/parse/detect",
        "method": "POST",
        "tag": "PDF解析",
        "summary": "检测文件类型和页数",
        "description": "快速检测 PDF/图片类型和总页数，用于解析前更新进度显示。图片文件返回 totalPages=1, pdfType=SCANNED。",
        "requestBody": {"file_path": "文件绝对路径"},
    },
    {
        "id": "parse-parse",
        "path": "/api/v1/parse/parse",
        "method": "POST",
        "tag": "PDF解析",
        "summary": "解析银行流水",
        "description": "解析 PDF 或图片银行流水，支持多页。首页有表头，后续页继承表头结构。返回结构化交易数据。",
        "requestBody": {"file_path": "文件路径", "pages": "可选，指定页码列表"},
    },
    {
        "id": "parse-parse-page",
        "path": "/api/v1/parse/parse-page",
        "method": "POST",
        "tag": "PDF解析",
        "summary": "解析单页",
        "description": "解析指定单页，用于失败重试场景。",
        "requestBody": {"file_path": "文件路径", "page_number": "页码"},
    },
    {
        "id": "parse-parse-multi",
        "path": "/api/v1/parse/parse-multi",
        "method": "POST",
        "tag": "PDF解析",
        "summary": "多文件一次性解析",
        "description": "将多个 PDF/图片一次性传入大模型，按 sourceIndex 分组返回，减少调用次数。",
        "requestBody": {"file_paths": "文件路径列表"},
    },
    {
        "id": "report-generate",
        "path": "/api/v1/report/generate",
        "method": "POST",
        "tag": "报告生成",
        "summary": "流式生成信审报告",
        "description": "根据银行流水分析数据，使用 AI 流式生成信审分析报告。返回 SSE 格式，支持实时展示。",
        "requestBody": {"analysis_data": "分析数据对象", "template": "可选，自定义 Prompt 模板"},
    },
    {
        "id": "tag-classify",
        "path": "/api/v1/tag/classify",
        "method": "POST",
        "tag": "智能标签",
        "summary": "交易智能分类",
        "description": "对已解析的交易记录进行智能分类，为每笔交易添加 category 标签（如工资收入、日常消费等）。",
        "requestBody": {"transactions": "交易记录列表", "prompt": "可选，自定义分类 Prompt"},
    },
    {
        "id": "financial-report-parse",
        "path": "/api/v1/financial-report/parse",
        "method": "POST",
        "tag": "财报解析",
        "summary": "解析财报",
        "description": "解析利润表或资产负债表图片/PDF，提取营业收入、营业利润、净利润、总资产等关键数据。",
        "requestBody": {"file_path": "文件路径", "report_type": "可选 INCOME_STATEMENT/BALANCE_SHEET"},
    },
    {
        "id": "agent-chat-with-sql",
        "path": "/api/v1/agent/chat-with-sql",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "智能体问答（SQL 驱动）",
        "description": "根据问题生成 SQL 或直接回答。若需查数据则返回 needQuery+sql，否则返回 [思考][回答] 格式。",
        "requestBody": {"system_prompt": "系统提示词", "question": "用户问题", "subject_id": "主体ID", "subject_name": "主体名称"},
    },
    {
        "id": "agent-answer-with-data",
        "path": "/api/v1/agent/answer-with-data",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "基于查询结果生成回答",
        "description": "根据 SQL 查询结果和用户问题，生成最终回答。",
        "requestBody": {"system_prompt": "系统提示词", "question": "用户问题", "query_results": "查询结果列表"},
    },
    {
        "id": "agent-answer-with-data-stream",
        "path": "/api/v1/agent/answer-with-data-stream",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "基于查询结果流式生成回答",
        "description": "流式生成回答，返回 SSE 格式。",
        "requestBody": {"system_prompt": "系统提示词", "question": "用户问题", "query_results": "查询结果列表"},
    },
    {
        "id": "agent-chat",
        "path": "/api/v1/agent/chat",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "智能体问答（基于上下文）",
        "description": "基于上下文数据（流水汇总、财报、分析结果等）回答用户问题。",
        "requestBody": {"context": "上下文数据", "question": "用户问题"},
    },
    {
        "id": "agent-statement-query",
        "path": "/api/v1/agent/statement-query",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "问题→计算规格",
        "description": "根据用户问题生成流水数据计算规格（groupBy、aggregation、dateRange 等）。",
        "requestBody": {"question": "用户问题", "subject_name": "主体名称"},
    },
    {
        "id": "agent-skill-from-nl",
        "path": "/api/v1/agent/skill-from-nl",
        "method": "POST",
        "tag": "智能体问答",
        "summary": "自然语言→Skill 配置",
        "description": "将自然语言需求解析为 Appolo 分析 Skill 配置（COMPLETENESS_CHECK、INDICATOR_CALC 等）。",
        "requestBody": {"description": "自然语言描述的需求"},
    },
    {
        "id": "health",
        "path": "/health",
        "method": "GET",
        "tag": "系统",
        "summary": "健康检查",
        "description": "用于容器编排的存活探针和就绪探针，返回服务状态。",
        "requestBody": None,
    },
]


@router.get(
    "/api/v1/docs/catalog",
    summary="API 资产目录",
    description="返回所有对外 API 的资产化清单，供程序或文档系统消费。按业务域分组，包含路径、方法、描述、请求参数说明。",
)
async def get_api_catalog(request: Request) -> JSONResponse:
    """获取 API 资产目录"""
    base_url = str(request.base_url).rstrip("/")
    catalog = {
        "service": "Appolo AI 服务",
        "version": "1.0.0",
        "description": "银行流水智能解析与报告生成服务，使用大模型解析 PDF/图片",
        "baseUrl": base_url,
        "openApiSpec": f"{base_url}/openapi.json",
        "swaggerUi": f"{base_url}/docs",
        "redoc": f"{base_url}/redoc",
        "docsCenter": f"{base_url}/docs-center",
        "apis": [
            {**asset, "fullUrl": f"{base_url}{asset['path']}"}
            for asset in API_ASSETS
        ],
        "tags": [
            {"name": "PDF解析", "description": "银行流水 PDF/图片解析"},
            {"name": "报告生成", "description": "信审报告流式生成"},
            {"name": "智能标签", "description": "交易智能分类"},
            {"name": "财报解析", "description": "利润表、资产负债表解析"},
            {"name": "智能体问答", "description": "基于上下文的智能问答"},
            {"name": "系统", "description": "健康检查等系统接口"},
        ],
    }
    return JSONResponse(content=catalog, media_type="application/json")


@router.get(
    "/docs-center",
    summary="文档中心（内部参考）",
    response_class=HTMLResponse,
    include_in_schema=False,
)
async def docs_center(request: Request) -> HTMLResponse:
    """AI 服务内部文档入口。用户请使用后端 /api/docs 查看完整 API 文档。"""
    base_url = str(request.base_url).rstrip("/")
    # 按 tag 分组
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for api in API_ASSETS:
        tag = api["tag"]
        if tag not in by_tag:
            by_tag[tag] = []
        by_tag[tag].append({**api, "fullUrl": f"{base_url}{api['path']}"})

    tag_order = ["PDF解析", "报告生成", "智能标签", "财报解析", "智能体问答", "系统"]
    html_apis = ""
    for tag in tag_order:
        if tag not in by_tag:
            continue
        apis = by_tag[tag]
        html_apis += f'<section class="api-group"><h2>{tag}</h2>'
        for api in apis:
            html_apis += f"""
            <div class="api-card">
                <div class="api-header">
                    <span class="method">{api["method"]}</span>
                    <code class="path">{api["path"]}</code>
                </div>
                <h3>{api["summary"]}</h3>
                <p class="desc">{api["description"]}</p>
                <div class="api-links">
                    <a href="{base_url}/docs" target="_blank">Swagger 调试</a>
                </div>
            </div>
            """
        html_apis += "</section>"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Appolo AI 服务 - 文档中心</title>
    <style>
        :root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --accent: #38bdf8; --muted: #94a3b8; }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; padding: 2rem; }}
        header {{ margin-bottom: 2.5rem; padding-bottom: 1.5rem; border-bottom: 1px solid #334155; }}
        h1 {{ font-size: 1.75rem; color: var(--accent); margin-bottom: 0.5rem; }}
        .subtitle {{ color: var(--muted); font-size: 0.95rem; }}
        .links {{ margin-top: 1rem; display: flex; gap: 1rem; flex-wrap: wrap; }}
        .links a {{ color: var(--accent); text-decoration: none; font-size: 0.9rem; }}
        .links a:hover {{ text-decoration: underline; }}
        .api-group {{ margin-bottom: 2rem; }}
        .api-group h2 {{ font-size: 1.1rem; color: var(--muted); margin-bottom: 1rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        .api-card {{ background: var(--card); border-radius: 8px; padding: 1.25rem; margin-bottom: 1rem; border-left: 3px solid var(--accent); }}
        .api-header {{ display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem; }}
        .method {{ font-weight: 600; color: #4ade80; font-size: 0.8rem; }}
        .path {{ font-size: 0.9rem; color: var(--accent); }}
        .api-card h3 {{ font-size: 1rem; margin-bottom: 0.5rem; }}
        .desc {{ color: var(--muted); font-size: 0.9rem; margin-bottom: 0.75rem; }}
        .api-links a {{ color: var(--accent); font-size: 0.85rem; text-decoration: none; }}
        .api-links a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Appolo AI 服务 - 文档中心</h1>
            <p class="subtitle">API 服务资产化 · 银行流水智能解析与报告生成</p>
            <div class="links">
                <a href="{base_url}/docs" target="_blank">Swagger UI（交互式调试）</a>
                <a href="{base_url}/redoc" target="_blank">ReDoc（阅读版文档）</a>
                <a href="{base_url}/openapi.json" target="_blank">OpenAPI 规范</a>
                <a href="{base_url}/api/v1/docs/catalog" target="_blank">API 资产目录（JSON）</a>
            </div>
        </header>
        <section>
            <h2>快速开始</h2>
            <p class="desc" style="margin-bottom:1rem;">所有接口均需 POST JSON（除健康检查为 GET）。请求示例：</p>
            <pre style="background:var(--card);padding:1rem;border-radius:6px;font-size:0.85rem;overflow-x:auto;">POST /api/v1/parse/detect
Content-Type: application/json

{{"file_path": "/path/to/your/bank_statement.pdf"}}</pre>
        </section>
        {html_apis}
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)
