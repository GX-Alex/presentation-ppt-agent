"""HTML-to-DeckSpec semantic adapter used by canonical deck generation."""

from __future__ import annotations

from dataclasses import dataclass, field
import html as html_lib
from html.parser import HTMLParser
import re
from typing import Any, Iterable

from app.schemas.deck_spec import DeckSpec
from app.services.theme_manager import get_theme

DEFAULT_SLIDE_WIDTH = 1280
DEFAULT_SLIDE_HEIGHT = 720
SLIDE_MARGIN_X = 92
SLIDE_TITLE_Y = 64
SLIDE_CONTENT_Y = 188
SLIDE_FOOTER_GAP = 68
CONTENT_WIDTH = DEFAULT_SLIDE_WIDTH - (SLIDE_MARGIN_X * 2)

_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}
_TEXT_BLOCK_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "pre", "code"}
_CARD_CLASS_HINTS = {"cards", "card", "grid", "features", "items", "metrics", "highlights"}
_COLUMN_CLASS_HINTS = {"columns", "column", "split", "comparison", "compare", "two-column", "two_columns", "dual"}
_CHART_SLIDE_TYPES = {"chart", "stats"}
_TABLE_SLIDE_TYPES = {"table"}
_CARD_SLIDE_TYPES = {"icon-grid", "summary"}
_COLUMN_SLIDE_TYPES = {"two-column", "comparison", "image-text"}
_EMOJI_RE = re.compile(r"^[\W_]*(?P<emoji>[\U0001F300-\U0001FAFF\u2600-\u27BF])")
_METRIC_RE = re.compile(
    r"^(?P<label>.+?)(?:[:：|\-]\s*|\s+)(?P<value>[-+]?\d[\d,.]*)(?P<suffix>%|％|万|亿|k|K|m|M|x|倍)?$"
)


@dataclass(slots=True)
class _HtmlElement:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_HtmlElement"] = field(default_factory=list)
    text_chunks: list[str] = field(default_factory=list)

    def walk(self) -> Iterable["_HtmlElement"]:
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(slots=True)
class _CardContent:
    title: str
    body: str
    icon: str | None = None
    image_src: str | None = None
    image_alt: str | None = None


class _HtmlTreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlElement(tag="document")
        self._stack: list[_HtmlElement] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlElement(
            tag=tag.lower(),
            attrs={key.lower(): (value or "") for key, value in attrs},
        )
        self._stack[-1].children.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlElement(
            tag=tag.lower(),
            attrs={key.lower(): (value or "") for key, value in attrs},
        )
        self._stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == lowered:
                del self._stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].text_chunks.append(data)


class _NodeFactory:
    def __init__(self, slide_index: int) -> None:
        self.slide_index = slide_index
        self._counter = 0

    def next_id(self, role: str) -> str:
        self._counter += 1
        safe_role = re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-") or "node"
        return f"slide-{self.slide_index + 1}-{safe_role}-{self._counter}"


def build_deckspec_from_slides(
    presentation_id: str,
    title: str,
    theme_id: str,
    slides_data: list[dict[str, Any]],
    artifact_mode: str = "dual_render",
) -> DeckSpec:
    theme = get_theme(theme_id)
    theme_css = theme["css"]
    slide_specs = [_build_slide_spec(slide_data, index, theme_css) for index, slide_data in enumerate(slides_data)]

    deck_payload = {
        "deck_id": presentation_id,
        "artifact_mode": artifact_mode,
        "title": title,
        "theme": {
            "theme_id": theme_id,
            "palette": {
                "background": theme_css.get("backgroundColor", "#FFFFFF"),
                "foreground": theme_css.get("color", "#1E293B"),
                "accent": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                "muted": theme_css.get("linkColor", "#64748B"),
            },
            "typography": {
                "heading_font": _primary_font(theme_css.get("headingFontFamily")) or "Aptos Display",
                "body_font": _primary_font(theme_css.get("fontFamily")) or "Aptos",
                "mono_font": _primary_font(theme_css.get("codeFontFamily")) or "Cascadia Code",
            },
            "spacing": {
                "base_unit": 8,
                "section_gap": 28,
                "item_gap": 14,
            },
            "custom": {
                "theme_name": theme.get("name", theme_id),
            },
        },
        "slide_size": {
            "width": DEFAULT_SLIDE_WIDTH,
            "height": DEFAULT_SLIDE_HEIGHT,
            "unit": "px",
        },
        "slides": slide_specs,
        "metadata": {
            "source": "html-semantic-adapter",
            "tags": [theme_id, "deckspec", "semantic-layout"],
            "semantic_layouts": [slide_spec["layout_id"] for slide_spec in slide_specs],
        },
    }
    return DeckSpec.model_validate(deck_payload)


