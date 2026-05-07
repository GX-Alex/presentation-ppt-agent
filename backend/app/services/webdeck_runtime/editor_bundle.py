"""WebDeck 页面结构化编辑模型派生。"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from app.services.webdeck_runtime.contracts import AssetNode, PageBundle

DEFAULT_STAGE_WIDTH = 1280
DEFAULT_STAGE_HEIGHT = 720

_WHITESPACE_RE = re.compile(r"\s+")
_GRID_CLASS_RE = re.compile(r"^s-grid-(\d+)$")
_STRUCTURAL_EDITABLE_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "blockquote", "li", "th", "td", "figcaption"}
_GENERIC_EDITABLE_TAGS = {"div", "span"}
_EXPLICIT_EDITABLE_ROLES = {"caption", "metric-label", "metric-value"}
_INLINE_FORMATTING_TAGS = {"a", "b", "br", "code", "em", "i", "mark", "small", "strong", "sub", "sup", "u"}
_LAYOUT_SCOPE_TAGS = {"section", "main", "article"}
_CHART_CLASS_NAMES = {"deck-chart-wrapper"}
_DIAGRAM_CLASS_NAMES = {"deck-diagram-wrapper"}


def _normalize_space(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def _class_list(attrs: dict[str, str]) -> list[str]:
    return [item for item in str(attrs.get("class") or "").split() if item]


def _style_map(style: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for fragment in (style or "").split(";"):
        if ":" not in fragment:
            continue
        key, value = fragment.split(":", 1)
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if normalized_key and normalized_value:
            declarations[normalized_key] = normalized_value
    return declarations


def _parse_numeric(value: str | None) -> int | float | None:
    if not value:
        return None
    candidate = value.strip().split()[0]
    match = re.search(r"-?\d+(?:\.\d+)?", candidate)
    if not match:
        return None
    parsed = float(match.group(0))
    return int(parsed) if parsed.is_integer() else parsed


def _parse_percent(value: str | None) -> int | float | None:
    if not value or "%" not in value:
        return None
    return _parse_numeric(value)


def _parse_list_attr(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _parse_visibility_attr(value: str | None) -> dict[str, bool]:
    visibility: dict[str, bool] = {}
    for token in _parse_list_attr(value):
        if ":" not in token:
            continue
        module_id, state = token.split(":", 1)
        normalized_id = module_id.strip()
        normalized_state = state.strip().lower()
        if normalized_id:
            visibility[normalized_id] = normalized_state not in {"hidden", "none", "false", "0"}
    return visibility


def _infer_density(explicit: str | None, gap: int | float | None, padding: int | float | None) -> str:
    if explicit:
        return explicit.strip().lower()
    gap_value = float(gap) if gap is not None else 0.0
    padding_value = float(padding) if padding is not None else 0.0
    if gap_value <= 12 and padding_value <= 16:
        return "compact"
    if gap_value >= 24 or padding_value >= 24:
        return "spacious"
    return "balanced"


def _selector_hint(tag: str, attrs: dict[str, str], classes: list[str]) -> str:
    element_id = attrs.get("id")
    return "".join([tag.lower(), f"#{element_id}" if element_id else "", *[f".{item}" for item in classes[:2]]])


def _infer_scope_kind(tag: str, classes: list[str], style: str) -> str:
    class_text = " ".join(classes).lower()
    style_text = (style or "").replace(" ", "").lower()
    if "grid" in class_text or "display:grid" in style_text:
        return "grid"
    if "flex" in class_text or "display:flex" in style_text:
        return "flex"
    if any(token in class_text for token in ("chart", "diagram", "visual")):
        return "visual_group"
    return "container"


def _guess_columns(classes: list[str], style: str) -> int | None:
    for class_name in classes:
        match = _GRID_CLASS_RE.match(class_name)
        if match:
            return int(match.group(1))

    repeat_match = re.search(r"repeat\((\d+),", style or "", flags=re.IGNORECASE)
    if repeat_match:
        return int(repeat_match.group(1))

    return None


def _is_layout_scope(tag: str, classes: list[str], style: str) -> bool:
    if tag in _LAYOUT_SCOPE_TAGS:
        return True

    class_text = " ".join(classes).lower()
    style_text = (style or "").replace(" ", "").lower()
    return any(token in class_text for token in ("grid", "flex", "visual", "chart", "diagram")) or "display:grid" in style_text or "display:flex" in style_text


def _build_scope_parameters(attrs: dict[str, str], classes: list[str], style: str) -> dict[str, Any]:
    styles = _style_map(style)
    columns = _parse_numeric(attrs.get("data-layout-columns"))
    if columns is None:
        columns = _guess_columns(classes, style)

    gap = _parse_numeric(attrs.get("data-layout-gap"))
    if gap is None:
        gap = _parse_numeric(styles.get("gap") or styles.get("column-gap"))

    padding = _parse_numeric(attrs.get("data-layout-padding"))
    if padding is None:
        padding = _parse_numeric(styles.get("padding") or styles.get("padding-inline") or styles.get("padding-block"))

    width_ratio = _parse_numeric(attrs.get("data-layout-width-ratio"))
    if width_ratio is None:
        width_ratio = _parse_percent(styles.get("width") or styles.get("max-width"))

    justify = attrs.get("data-layout-justify") or styles.get("justify-content")
    align = attrs.get("data-layout-align") or styles.get("align-items")
    density = _infer_density(attrs.get("data-layout-density"), gap, padding)
    module_order = _parse_list_attr(attrs.get("data-layout-module-order"))
    module_visibility = _parse_visibility_attr(attrs.get("data-layout-module-visibility"))

    return {
        "columns": columns,
        "widthRatio": width_ratio,
        "gap": gap,
        "padding": padding,
        "justify": justify,
        "align": align,
        "density": density,
        "moduleOrder": module_order,
        "moduleVisibility": module_visibility,
        "classNames": classes,
    }


def _infer_node_kind(tag: str, attrs: dict[str, str], classes: list[str], stack: list[dict[str, Any]]) -> str:
    if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading"
    if tag == "li":
        return "list_item"
    if tag in {"th", "td"}:
        return "table_cell"
    if tag == "figcaption" or attrs.get("data-role") == "caption":
        return "caption"
    if tag in {"p", "blockquote"}:
        parent_classes = {item for frame in stack for item in frame.get("classes", [])}
        if {"deck-point-card", "s-card"} & parent_classes:
            return "card_text"
        return "paragraph"
    return "text"


def _is_layout_like(classes: list[str], style: str) -> bool:
    class_text = " ".join(classes).lower()
    style_text = (style or "").replace(" ", "").lower()
    return "grid" in class_text or "flex" in class_text or "display:grid" in style_text or "display:flex" in style_text


def _is_candidate_editable(tag: str, attrs: dict[str, str]) -> bool:
    return tag in _STRUCTURAL_EDITABLE_TAGS or tag in _GENERIC_EDITABLE_TAGS or attrs.get("data-role") in _EXPLICIT_EDITABLE_ROLES


def _artifact_to_manifest_item(artifact: AssetNode) -> dict[str, Any]:
    metadata = artifact.metadata or {}
    return {
        "asset_id": artifact.asset_id,
        "kind": artifact.kind,
        "label": metadata.get("label") or artifact.kind,
        "editable_via": "chart_spec" if artifact.kind == "chart" else "drawio" if artifact.kind == "diagram" else "preview_only",
        "binding_node_id": metadata.get("binding_node_id"),
        "metadata": metadata,
    }


def _artifact_from_dict(raw: dict[str, Any]) -> AssetNode:
    return AssetNode(
        asset_id=str(raw.get("asset_id") or raw.get("assetId") or ""),
        kind=str(raw.get("kind") or "asset"),
        content=str(raw.get("content") or ""),
        metadata=dict(raw.get("metadata") or {}),
    )


def _payload_value(payload: dict[str, Any], snake_key: str, camel_key: str) -> Any:
    if snake_key in payload:
        return payload.get(snake_key)
    return payload.get(camel_key)


def _normalize_manifest_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    asset_id = str(raw.get("asset_id") or raw.get("assetId") or "")
    if not asset_id:
        return None

    kind = str(raw.get("kind") or "asset")
    label = str(raw.get("label") or kind)
    editable_via = str(raw.get("editable_via") or raw.get("editableVia") or "preview_only")
    binding_node_id = raw.get("binding_node_id") or raw.get("bindingNodeId")

    return {
        "asset_id": asset_id,
        "kind": kind,
        "label": label,
        "editable_via": editable_via,
        "binding_node_id": str(binding_node_id) if binding_node_id else None,
        "metadata": dict(raw.get("metadata") or {}),
    }


class _StructuredBundleParser(HTMLParser):
    def __init__(self, page_id: str, base_asset_manifest: list[dict[str, Any]]):
        super().__init__(convert_charrefs=True)
        self.page_id = page_id
        self._node_counters: dict[str, int] = {}
        self._scope_counters: dict[str, int] = {}
        self._asset_counters: dict[str, int] = {"chart": 0, "diagram": 0}
        self._stack: list[dict[str, Any]] = []
        self.editable_model: list[dict[str, Any]] = []
        self.layout_model: list[dict[str, Any]] = []
        self.asset_manifest: list[dict[str, Any]] = list(base_asset_manifest)
        self._known_asset_ids = {
            str(item.get("asset_id") or "")
            for item in base_asset_manifest
            if item.get("asset_id")
        }

    def _current_scope_id(self) -> str | None:
        for frame in reversed(self._stack):
            scope_id = frame.get("scope_id")
            if scope_id:
                return scope_id
        return None

    def _append_detected_asset(self, kind: str, label: str) -> None:
        self._asset_counters[kind] += 1
        asset_id = f"detected-{kind}-{self._asset_counters[kind]}"
        if asset_id in self._known_asset_ids:
            return
        self._known_asset_ids.add(asset_id)
        self.asset_manifest.append({
            "asset_id": asset_id,
            "kind": kind,
            "label": label,
            "editable_via": "chart_spec" if kind == "chart" else "drawio",
            "metadata": {},
        })

    def handle_starttag(self, tag: str, attrs_seq: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_seq}
        tag = tag.lower()
        classes = _class_list(attrs)
        style = attrs.get("style") or ""

        scope_id = None
        scope_payload = None
        if _is_layout_scope(tag, classes, style):
            scope_kind = _infer_scope_kind(tag, classes, style)
            if not any(frame.get("scope_id") for frame in self._stack):
                scope_id = "scope-page-root"
            else:
                self._scope_counters[scope_kind] = self._scope_counters.get(scope_kind, 0) + 1
                scope_id = f"scope-{scope_kind}-{self._scope_counters[scope_kind]}"
            scope_payload = {
                "scope_id": scope_id,
                "scope_kind": scope_kind,
                "tag_name": tag,
                "label": attrs.get("aria-label") or attrs.get("data-layout-label") or attrs.get("class") or f"{scope_kind}-{self._scope_counters.get(scope_kind, 0) or 1}",
                "module_node_ids": [],
                "allowed_ops": ["columns", "width_ratio", "gap", "padding", "align", "justify", "module_order", "module_visibility", "density"] if scope_kind == "grid" else ["gap", "padding", "align", "justify", "module_order", "module_visibility", "density"],
                "parameters": _build_scope_parameters(attrs, classes, style),
            }

        class_set = set(classes)
        if attrs.get("data-chart") or class_set & _CHART_CLASS_NAMES:
            self._append_detected_asset("chart", f"图表 {self._asset_counters['chart'] + 1}")
        if tag == "svg" or class_set & _DIAGRAM_CLASS_NAMES:
            self._append_detected_asset("diagram", f"图示 {self._asset_counters['diagram'] + 1}")

        self._stack.append({
            "tag": tag,
            "attrs": attrs,
            "classes": classes,
            "style": style,
            "scope_id": scope_id,
            "scope_payload": scope_payload,
            "text_parts": [],
            "direct_text_parts": [],
            "has_editable_child": False,
            "has_children": False,
            "only_inline_children": True,
            "has_blocking_child": False,
        })

    def handle_data(self, data: str) -> None:
        if not data:
            return
        for frame in self._stack:
            frame["text_parts"].append(data)
        if self._stack:
            self._stack[-1]["direct_text_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        frame = self._stack.pop()

        tag = str(frame.get("tag") or tag).lower()
        attrs = dict(frame.get("attrs") or {})
        classes = list(frame.get("classes") or [])
        style = str(frame.get("style") or "")
        text = _normalize_space("".join(frame.get("text_parts") or []))
        direct_text = _normalize_space("".join(frame.get("direct_text_parts") or []))

        is_editable = False
        if text and _is_candidate_editable(tag, attrs):
            if tag in _STRUCTURAL_EDITABLE_TAGS or attrs.get("data-role") in _EXPLICIT_EDITABLE_ROLES:
                is_editable = True
            elif tag in _GENERIC_EDITABLE_TAGS:
                is_editable = (
                    not _is_layout_like(classes, style)
                    and not frame.get("has_editable_child")
                    and not frame.get("has_blocking_child")
                    and (bool(direct_text) or (frame.get("has_children") and frame.get("only_inline_children")))
                )

        if is_editable:
            node_kind = _infer_node_kind(tag, attrs, classes, self._stack)
            self._node_counters[node_kind] = self._node_counters.get(node_kind, 0) + 1
            node_payload = {
                "node_id": f"{node_kind}-{self._node_counters[node_kind]}",
                "node_kind": node_kind,
                "tag_name": tag,
                "selector_hint": _selector_hint(tag, attrs, classes),
                "layout_scope_id": frame.get("scope_id") or self._current_scope_id(),
                "editable": True,
                "text": text,
            }
            self.editable_model.append(node_payload)
            node_id = node_payload.get("node_id")
            for open_frame in self._stack:
                scope_payload = open_frame.get("scope_payload")
                if scope_payload is not None and node_id and node_id not in scope_payload["module_node_ids"]:
                    scope_payload["module_node_ids"].append(node_id)

        if self._stack:
            parent = self._stack[-1]
            parent["has_children"] = True
            if tag not in _INLINE_FORMATTING_TAGS:
                parent["only_inline_children"] = False
            if is_editable:
                parent["has_editable_child"] = True
            if _is_layout_like(classes, style) or tag in {"svg", "canvas", "img", "table", "ul", "ol", "figure"}:
                parent["has_blocking_child"] = True

        scope_payload = frame.get("scope_payload")
        if scope_payload is not None:
            self.layout_model.append(scope_payload)


def hydrate_page_bundle(bundle: PageBundle) -> PageBundle:
    base_asset_manifest: list[dict[str, Any]] = []
    seen_asset_ids: set[str] = set()

    for raw_item in bundle.asset_manifest or []:
        normalized = _normalize_manifest_item(raw_item)
        if not normalized:
            continue
        asset_id = str(normalized.get("asset_id") or "")
        if asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        base_asset_manifest.append(normalized)

    for artifact in bundle.artifacts:
        normalized = _artifact_to_manifest_item(artifact)
        asset_id = str(normalized.get("asset_id") or "")
        if not asset_id or asset_id in seen_asset_ids:
            continue
        seen_asset_ids.add(asset_id)
        base_asset_manifest.append(normalized)

    parser = _StructuredBundleParser(
        bundle.page_id,
        base_asset_manifest,
    )
    parser.feed(bundle.html or "")
    parser.close()

    bundle.editor_schema_version = bundle.editor_schema_version or "p1-runtime-v1"
    bundle.editable_model = parser.editable_model
    bundle.layout_model = parser.layout_model
    bundle.asset_manifest = parser.asset_manifest
    bundle.render_hints = {
        "stage_width": DEFAULT_STAGE_WIDTH,
        "stage_height": DEFAULT_STAGE_HEIGHT,
        "surface": "shadow_root",
        **(bundle.render_hints or {}),
    }
    return bundle


def build_page_bundle_payload(
    page_id: str,
    html: str,
    base_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(base_payload or {})
    bundle = PageBundle(
        page_id=page_id,
        status=str(payload.get("status") or "completed"),
        html=html,
        css_tokens=dict(_payload_value(payload, "css_tokens", "cssTokens") or {}),
        js_modules=list(_payload_value(payload, "js_modules", "jsModules") or []),
        artifacts=[
            _artifact_from_dict(item)
            for item in payload.get("artifacts", [])
            if isinstance(item, dict)
        ],
        editor_schema_version=str(_payload_value(payload, "editor_schema_version", "editorSchemaVersion") or "") or None,
        asset_manifest=[
            normalized
            for item in (_payload_value(payload, "asset_manifest", "assetManifest") or [])
            if isinstance(item, dict)
            for normalized in [_normalize_manifest_item(item)]
            if normalized
        ],
        render_hints=dict(_payload_value(payload, "render_hints", "renderHints") or {}),
    )
    hydrate_page_bundle(bundle)
    return bundle.to_dict()