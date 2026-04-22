import asyncio
import os
import tempfile
from pathlib import Path

import httpx


_TMPDIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(_TMPDIR.name) / 'p1_test.db'}"

from main import app
from app.models.database import async_session, init_db
from app.services import ppt_service
from app.services.native_renderer_service import build_deckspec_from_slides, render_deck_to_pptx
from app.services.package_runtime import OFFICIAL_NATIVE_ORCHESTRATOR, OFFICIAL_NATIVE_RENDERER


asyncio.run(init_db())


def test_html_to_deckspec_semantic_adapter() -> None:
    deck = build_deckspec_from_slides(
        presentation_id="pres-p1-semantic",
        title="P1 Native Renderer",
        theme_id="tech_dark",
        slides_data=[
            {
                "index": 0,
                "type": "two-column",
                "html": (
                    "<section><h1>双栏页</h1><p>左侧讲结构，右侧放图表。</p>"
                    "<div style='display:flex; gap:24px'>"
                    "<div><h3>左侧要点</h3><p>覆盖工作流、权限、导出策略。</p></div>"
                    "<div><p>渲染效率 92%</p><p>成功率 98%</p><p>编辑保真 85%</p></div>"
                    "</div></section>"
                ),
                "speaker_notes": "two-column",
            },
            {
                "index": 1,
                "type": "icon-grid",
                "html": (
                    "<section><h1>卡片组</h1><div style='display:grid; grid-template-columns:repeat(3,1fr); gap:24px'>"
                    "<div><h3>能力一</h3><p>统一 DeckSpec 契约。</p></div>"
                    "<div><h3>能力二</h3><p>原生渲染服务。</p></div>"
                    "<div><h3>能力三</h3><p>版本升级与回滚。</p></div>"
                    "</div></section>"
                ),
                "speaker_notes": "cards",
            },
            {
                "index": 2,
                "type": "table",
                "html": (
                    "<section><h1>对比表</h1><p>对比现有链路与新链路。</p>"
                    "<table><tr><th>维度</th><th>Legacy</th><th>Native</th></tr>"
                    "<tr><td>输出</td><td>HTML-first</td><td>PPTX-first</td></tr>"
                    "<tr><td>编辑性</td><td>一般</td><td>更强</td></tr></table></section>"
                ),
                "speaker_notes": "table",
            },
            {
                "index": 3,
                "type": "chart",
                "html": "<section><h1>关键指标</h1><p>成功率 98%</p><p>平均导出时长 12</p><p>返工页数 3</p></section>",
                "speaker_notes": "chart",
            },
        ],
    )

    assert deck.deck_id == "pres-p1-semantic"
    assert [slide.layout_id for slide in deck.slides] == [
        "semantic.two-column",
        "semantic.card-group",
        "semantic.table",
        "semantic.chart",
    ]

    node_kinds = [{node.kind for node in slide.nodes} for slide in deck.slides]
    assert "group" in node_kinds[0]
    assert "group" in node_kinds[1]
    assert "table" in node_kinds[2]
    assert "chart" in node_kinds[3]


def test_native_renderer_integration() -> None:
    async def _run() -> None:
        deck = build_deckspec_from_slides(
            presentation_id="pres-p1-render",
            title="P1 Native Renderer Integration",
            theme_id="tech_dark",
            slides_data=[
                {
                    "index": 0,
                    "type": "table",
                    "html": (
                        "<section><h1>Native Export</h1><table><tr><th>阶段</th><th>状态</th></tr>"
                        "<tr><td>Adapter</td><td>完成</td></tr><tr><td>Renderer</td><td>完成</td></tr></table></section>"
                    ),
                    "speaker_notes": "integration",
                }
            ],
        )
        content, meta = await render_deck_to_pptx(deck)
        assert len(content) > 1024
        assert meta.get("slideCount") == 1

    asyncio.run(_run())


def test_native_orchestrator_workflow_api() -> None:
    async def _run() -> None:
        async with async_session() as session:
            await ppt_service.create_presentation(
                session,
                task_id="task-p1-native",
                presentation_id="pres-p1-workflow",
                title="Native Workflow",
                theme_id="tech_dark",
                outline=[],
            )
            await ppt_service.save_slides(
                session,
                "pres-p1-workflow",
                [
                    {
                        "index": 0,
                        "type": "two-column",
                        "html": (
                            "<section><h1>双栏工作流</h1><div style='display:flex; gap:24px'>"
                            "<div><h3>规划</h3><p>大纲、版式、依赖。</p></div>"
                            "<div><p>安装成功率 97%</p><p>导出成功率 99%</p></div></div></section>"
                        ),
                        "speaker_notes": "workflow-two-column",
                    },
                    {
                        "index": 1,
                        "type": "chart",
                        "html": "<section><h1>指标</h1><p>渲染成功率 99%</p><p>平均时延 14</p><p>返工页数 2</p></section>",
                        "speaker_notes": "workflow-chart",
                    },
                ],
            )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/presentations/pres-p1-workflow/workflows/native-pptx",
                json={"persist_artifact": False},
            )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["workflow"]["package_id"] == OFFICIAL_NATIVE_ORCHESTRATOR
        assert payload["renderer"]["package_id"] == OFFICIAL_NATIVE_RENDERER
        assert payload["deck_summary"]["slide_count"] == 2
        assert payload["deck_summary"]["layout_ids"] == [
            "semantic.two-column",
            "semantic.chart",
        ]

    asyncio.run(_run())


def run_all_tests() -> None:
    if not os.getenv("NATIVE_RENDERER_URL"):
        os.environ["NATIVE_RENDERER_URL"] = "http://127.0.0.1:4100"
    test_html_to_deckspec_semantic_adapter()
    test_native_renderer_integration()
    test_native_orchestrator_workflow_api()
    _TMPDIR.cleanup()
    print("P1 native renderer tests passed")


if __name__ == "__main__":
    run_all_tests()