def _primary_font(font_family: str | None) -> str | None:
    if not font_family:
        return None
    first = font_family.split(",")[0].strip().strip("'\"")
    return first or None


def _build_slide_spec(slide_data: dict[str, Any], slide_index: int, theme_css: dict[str, Any]) -> dict[str, Any]:
    tree = _parse_html_tree(slide_data.get("html", ""))
    section = _section_root(tree)
    title_text = _extract_slide_title(section) or f"Slide {slide_index + 1}"
    subtitle_text = _extract_slide_subtitle(section, title_text)
    factory = _NodeFactory(slide_index)
    nodes, layout_kind = _build_semantic_nodes(
        section=section,
        slide_data=slide_data,
        title_text=title_text,
        subtitle_text=subtitle_text,
        theme_css=theme_css,
        factory=factory,
    )

    return {
        "slide_id": slide_data.get("id") or f"slide-{slide_index + 1}",
        "title": title_text,
        "page_type": slide_data.get("type", layout_kind),
        "layout_id": f"semantic.{layout_kind}",
        "notes": slide_data.get("speaker_notes", ""),
        "nodes": nodes,
        "metadata": {
            "source_html": slide_data.get("html", ""),
            "index": slide_data.get("index", slide_index),
            "semantic_layout": layout_kind,
            "subtitle": subtitle_text,
        },
    }


