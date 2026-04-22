"""DeckSpec HTML preview rendering utilities."""

from __future__ import annotations

from html import escape
from typing import Any

from app.schemas.deck_spec import DeckSpec, SlideNodeSpec, SlideSpec
from app.services.theme_manager import build_reveal_html

PX_PER_INCH = 96
PT_PER_INCH = 72
EMU_PER_INCH = 914400


def render_deck_to_html_preview(deck_spec: DeckSpec) -> tuple[str, dict[str, Any]]:
    sections = render_slide_sections_from_deckspec(deck_spec)
    html = build_reveal_html(sections, deck_spec.theme.theme_id, deck_spec.title or "演示文稿")
    return html, {
        "slideCount": len(deck_spec.slides),
        "nodeCount": sum(_count_nodes(slide.nodes) for slide in deck_spec.slides),
        "artifactMode": deck_spec.artifact_mode,
    }


def render_slide_sections_from_deckspec(deck_spec: DeckSpec) -> list[str]:
    width = _unit_to_px(deck_spec.slide_size.width, deck_spec.slide_size.unit)
    height = _unit_to_px(deck_spec.slide_size.height, deck_spec.slide_size.unit)
    return [_render_slide_section(deck_spec, slide, width, height) for slide in deck_spec.slides]


def _render_slide_section(deck_spec: DeckSpec, slide: SlideSpec, width: float, height: float) -> str:
    content = "".join(_render_node(deck_spec, node) for node in slide.nodes)
    return (
        f'<section data-deckspec-slide="{escape(slide.slide_id)}" '
        f'data-layout-id="{escape(slide.layout_id)}" '
        'data-deckspec-preview="true">'
        f'<div class="deckspec-canvas" style="position:relative;width:{width:.2f}px;height:{height:.2f}px;overflow:hidden;">'
        f"{content}</div></section>"
    )


def _render_node(deck_spec: DeckSpec, node: SlideNodeSpec) -> str:
    if node.kind == "group":
        return "".join(_render_node(deck_spec, child) for child in node.children)

    bbox_style = _bbox_style(deck_spec, node)
    role = escape(node.role)
    node_id = escape(node.node_id)

    if node.kind == "text":
        style = _join_styles(
            bbox_style,
            {
                "overflow": "hidden",
                "white-space": "pre-wrap",
                "font-size": f"{_font_size(node, 16):.2f}px",
                "font-weight": "700" if node.style.get("bold") else "400",
                "font-style": "italic" if node.style.get("italic") else "normal",
                "line-height": node.style.get("lineHeight", 1.35),
                "color": _color(node.style.get("color"), deck_spec.theme.palette.foreground),
                "text-align": node.style.get("align", "left"),
                "background": _optional_color(node.style.get("fillColor")),
                "border": _line_css(node.style.get("lineColor"), node.style.get("lineWidth")),
                "border-radius": "14px" if "card" in node.role or "highlight" in node.role else None,
                "padding": _padding_for_text(node),
            },
        )
        return (
            f'<div data-deckspec-role="{role}" data-node-id="{node_id}" style="{style}">'
            f"{_render_text_content(node)}</div>"
        )

    if node.kind == "image":
        image_src = _resolve_image_source(node)
        if not image_src:
            return ""
        style = _join_styles(
            bbox_style,
            {
                "display": "block",
                "object-fit": node.style.get("objectFit", "contain"),
                "border-radius": "12px" if node.style.get("borderRadius") else None,
            },
        )
        alt_text = escape(str(node.content.get("alt") or node.role or node.node_id))
        return f'<img data-deckspec-role="{role}" data-node-id="{node_id}" src="{escape(image_src)}" alt="{alt_text}" style="{style}" />'

    if node.kind == "shape":
        border_radius = "18px" if str(node.content.get("shapeType") or "").lower().startswith("rounded") else "0"
        style = _join_styles(
            bbox_style,
            {
                "background": _color(node.style.get("fillColor"), deck_spec.theme.palette.accent),
                "border": _line_css(node.style.get("lineColor"), node.style.get("lineWidth"), fallback="#00000000"),
                "border-radius": border_radius,
                "opacity": _opacity(node.style.get("transparency")),
            },
        )
        return f'<div data-deckspec-role="{role}" data-node-id="{node_id}" style="{style}"></div>'

    if node.kind == "table":
        return _render_table_node(deck_spec, node, bbox_style)

    if node.kind == "chart":
        return _render_chart_node(deck_spec, node, bbox_style)

    return ""


