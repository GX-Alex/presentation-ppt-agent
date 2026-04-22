import asyncio
from types import SimpleNamespace

from app.services.webdeck_runtime.page_orchestrator import PageOrchestrator


def test_plan_lanes_keeps_multiple_chart_assets() -> None:
    orchestrator = PageOrchestrator()

    lanes = orchestrator._plan_lanes(
        page_id="p06",
        page_kind="chart_analysis",
        asset_reqs=[
            {"type": "chart", "kind": "line_chart", "description": "投资回报曲线"},
            {"type": "chart", "kind": "bar_chart", "description": "成本结构对比"},
        ],
        revision_guidance="",
    )

    assert [lane["lane_kind"] for lane in lanes] == ["narrative", "chart", "chart"]
    chart_inputs = [lane["input"] for lane in lanes if lane["lane_kind"] == "chart"]
    assert [lane_input["chart_kind"] for lane_input in chart_inputs] == ["line_chart", "bar_chart"]
    assert [lane_input["container_id"] for lane_input in chart_inputs] == ["p06_chart_1", "p06_chart_2"]


def test_generate_with_lanes_preserves_multiple_chart_artifacts(monkeypatch) -> None:
    orchestrator = PageOrchestrator()
    created_lanes: list[SimpleNamespace] = []

    async def fake_create_lane(session, page_db_id, project_id, lane_id, kind, input_data=None):
        lane = SimpleNamespace(
            id=f"db-{len(created_lanes) + 1}",
            lane_id=lane_id,
            kind=kind,
            input_data=input_data or {},
            retries=0,
        )
        created_lanes.append(lane)
        return lane

    async def fake_run_lane(session, lane, model=None):
        input_data = lane.input_data or {}
        if lane.kind == "narrative":
            return {"content": "<div>narrative</div>", "asset": None, "metadata": {"kind": "narrative"}}

        chart_kind = input_data.get("chart_kind")
        container_id = input_data.get("container_id")
        html = (
            f'<div class="deck-visual-wrapper deck-chart-wrapper">'
            f'<div id="{container_id}"></div>'
            f'<script>const kind = "{chart_kind}";</script>'
            f'</div>'
        )
        return {
            "content": html,
            "asset": html,
            "metadata": {
                "kind": "chart",
                "chart_kind": chart_kind,
                "container_id": container_id,
            },
        }

    async def fake_send(_event: dict) -> None:
        return None

    async def fake_compose(*args, **kwargs):
        return '<section data-page-id="p06" class="deck-page"></section>'

    monkeypatch.setattr(
        "app.services.webdeck_runtime.page_orchestrator.deck_state_store.create_lane",
        fake_create_lane,
    )
    monkeypatch.setattr(orchestrator.lane_runner, "run_lane", fake_run_lane)
    monkeypatch.setattr(orchestrator, "_compose_page_html", fake_compose)

    page = SimpleNamespace(
        id="page-db-1",
        page_id="p06",
        page_kind="chart_analysis",
        page_spec={
            "asset_requirements": [
                {"type": "chart", "kind": "line_chart", "description": "投资回报曲线"},
                {"type": "chart", "kind": "bar_chart", "description": "成本结构对比"},
            ],
        },
    )

    bundle = asyncio.run(
        orchestrator._generate_with_lanes(
            session=object(),
            page=page,
            project_id="proj-1",
            global_theme={"accent_color": "#3b82f6", "bg_color": "#0f172a", "text_color": "#f1f5f9"},
            send_fn=fake_send,
            model=None,
            revision_guidance="",
        )
    )

    assert bundle.html == '<section data-page-id="p06" class="deck-page" style="background:#0f172a; color:#f1f5f9;"></section>'
    assert len(bundle.artifacts) == 2
    assert [artifact.metadata["chart_kind"] for artifact in bundle.artifacts] == ["line_chart", "bar_chart"]
    assert [artifact.metadata["container_id"] for artifact in bundle.artifacts] == ["p06_chart_1", "p06_chart_2"]


def test_apply_theme_shell_overrides_outer_section_theme() -> None:
    orchestrator = PageOrchestrator()

    themed = orchestrator._apply_theme_shell(
        '<section data-page-id="p01" class="deck-page" style="background:#ffffff;color:#111111;"><div>hello</div></section>',
        {"bg_color": "#0f172a", "text_color": "#f1f5f9"},
    )

    assert "background:#0f172a; color:#f1f5f9;" in themed
    assert "background:#ffffff" in themed