def _build_semantic_nodes(
    *,
    section: _HtmlElement,
    slide_data: dict[str, Any],
    title_text: str,
    subtitle_text: str | None,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> tuple[list[dict[str, Any]], str]:
    slide_type = str(slide_data.get("type", "content") or "content").lower()
    table_element = _find_first(section, {"table"})
    metric_points = _extract_metric_points(section, title_text)
    two_column_container = _find_two_column_container(section)
    cards = _extract_cards(section)

    if table_element is not None or slide_type in _TABLE_SLIDE_TYPES:
        rows = _extract_table_rows(table_element) if table_element is not None else []
        if rows:
            return _build_table_layout(title_text, subtitle_text, rows, section, theme_css, factory), "table"

    if (slide_type in _CHART_SLIDE_TYPES or _has_chart_markup(section)) and len(metric_points) >= 2:
        return _build_chart_layout(title_text, subtitle_text, metric_points, section, theme_css, factory), "chart"

    if (slide_type in _COLUMN_SLIDE_TYPES or two_column_container is not None) and two_column_container is not None:
        return _build_two_column_layout(title_text, subtitle_text, two_column_container, theme_css, factory), "two-column"

    if (slide_type in _CARD_SLIDE_TYPES or len(cards) >= 3) and len(cards) >= 3:
        return _build_card_layout(title_text, subtitle_text, cards, theme_css, factory), "card-group"

    if len(metric_points) >= 3 and slide_type in {"content", "summary"}:
        return _build_chart_layout(title_text, subtitle_text, metric_points, section, theme_css, factory), "chart"

    return _build_generic_layout(title_text, subtitle_text, section, theme_css, factory), "flow"


def _build_generic_layout(
    title_text: str,
    subtitle_text: str | None,
    section: _HtmlElement,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> list[dict[str, Any]]:
    nodes, content_top = _build_heading_nodes(title_text, subtitle_text, theme_css, factory)
    bbox = {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": DEFAULT_SLIDE_HEIGHT - content_top - SLIDE_FOOTER_GAP}
    entries = _collect_flow_entries(section, title_text, subtitle_text)
    nodes.extend(_build_flow_nodes(entries, bbox, theme_css, factory, "flow"))
    return nodes


def _build_two_column_layout(
    title_text: str,
    subtitle_text: str | None,
    container: _HtmlElement,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> list[dict[str, Any]]:
    nodes, content_top = _build_heading_nodes(title_text, subtitle_text, theme_css, factory)
    columns = _content_children(container)[:2]
    gap = 28
    col_width = (CONTENT_WIDTH - gap) / 2
    group_height = DEFAULT_SLIDE_HEIGHT - content_top - SLIDE_FOOTER_GAP
    left_bbox = {"x": SLIDE_MARGIN_X, "y": content_top, "w": col_width, "h": group_height}
    right_bbox = {"x": SLIDE_MARGIN_X + col_width + gap, "y": content_top, "w": col_width, "h": group_height}
    group_bbox = {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": group_height}

    left_group = {
        "node_id": factory.next_id("column-left"),
        "kind": "group",
        "role": "column.left",
        "bbox": left_bbox,
        "content": {"layout": "stack"},
        "style": {},
        "children": _build_region_nodes(columns[0], left_bbox, theme_css, factory, "left_column"),
    }
    right_group = {
        "node_id": factory.next_id("column-right"),
        "kind": "group",
        "role": "column.right",
        "bbox": right_bbox,
        "content": {"layout": "stack"},
        "style": {},
        "children": _build_region_nodes(columns[1], right_bbox, theme_css, factory, "right_column"),
    }
    divider = {
        "node_id": factory.next_id("column-divider"),
        "kind": "shape",
        "role": "column.divider",
        "bbox": {
            "x": SLIDE_MARGIN_X + col_width + (gap / 2) - 1,
            "y": content_top + 8,
            "w": 2,
            "h": group_height - 16,
        },
        "content": {"shapeType": "rect"},
        "style": {
            "fillColor": theme_css.get("linkColor", "#CBD5E1"),
            "lineColor": theme_css.get("linkColor", "#CBD5E1"),
            "transparency": 38,
        },
        "children": [],
    }
    nodes.append(
        {
            "node_id": factory.next_id("two-column-layout"),
            "kind": "group",
            "role": "layout.two-column",
            "bbox": group_bbox,
            "content": {"columns": 2},
            "style": {},
            "children": [left_group, divider, right_group],
        }
    )
    return nodes


def _build_card_layout(
    title_text: str,
    subtitle_text: str | None,
    cards: list[_CardContent],
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> list[dict[str, Any]]:
    nodes, content_top = _build_heading_nodes(title_text, subtitle_text, theme_css, factory)
    count = len(cards)
    columns = 2 if count <= 4 else 3
    rows = (count + columns - 1) // columns
    gap = 24
    card_width = (CONTENT_WIDTH - gap * (columns - 1)) / columns
    available_height = DEFAULT_SLIDE_HEIGHT - content_top - SLIDE_FOOTER_GAP
    card_height = min(200, (available_height - gap * max(rows - 1, 0)) / max(rows, 1))
    card_groups: list[dict[str, Any]] = []

    for index, card in enumerate(cards):
        row = index // columns
        col = index % columns
        card_x = SLIDE_MARGIN_X + col * (card_width + gap)
        card_y = content_top + row * (card_height + gap)
        card_bbox = {"x": card_x, "y": card_y, "w": card_width, "h": card_height}
        inner_x = card_x + 20
        inner_w = card_width - 40
        cursor_y = card_y + 18

        children: list[dict[str, Any]] = [
            {
                "node_id": factory.next_id("card-bg"),
                "kind": "shape",
                "role": "card.background",
                "bbox": card_bbox,
                "content": {"shapeType": "roundedRect"},
                "style": {
                    "fillColor": theme_css.get("cardBackgroundColor", theme_css.get("backgroundColor", "#FFFFFF")),
                    "lineColor": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                    "lineWidth": 1,
                    "transparency": 8,
                },
                "children": [],
            }
        ]

        if card.icon:
            children.append(
                {
                    "node_id": factory.next_id("card-icon"),
                    "kind": "text",
                    "role": "card.icon",
                    "bbox": {"x": inner_x, "y": cursor_y, "w": 48, "h": 28},
                    "content": {"text": card.icon},
                    "style": {
                        "fontSize": 22,
                        "color": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                    },
                    "children": [],
                }
            )
            cursor_y += 30

        if card.image_src:
            children.append(
                {
                    "node_id": factory.next_id("card-image"),
                    "kind": "image",
                    "role": "card.image",
                    "bbox": {"x": inner_x, "y": cursor_y, "w": inner_w, "h": 72},
                    "content": {"src": card.image_src, "alt": card.image_alt or card.title},
                    "style": {},
                    "children": [],
                }
            )
            cursor_y += 82

        children.extend(
            [
                {
                    "node_id": factory.next_id("card-title"),
                    "kind": "text",
                    "role": "card.title",
                    "bbox": {"x": inner_x, "y": cursor_y, "w": inner_w, "h": 34},
                    "content": {"text": card.title},
                    "style": {
                        "fontSize": 18,
                        "color": theme_css.get("headingColor", "#2563EB"),
                        "bold": True,
                        "fit": "shrink",
                    },
                    "children": [],
                },
                {
                    "node_id": factory.next_id("card-body"),
                    "kind": "text",
                    "role": "card.body",
                    "bbox": {
                        "x": inner_x,
                        "y": cursor_y + 40,
                        "w": inner_w,
                        "h": max(52, card_height - (cursor_y - card_y) - 58),
                    },
                    "content": {"text": card.body},
                    "style": {
                        "fontSize": 14,
                        "color": theme_css.get("color", "#1E293B"),
                        "fit": "shrink",
                    },
                    "children": [],
                },
            ]
        )
        card_groups.append(
            {
                "node_id": factory.next_id("card-group"),
                "kind": "group",
                "role": "card",
                "bbox": card_bbox,
                "content": {"index": index},
                "style": {},
                "children": children,
            }
        )

    nodes.append(
        {
            "node_id": factory.next_id("card-layout"),
            "kind": "group",
            "role": "layout.card-group",
            "bbox": {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": available_height},
            "content": {"columns": columns, "rows": rows},
            "style": {},
            "children": card_groups,
        }
    )
    return nodes


def _build_table_layout(
    title_text: str,
    subtitle_text: str | None,
    table_rows: list[list[str]],
    section: _HtmlElement,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> list[dict[str, Any]]:
    nodes, content_top = _build_heading_nodes(title_text, subtitle_text, theme_css, factory)
    body_texts = _collect_body_texts(section, {title_text, subtitle_text or ""})
    if body_texts:
        nodes.append(
            {
                "node_id": factory.next_id("table-summary"),
                "kind": "text",
                "role": "table.summary",
                "bbox": {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": 44},
                "content": {"text": body_texts[0]},
                "style": {
                    "fontSize": 15,
                    "color": theme_css.get("color", "#1E293B"),
                    "fit": "shrink",
                },
                "children": [],
            }
        )
        content_top += 56

    col_count = max(len(row) for row in table_rows)
    nodes.append(
        {
            "node_id": factory.next_id("table"),
            "kind": "table",
            "role": "data.table",
            "bbox": {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": DEFAULT_SLIDE_HEIGHT - content_top - 118},
            "content": {
                "rows": table_rows,
                "headerRows": 1,
                "colWidths": [CONTENT_WIDTH / col_count for _ in range(col_count)],
            },
            "style": {
                "fontSize": 13,
                "headerFillColor": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                "headerColor": theme_css.get("backgroundColor", "#FFFFFF"),
                "fillColor": theme_css.get("cardBackgroundColor", theme_css.get("backgroundColor", "#FFFFFF")),
                "lineColor": theme_css.get("linkColor", "#94A3B8"),
                "color": theme_css.get("color", "#1E293B"),
            },
            "children": [],
        }
    )
    return nodes


def _build_chart_layout(
    title_text: str,
    subtitle_text: str | None,
    metric_points: list[dict[str, Any]],
    section: _HtmlElement,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> list[dict[str, Any]]:
    nodes, content_top = _build_heading_nodes(title_text, subtitle_text, theme_css, factory)
    body_texts = _collect_body_texts(section, {title_text, subtitle_text or ""})
    insight_text = next((text for text in body_texts if not _METRIC_RE.match(text)), None)
    chart_bbox = {"x": SLIDE_MARGIN_X, "y": content_top, "w": 712, "h": 360}
    top_metric = max(metric_points, key=lambda item: item["value"])
    callout_x = chart_bbox["x"] + chart_bbox["w"] + 28
    callout_children = [
        {
            "node_id": factory.next_id("chart-highlight-bg"),
            "kind": "shape",
            "role": "chart.highlight.bg",
            "bbox": {"x": callout_x, "y": content_top, "w": 356, "h": 120},
            "content": {"shapeType": "roundedRect"},
            "style": {
                "fillColor": theme_css.get("cardBackgroundColor", theme_css.get("backgroundColor", "#FFFFFF")),
                "lineColor": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                "lineWidth": 1,
                "transparency": 10,
            },
            "children": [],
        },
        {
            "node_id": factory.next_id("chart-highlight-value"),
            "kind": "text",
            "role": "chart.highlight.value",
            "bbox": {"x": callout_x + 20, "y": content_top + 18, "w": 316, "h": 38},
            "content": {"text": _format_metric_value(top_metric["value"], top_metric.get("suffix"))},
            "style": {
                "fontSize": 28,
                "color": theme_css.get("headingColor", "#2563EB"),
                "bold": True,
            },
            "children": [],
        },
        {
            "node_id": factory.next_id("chart-highlight-label"),
            "kind": "text",
            "role": "chart.highlight.label",
            "bbox": {"x": callout_x + 20, "y": content_top + 62, "w": 316, "h": 42},
            "content": {"text": top_metric["label"]},
            "style": {
                "fontSize": 15,
                "color": theme_css.get("color", "#1E293B"),
                "fit": "shrink",
            },
            "children": [],
        },
    ]
    if insight_text:
        callout_children.append(
            {
                "node_id": factory.next_id("chart-insight"),
                "kind": "text",
                "role": "chart.insight",
                "bbox": {"x": callout_x, "y": content_top + 144, "w": 356, "h": 184},
                "content": {"text": insight_text},
                "style": {
                    "fontSize": 15,
                    "color": theme_css.get("color", "#1E293B"),
                    "fit": "shrink",
                },
                "children": [],
            }
        )

    nodes.extend(
        [
            {
                "node_id": factory.next_id("chart"),
                "kind": "chart",
                "role": "data.chart",
                "bbox": chart_bbox,
                "content": {
                    "chartType": "bar",
                    "categories": [point["label"] for point in metric_points],
                    "series": [{"name": title_text, "values": [point["value"] for point in metric_points]}],
                    "showLegend": False,
                    "showValue": True,
                    "valueSuffix": metric_points[0].get("suffix") if metric_points else None,
                },
                "style": {
                    "color": theme_css.get("color", "#1E293B"),
                    "lineColor": theme_css.get("linkColor", "#94A3B8"),
                },
                "children": [],
            },
            {
                "node_id": factory.next_id("chart-layout"),
                "kind": "group",
                "role": "layout.chart",
                "bbox": {"x": SLIDE_MARGIN_X, "y": content_top, "w": CONTENT_WIDTH, "h": DEFAULT_SLIDE_HEIGHT - content_top - SLIDE_FOOTER_GAP},
                "content": {"layout": "chart-with-callout"},
                "style": {},
                "children": callout_children,
            },
        ]
    )
    return nodes


def _build_heading_nodes(
    title_text: str,
    subtitle_text: str | None,
    theme_css: dict[str, Any],
    factory: _NodeFactory,
) -> tuple[list[dict[str, Any]], float]:
    nodes = [
        {
            "node_id": factory.next_id("title"),
            "kind": "text",
            "role": "title",
            "bbox": {"x": SLIDE_MARGIN_X, "y": SLIDE_TITLE_Y, "w": CONTENT_WIDTH, "h": 70},
            "content": {"text": title_text},
            "style": {
                "fontSize": 28,
                "color": theme_css.get("headingColor", "#2563EB"),
                "bold": True,
                "fit": "shrink",
            },
            "children": [],
        }
    ]
    content_top = SLIDE_CONTENT_Y
    if subtitle_text:
        nodes.append(
            {
                "node_id": factory.next_id("subtitle"),
                "kind": "text",
                "role": "subtitle",
                "bbox": {"x": SLIDE_MARGIN_X, "y": 132, "w": CONTENT_WIDTH, "h": 42},
                "content": {"text": subtitle_text},
                "style": {
                    "fontSize": 15,
                    "color": theme_css.get("color", "#475569"),
                    "fit": "shrink",
                },
                "children": [],
            }
        )
        content_top = 198
    return nodes, content_top


def _build_region_nodes(
    element: _HtmlElement,
    bbox: dict[str, float],
    theme_css: dict[str, Any],
    factory: _NodeFactory,
    role_prefix: str,
) -> list[dict[str, Any]]:
    table_element = _find_first(element, {"table"})
    if table_element is not None:
        rows = _extract_table_rows(table_element)
        if rows:
            col_count = max(len(row) for row in rows)
            return [
                {
                    "node_id": factory.next_id(f"{role_prefix}-table"),
                    "kind": "table",
                    "role": f"{role_prefix}.table",
                    "bbox": bbox,
                    "content": {
                        "rows": rows,
                        "headerRows": 1,
                        "colWidths": [bbox["w"] / col_count for _ in range(col_count)],
                    },
                    "style": {
                        "fontSize": 12,
                        "headerFillColor": theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")),
                        "headerColor": theme_css.get("backgroundColor", "#FFFFFF"),
                        "fillColor": theme_css.get("cardBackgroundColor", theme_css.get("backgroundColor", "#FFFFFF")),
                        "lineColor": theme_css.get("linkColor", "#94A3B8"),
                        "color": theme_css.get("color", "#1E293B"),
                    },
                    "children": [],
                }
            ]

    metrics = _extract_metric_points(element, "")
    if len(metrics) >= 2 and bbox["w"] >= 300:
        return [
            {
                "node_id": factory.next_id(f"{role_prefix}-chart"),
                "kind": "chart",
                "role": f"{role_prefix}.chart",
                "bbox": bbox,
                "content": {
                    "chartType": "bar",
                    "categories": [point["label"] for point in metrics],
                    "series": [{"name": role_prefix, "values": [point["value"] for point in metrics]}],
                    "showLegend": False,
                    "showValue": True,
                    "valueSuffix": metrics[0].get("suffix"),
                },
                "style": {
                    "color": theme_css.get("color", "#1E293B"),
                    "lineColor": theme_css.get("linkColor", "#94A3B8"),
                },
                "children": [],
            }
        ]

    entries = _collect_flow_entries(element, None, None)
    return _build_flow_nodes(entries, bbox, theme_css, factory, role_prefix)


def _build_flow_nodes(
    entries: list[dict[str, Any]],
    bbox: dict[str, float],
    theme_css: dict[str, Any],
    factory: _NodeFactory,
    role_prefix: str,
) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    cursor_y = bbox["y"]
    max_y = bbox["y"] + bbox["h"]

    for entry in entries:
        if cursor_y >= max_y - 24:
            break
        tag = entry["tag"]
        if tag == "img":
            height = min(220, max(120, bbox["h"] * 0.38))
            if cursor_y + height > max_y:
                height = max(96, max_y - cursor_y)
            nodes.append(
                {
                    "node_id": factory.next_id(f"{role_prefix}-image"),
                    "kind": "image",
                    "role": f"{role_prefix}.image",
                    "bbox": {"x": bbox["x"], "y": cursor_y, "w": bbox["w"], "h": height},
                    "content": {"src": entry["src"], "alt": entry.get("alt") or role_prefix},
                    "style": {},
                    "children": [],
                }
            )
            cursor_y += height + 18
            continue

        role, font_size, color, spacing_after = _text_role_style(tag, theme_css)
        text = entry.get("text", "")
        line_count = max(1, text.count("\n") + (len(text) // 44))
        height = min(120, max(32, 26 + line_count * (font_size * 0.85)))
        if cursor_y + height > max_y:
            height = max(32, max_y - cursor_y)
        nodes.append(
            {
                "node_id": factory.next_id(f"{role_prefix}-{role}"),
                "kind": "text",
                "role": role,
                "bbox": {"x": bbox["x"], "y": cursor_y, "w": bbox["w"], "h": height},
                "content": {"text": text},
                "style": {
                    "fontSize": font_size,
                    "color": color,
                    "bold": role in {"headline", "section_heading"},
                    "italic": role == "quote",
                    "fit": "shrink",
                },
                "children": [],
            }
        )
        cursor_y += height + spacing_after

    return nodes


def _parse_html_tree(html: str) -> _HtmlElement:
    cleaned = re.sub(r"</?section[^>]*>", "", html, flags=re.IGNORECASE)
    parser = _HtmlTreeParser()
    parser.feed(cleaned)
    parser.close()
    return parser.root


def _section_root(tree: _HtmlElement) -> _HtmlElement:
    section = _find_first(tree, {"section"})
    return section or tree


def _find_first(node: _HtmlElement, tags: set[str]) -> _HtmlElement | None:
    for candidate in node.walk():
        if candidate.tag in tags:
            return candidate
    return None


def _find_all(node: _HtmlElement, tags: set[str]) -> list[_HtmlElement]:
    return [candidate for candidate in node.walk() if candidate.tag in tags]


def _extract_slide_title(section: _HtmlElement) -> str | None:
    heading = _find_first(section, {"h1", "h2", "h3"})
    return _node_text(heading) or None


def _extract_slide_subtitle(section: _HtmlElement, title_text: str) -> str | None:
    for entry in _collect_flow_entries(section, title_text, None):
        if entry["tag"] in {"p", "blockquote", "div"} and entry.get("text"):
            return entry["text"]
    return None


def _find_two_column_container(section: _HtmlElement) -> _HtmlElement | None:
    best: _HtmlElement | None = None
    best_score = -1
    for candidate in section.walk():
        children = _content_children(candidate)
        if len(children) != 2:
            continue
        if not (_is_layout_container(candidate, _COLUMN_CLASS_HINTS) or candidate.tag in {"section", "article"}):
            continue
        score = sum(len(_node_text(child)) for child in children)
        if score > best_score:
            best = candidate
            best_score = score
    return best


def _extract_cards(section: _HtmlElement) -> list[_CardContent]:
    for candidate in section.walk():
        children = _content_children(candidate)
        if len(children) < 3:
            continue
        if not _is_layout_container(candidate, _CARD_CLASS_HINTS):
            continue
        cards = [_card_from_element(child) for child in children]
        valid_cards = [card for card in cards if card is not None and (card.title or card.body)]
        if len(valid_cards) >= 3:
            return valid_cards

    list_items = [_node_text(node) for node in _find_all(section, {"li"}) if _node_text(node)]
    if len(list_items) < 3:
        return []
    cards: list[_CardContent] = []
    for item in list_items:
        icon = _leading_emoji(item)
        clean = item.replace(icon, "", 1).strip() if icon else item
        title, body = _split_title_body(clean)
        cards.append(_CardContent(title=title, body=body, icon=icon))
    return cards


def _extract_table_rows(table_element: _HtmlElement | None) -> list[list[str]]:
    if table_element is None:
        return []
    rows: list[list[str]] = []
    for row in _find_all(table_element, {"tr"}):
        cells = [_node_text(cell) for cell in row.children if cell.tag in {"th", "td"}]
        cells = [cell for cell in cells if cell]
        if cells:
            rows.append(cells)
    return rows


def _has_chart_markup(section: _HtmlElement) -> bool:
    for candidate in section.walk():
        if any(key.startswith("data-chart") for key in candidate.attrs):
            return True
        style = _style_map(candidate)
        children = _content_children(candidate)
        if candidate.tag == "div" and len(children) >= 2 and any(_style_map(child).get("height") for child in children):
            return True
        if "grid-template-columns" in style and any(_style_map(child).get("height") for child in children):
            return True
    return False


def _extract_metric_points(section: _HtmlElement, title_text: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for element in section.walk():
        if element.tag not in _TEXT_BLOCK_TAGS and element.tag not in {"div", "span", "strong"}:
            continue
        text = _node_text(element)
        if not text or text == title_text:
            continue
        match = _METRIC_RE.match(text)
        if not match:
            continue
        label = match.group("label").strip(" -:：")
        if not label or label in seen_labels:
            continue
        value_str = match.group("value").replace(",", "")
        try:
            value = float(value_str)
        except ValueError:
            continue
        points.append({"label": label, "value": value, "suffix": match.group("suffix") or None})
        seen_labels.add(label)
    return points


def _collect_flow_entries(
    node: _HtmlElement,
    title_text: str | None,
    subtitle_text: str | None,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def visit(element: _HtmlElement) -> None:
        if element.tag == "table":
            return
        if element.tag == "img":
            src = element.attrs.get("src", "").strip()
            if src:
                entries.append({"tag": "img", "src": src, "alt": element.attrs.get("alt", "").strip()})
            return
        if element.tag in _TEXT_BLOCK_TAGS:
            text = _node_text(element)
            if text and text not in {title_text, subtitle_text}:
                entries.append({"tag": element.tag, "text": text})
            return

        children = _content_children(element)
        if children:
            for child in children:
                visit(child)
            return

        text = _node_text(element)
        if text and text not in {title_text, subtitle_text}:
            entries.append({"tag": element.tag, "text": text})

    for child in node.children:
        visit(child)
    return entries


def _collect_body_texts(section: _HtmlElement, excluded: set[str]) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()
    for element in section.walk():
        if element.tag not in _TEXT_BLOCK_TAGS and element.tag != "div":
            continue
        text = _node_text(element)
        if not text or text in excluded or text in seen:
            continue
        texts.append(text)
        seen.add(text)
    return texts


def _content_children(node: _HtmlElement) -> list[_HtmlElement]:
    children: list[_HtmlElement] = []
    for child in node.children:
        if child.tag in {"br", "hr"}:
            continue
        if child.tag in {"img", "table"}:
            children.append(child)
            continue
        if _node_text(child) or _find_first(child, {"img", "table"}) is not None:
            children.append(child)
    return children


def _is_layout_container(node: _HtmlElement, class_hints: set[str]) -> bool:
    style = _style_map(node)
    class_tokens = {token.strip().lower() for token in node.attrs.get("class", "").split() if token.strip()}
    if class_tokens & class_hints:
        return True
    display = style.get("display", "")
    if display in {"flex", "grid", "inline-flex", "inline-grid"}:
        return True
    if "grid-template-columns" in style or "flex-direction" in style:
        return True
    return False


def _card_from_element(node: _HtmlElement) -> _CardContent | None:
    title_node = _find_first(node, {"h1", "h2", "h3", "h4", "strong"})
    title = _node_text(title_node) if title_node is not None else ""
    texts = [_node_text(candidate) for candidate in node.walk() if candidate.tag in _TEXT_BLOCK_TAGS and _node_text(candidate)]
    image = _find_first(node, {"img"})
    combined_text = " ".join(dict.fromkeys(texts))
    if not title and combined_text:
        title, body = _split_title_body(combined_text)
    else:
        body = " ".join(text for text in texts if text and text != title).strip()
    if not title and not body:
        return None
    icon = _leading_emoji(title or body)
    if icon and title.startswith(icon):
        title = title.replace(icon, "", 1).strip()
    return _CardContent(
        title=title or body[:18],
        body=body or title,
        icon=icon,
        image_src=image.attrs.get("src", "").strip() if image is not None else None,
        image_alt=image.attrs.get("alt", "").strip() if image is not None else None,
    )


def _split_title_body(text: str) -> tuple[str, str]:
    for separator in (":", "：", " - ", " | ", "，", ","):
        if separator in text:
            left, right = text.split(separator, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    words = text.split()
    if len(words) > 6:
        return " ".join(words[:4]), " ".join(words[4:])
    return text, text


def _leading_emoji(text: str) -> str | None:
    match = _EMOJI_RE.match(text.strip())
    return match.group("emoji") if match else None


def _node_text(node: _HtmlElement | None) -> str:
    if node is None:
        return ""
    parts: list[str] = []
    parts.extend(chunk for chunk in node.text_chunks if chunk)
    for child in node.children:
        if child.tag == "br":
            parts.append("\n")
            continue
        child_text = _node_text(child)
        if child_text:
            parts.append(child_text)
    text = " ".join(parts)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return text.strip()


def _style_map(node: _HtmlElement) -> dict[str, str]:
    style = node.attrs.get("style", "")
    style_map: dict[str, str] = {}
    for chunk in style.split(";"):
        if ":" not in chunk:
            continue
        key, value = chunk.split(":", 1)
        style_map[key.strip().lower()] = value.strip().lower()
    return style_map


def _text_role_style(tag: str, theme_css: dict[str, Any]) -> tuple[str, int, str, int]:
    if tag == "h2":
        return "headline", 22, theme_css.get("headingColor", "#2563EB"), 16
    if tag == "h3":
        return "section_heading", 18, theme_css.get("accentColor", theme_css.get("headingColor", "#2563EB")), 14
    if tag == "li":
        return "bullet", 16, theme_css.get("color", "#1E293B"), 10
    if tag == "blockquote":
        return "quote", 16, theme_css.get("accentColor", "#475569"), 12
    if tag in {"pre", "code"}:
        return "code", 13, theme_css.get("accentColor", "#0F172A"), 14
    return "body", 15, theme_css.get("color", "#1E293B"), 12


def _format_metric_value(value: float, suffix: str | None) -> str:
    rendered = str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{rendered}{suffix or ''}"