def _render_table_node(deck_spec: DeckSpec, node: SlideNodeSpec, bbox_style: dict[str, str | float | None]) -> str:
    rows = node.content.get("rows") or []
    if not rows:
        return ""

    header_rows = int(node.content.get("headerRows") or 0)
    table_rows: list[str] = []
    for row_index, row in enumerate(rows):
        cells = []
        is_header = row_index < header_rows
        for cell in row:
            tag = "th" if is_header else "td"
            cell_style = _join_styles(
                {
                    "border": _line_css(node.style.get("lineColor"), 1, fallback="#CBD5E1"),
                    "padding": "8px 10px",
                    "font-size": f"{_font_size(node, 12):.2f}px",
                    "text-align": "left",
                    "vertical-align": "top",
                    "background": _color(
                        node.style.get("headerFillColor") if is_header else node.style.get("fillColor"),
                        deck_spec.theme.palette.background,
                    ),
                    "color": _color(
                        node.style.get("headerColor") if is_header else node.style.get("color"),
                        deck_spec.theme.palette.foreground,
                    ),
                    "font-weight": "700" if is_header else "400",
                },
            )
            cells.append(f'<{tag} style="{cell_style}">{escape(str(cell))}</{tag}>')
        table_rows.append(f"<tr>{''.join(cells)}</tr>")

    wrapper_style = _join_styles(
        bbox_style,
        {
            "overflow": "hidden",
            "display": "flex",
            "align-items": "stretch",
        },
    )
    table_style = "width:100%;height:100%;border-collapse:collapse;table-layout:fixed;"
    return (
        f'<div data-deckspec-role="{escape(node.role)}" data-node-id="{escape(node.node_id)}" style="{wrapper_style}">'
        f'<table style="{table_style}">{"".join(table_rows)}</table></div>'
    )


def _render_chart_node(deck_spec: DeckSpec, node: SlideNodeSpec, bbox_style: dict[str, str | float | None]) -> str:
    categories = [str(item) for item in (node.content.get("categories") or [])]
    series = node.content.get("series") or []
    values = list(series[0].get("values") or []) if series else []
    if not categories or not values:
        return ""

    numeric_values = [float(value or 0) for value in values]
    max_value = max([abs(value) for value in numeric_values] or [1.0])
    suffix = str(node.content.get("valueSuffix") or "")
    bars = []
    for index, label in enumerate(categories):
        value = numeric_values[index] if index < len(numeric_values) else 0.0
        ratio = 0 if max_value == 0 else max(min(abs(value) / max_value, 1), 0)
        bars.append(
            "".join(
                [
                    '<div style="display:grid;grid-template-columns:minmax(72px, 160px) 1fr auto;gap:10px;align-items:center;">',
                    f'<div style="font-size:{_font_size(node, 12):.2f}px;color:{_color(node.style.get("color"), deck_spec.theme.palette.foreground)};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{escape(label)}</div>',
                    '<div style="height:12px;background:rgba(148,163,184,0.18);border-radius:999px;overflow:hidden;">',
                    f'<div style="width:{ratio * 100:.2f}%;height:100%;background:{_color(node.style.get("fillColor"), deck_spec.theme.palette.accent)};"></div>',
                    '</div>',
                    f'<div style="font-size:{_font_size(node, 12):.2f}px;font-weight:600;color:{_color(node.style.get("color"), deck_spec.theme.palette.foreground)};">{escape(_format_chart_value(value, suffix))}</div>',
                    '</div>',
                ]
            )
        )

    wrapper_style = _join_styles(
        bbox_style,
        {
            "display": "flex",
            "flex-direction": "column",
            "justify-content": "center",
            "gap": "12px",
            "padding": "14px 16px",
            "border": _line_css(node.style.get("lineColor"), 1, fallback="#CBD5E1"),
            "border-radius": "16px",
            "background": _optional_color(node.style.get("fillColor")) or "transparent",
            "overflow": "hidden",
        },
    )
    return (
        f'<div data-deckspec-role="{escape(node.role)}" data-node-id="{escape(node.node_id)}" style="{wrapper_style}">'
        f"{''.join(bars)}</div>"
    )


