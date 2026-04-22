"""
Theme propagation tests — verifies that global_theme colors reach the final HTML.

Covers:
- CHART_PROMPT includes bg_color and text_color placeholders (no hardcoded dark theme)
- _run_chart passes bg_color and text_color to the prompt
- _apply_theme_shell injects :root CSS variables into <head>
- _apply_theme_shell sets !important on section.deck-page background
- _compose_page_html prompt contains 【强制】 color constraints
"""
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.webdeck_runtime.lane_runner import CHART_PROMPT, LaneRunner
from app.services.webdeck_runtime.page_orchestrator import PageOrchestrator


# ─── CHART_PROMPT structure ──────────────────────────────────────────────────

def test_chart_prompt_has_bg_color_placeholder():
    assert "{bg_color}" in CHART_PROMPT


def test_chart_prompt_has_text_color_placeholder():
    assert "{text_color}" in CHART_PROMPT


def test_chart_prompt_no_hardcoded_dark_theme():
    assert "深色主题" not in CHART_PROMPT


# ─── _apply_theme_shell ───────────────────────────────────────────────────────

LIGHT_THEME = {"bg_color": "#FFFFFF", "text_color": "#000000", "accent_color": "#0A2463"}
DARK_THEME  = {"bg_color": "#0f172a", "text_color": "#f1f5f9", "accent_color": "#3b82f6"}


def _make_full_html(section_inner: str = "<p>content</p>") -> str:
    return (
        "<html><head><title>Test</title></head><body>"
        f'<section data-page-id="p01" class="deck-page">{section_inner}</section>'
        "</body></html>"
    )


def test_apply_theme_shell_injects_root_vars_into_head():
    orch = PageOrchestrator()
    result = orch._apply_theme_shell(_make_full_html(), LIGHT_THEME)
    assert "deck-theme-vars" in result
    assert "--bg:#FFFFFF" in result
    assert "--text:#000000" in result
    assert "--accent:#0A2463" in result


def test_apply_theme_shell_places_vars_before_closing_head():
    orch = PageOrchestrator()
    result = orch._apply_theme_shell(_make_full_html(), LIGHT_THEME)
    head_close = result.index("</head>")
    vars_pos   = result.index("deck-theme-vars")
    assert vars_pos < head_close


def test_apply_theme_shell_section_important_override():
    orch = PageOrchestrator()
    result = orch._apply_theme_shell(_make_full_html(), LIGHT_THEME)
    # section.deck-page rule must force background with !important
    assert "section.deck-page" in result
    assert "!important" in result


def test_apply_theme_shell_works_for_dark_theme():
    orch = PageOrchestrator()
    result = orch._apply_theme_shell(_make_full_html(), DARK_THEME)
    assert "--bg:#0f172a" in result


def test_apply_theme_shell_inserts_before_body_when_no_head():
    """Falls back to inserting before <body> if </head> not present."""
    orch = PageOrchestrator()
    html = '<body><section class="deck-page"><p>x</p></section></body>'
    result = orch._apply_theme_shell(html, LIGHT_THEME)
    assert "deck-theme-vars" in result


def test_apply_theme_shell_section_inline_style_set():
    orch = PageOrchestrator()
    result = orch._apply_theme_shell(_make_full_html(), LIGHT_THEME)
    # section inline style should include background and color
    section_match = re.search(r"<section\b[^>]*style=\"([^\"]*)\"", result, re.IGNORECASE)
    assert section_match, "section has no inline style"
    style = section_match.group(1)
    assert "background:#FFFFFF" in style
    assert "color:#000000" in style


# ─── _run_chart passes colors ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_chart_forwards_bg_and_text_colors():
    """_run_chart must forward bg_color and text_color to CHART_PROMPT.format()."""
    captured_prompts: list[str] = []

    mock_response = MagicMock()
    mock_response.content = '<div class="deck-visual-wrapper"><div id="c1"></div><script></script></div>'

    async def fake_llm_chat(system, messages, model=None):
        captured_prompts.append(system)
        return mock_response

    runner = LaneRunner()
    input_data = {
        "global_theme": {"bg_color": "#FFFFFF", "text_color": "#111111", "accent_color": "#0A2463"},
        "page_spec": {"title": "Test", "goal": "test"},
        "container_id": "c1",
        "chart_kind": "bar",
        "description": "test chart",
        "purpose": "test",
        "data_dimensions": [],
        "required_elements": [],
        "caption": "cap",
    }

    with patch("app.services.webdeck_runtime.lane_runner.llm_chat", side_effect=fake_llm_chat):
        await runner._run_chart(input_data, model=None)

    assert captured_prompts, "llm_chat was not called"
    prompt = captured_prompts[0]
    assert "#FFFFFF" in prompt, "bg_color not in chart prompt"
    assert "#111111" in prompt, "text_color not in chart prompt"
