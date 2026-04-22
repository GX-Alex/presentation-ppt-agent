import asyncio

from app.services.webdeck_runtime.lane_runner import LaneRunner


def _page_spec() -> dict:
    return {
        "page_kind": "chart_analysis",
        "narrative_contract": {
            "core_message": "预计12个月回收投资，3年累计ROI达320%，成本结构从人力密集型转向技术驱动型",
        },
    }


def test_chart_analysis_narrative_uses_contract_roi() -> None:
    async def scenario() -> None:
        runner = LaneRunner()
        result = await runner._run_narrative({"page_spec": _page_spec()}, model=None)

        assert "320%" in result["content"]
        assert "12 个月" in result["content"] or "12个月" in result["content"]
        assert "3 年累计 ROI = 3 年累计回报 / 初始投入 × 100%" in result["content"]

    asyncio.run(scenario())


def test_chart_analysis_line_combo_chart_renders_roi_curve() -> None:
    async def scenario() -> None:
        runner = LaneRunner()
        result = await runner._run_chart(
            {
                "page_spec": _page_spec(),
                "global_theme": {"accent_color": "#3b82f6"},
                "chart_kind": "line_combo_chart",
                "container_id": "p05_chart_1",
                "caption": "AI客服系统3年ROI预测曲线",
            },
            model=None,
        )

        assert "AI客服系统3年ROI预测曲线" in result["content"]
        assert "累计回报" in result["content"]
        assert "12月回收" in result["content"]
        assert result["metadata"]["chart_kind"] == "line_combo_chart"

    asyncio.run(scenario())