def _render_text_content(node: SlideNodeSpec) -> str:
    runs = node.content.get("runs") or []
    if runs:
        parts: list[str] = []
        for run in runs:
            text = escape(str(run.get("text") or ""))
            if not text:
                continue
            if run.get("bullet"):
                text = f"&bull; {text}"
            run_style = _join_styles(
                {
                    "font-weight": "700" if run.get("bold") else None,
                    "font-style": "italic" if run.get("italic") else None,
                    "color": _optional_color(run.get("color")),
                },
            )
            parts.append(f'<span style="{run_style}">{text}</span>')
            if run.get("breakLine"):
                parts.append("<br />")
        if parts:
            return "".join(parts)
    text = str(node.content.get("text") or "")
    if not text:
        return ""
    return "<br />".join(escape(line) for line in text.splitlines())


def _resolve_image_source(node: SlideNodeSpec) -> str | None:
    image_source = node.content.get("data") or node.content.get("src") or node.content.get("path")
    if not image_source:
        return None
    return str(image_source)


def _bbox_style(deck_spec: DeckSpec, node: SlideNodeSpec) -> dict[str, str | float | None]:
    unit = deck_spec.slide_size.unit
    return {
        "position": "absolute",
        "left": f"{_unit_to_px(node.bbox.x, unit):.2f}px",
        "top": f"{_unit_to_px(node.bbox.y, unit):.2f}px",
        "width": f"{_unit_to_px(node.bbox.w, unit):.2f}px",
        "height": f"{_unit_to_px(node.bbox.h, unit):.2f}px",
    }


def _unit_to_px(value: float | int, unit: str) -> float:
    numeric = float(value)
    if unit == "pt":
        return numeric / PT_PER_INCH * PX_PER_INCH
    if unit == "emu":
        return numeric / EMU_PER_INCH * PX_PER_INCH
    return numeric


def _count_nodes(nodes: list[SlideNodeSpec]) -> int:
    total = 0
    for node in nodes:
        total += 1
        total += _count_nodes(node.children)
    return total


def _padding_for_text(node: SlideNodeSpec) -> str:
    if any(token in node.role for token in {"card", "highlight", "callout"}):
        return "10px 12px"
    return "0"


def _font_size(node: SlideNodeSpec, default: float) -> float:
    value = node.style.get("fontSize")
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _color(value: str | None, fallback: str) -> str:
    return _optional_color(value) or fallback


def _optional_color(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.startswith("#") or raw.startswith("rgb") or raw.startswith("hsl") or raw.lower() == "transparent":
        return raw
    return f"#{raw}"


def _line_css(color: Any, width: Any, fallback: str | None = None) -> str | None:
    resolved = _optional_color(color) or fallback
    if not resolved:
        return None
    try:
        numeric_width = float(width) if width is not None else 1.0
    except (TypeError, ValueError):
        numeric_width = 1.0
    return f"{numeric_width:.1f}px solid {resolved}"


def _opacity(transparency: Any) -> str:
    try:
        transparency_value = float(transparency or 0)
    except (TypeError, ValueError):
        transparency_value = 0.0
    return f"{max(0.0, min(1.0, 1.0 - transparency_value / 100.0)):.3f}"


def _join_styles(*parts: dict[str, Any]) -> str:
    items: list[str] = []
    for part in parts:
        for key, value in part.items():
            if value is None or value == "":
                continue
            items.append(f"{key}:{value}")
    return ";".join(items)


def _format_chart_value(value: float, suffix: str) -> str:
    if value.is_integer():
        return f"{int(value)}{suffix}"
    return f"{value:.2f}{suffix}".rstrip("0").rstrip(".")