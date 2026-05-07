from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree as ET

from app.services.diagram_xml_validator import validate_and_fix_xml


MAX_VALIDATION_RETRIES = 3


@dataclass
class DiagramReviewIssue:
    level: str
    code: str
    message: str
    cell_id: str | None = None
    suggestion: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiagramVisualReviewResult:
    valid: bool
    issues: list[DiagramReviewIssue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    review_mode: str = "heuristic"
    score: int = 100
    should_retry: bool = False
    snapshot_source: str = "xml"
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    @property
    def critical_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "critical")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.level == "warning")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["critical_count"] = self.critical_count
        payload["warning_count"] = self.warning_count
        return payload


def _parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _graph_model(root: ET.Element) -> ET.Element:
    if root.tag == "mxGraphModel":
        return root
    if root.tag != "mxfile":
        raise ValueError(f"unsupported root tag: {root.tag}")
    diagram = root.find("diagram")
    if diagram is None:
        raise ValueError("diagram element missing")
    graph_model = diagram.find("mxGraphModel")
    if graph_model is None:
        raise ValueError("mxGraphModel missing")
    return graph_model


def _graph_root(graph_model: ET.Element) -> ET.Element:
    root = graph_model.find("root")
    if root is None:
        raise ValueError("root element missing")
    return root


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", unescape(value or "")).strip()


def _display_units(text: str) -> int:
    units = 0
    for char in text:
        units += 2 if ord(char) > 127 else 1
    return units


def _append_issue(
    issues: list[DiagramReviewIssue],
    level: str,
    code: str,
    message: str,
    *,
    cell_id: str | None = None,
    suggestion: str | None = None,
) -> None:
    issues.append(
        DiagramReviewIssue(
            level=level,
            code=code,
            message=message,
            cell_id=cell_id,
            suggestion=suggestion,
        )
    )


def _vertex_cells(root: ET.Element) -> list[dict[str, Any]]:
    vertices: list[dict[str, Any]] = []
    for cell in root.findall("mxCell"):
        if cell.get("id") in {"0", "1"} or cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        vertices.append(
            {
                "cell_id": cell.get("id") or "",
                "label": _strip_tags(cell.get("value") or ""),
                "x": _parse_float(geometry.get("x") if geometry is not None else None),
                "y": _parse_float(geometry.get("y") if geometry is not None else None),
                "width": _parse_float(geometry.get("width") if geometry is not None else None, 120.0),
                "height": _parse_float(geometry.get("height") if geometry is not None else None, 60.0),
            }
        )
    return vertices


def _edge_cells(root: ET.Element) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for cell in root.findall("mxCell"):
        if cell.get("id") in {"0", "1"}:
            continue
        if cell.get("edge") == "1" or (cell.get("source") and cell.get("target")):
            edges.append(
                {
                    "cell_id": cell.get("id") or "",
                    "source": cell.get("source"),
                    "target": cell.get("target"),
                }
            )
    return edges


def review_diagram_snapshot(*, xml: str, svg: str | None = None, png: str | None = None) -> DiagramVisualReviewResult:
    structural = validate_and_fix_xml(xml, allow_fragment=False)
    if not structural.valid:
        return DiagramVisualReviewResult(
            valid=False,
            issues=[
                DiagramReviewIssue(
                    level="critical",
                    code="structural_invalid",
                    message=structural.error or "diagram XML invalid",
                    suggestion="先修复 XML 结构错误，再继续校验布局。",
                )
            ],
            suggestions=["先修复 XML 结构错误，再继续校验布局。"],
            score=0,
            should_retry=False,
            snapshot_source="xml",
        )

    root = ET.fromstring(structural.xml)
    graph_model = _graph_model(root)
    graph_root = _graph_root(graph_model)
    page_width = _parse_float(graph_model.get("pageWidth"), 827.0)
    page_height = _parse_float(graph_model.get("pageHeight"), 1169.0)
    vertices = _vertex_cells(graph_root)
    edges = _edge_cells(graph_root)
    issues: list[DiagramReviewIssue] = []

    if not vertices:
        _append_issue(
            issues,
            "critical",
            "empty_diagram",
            "当前图没有任何可见节点。",
            suggestion="至少添加 2 个以上的业务节点，再补充连接关系。",
        )
    elif len(vertices) == 1:
        _append_issue(
            issues,
            "warning",
            "single_node_diagram",
            "当前图只有 1 个节点，通常还不足以表达完整流程。",
            cell_id=vertices[0]["cell_id"],
            suggestion="如果这是流程图或架构图，请补充上下游节点或阶段节点。",
        )

    if len(vertices) >= 3 and not edges:
        _append_issue(
            issues,
            "critical",
            "missing_edges",
            "当前图包含多个节点，但没有连接线来表达关系。",
            suggestion="为关键节点补充带箭头的连接线，明确数据流或调用关系。",
        )

    connected_vertices = {edge["source"] for edge in edges if edge.get("source")}
    connected_vertices.update(edge["target"] for edge in edges if edge.get("target"))

    min_x = page_width
    min_y = page_height
    max_x = 0.0
    max_y = 0.0
    for vertex in vertices:
        cell_id = vertex["cell_id"]
        x = float(vertex["x"])
        y = float(vertex["y"])
        width = float(vertex["width"])
        height = float(vertex["height"])
        label = str(vertex["label"] or "")

        min_x = min(min_x, x)
        min_y = min(min_y, y)
        max_x = max(max_x, x + width)
        max_y = max(max_y, y + height)

        if width < 90 or height < 44:
            _append_issue(
                issues,
                "warning",
                "small_node",
                f"节点 {cell_id} 尺寸较小，标签和端点可能拥挤。",
                cell_id=cell_id,
                suggestion="将节点宽度提升到 100-140，高度提升到 50-70。",
            )

        if x < 0 or y < 0 or x + width > page_width or y + height > page_height:
            _append_issue(
                issues,
                "critical",
                "out_of_bounds",
                f"节点 {cell_id} 超出了当前画布范围。",
                cell_id=cell_id,
                suggestion="将所有节点控制在画布内，必要时重新布局或增大画布。",
            )

        if label:
            estimated_capacity = max(6, int(max(width - 18, 20) / 7.5))
            if _display_units(label) > estimated_capacity * 1.25:
                _append_issue(
                    issues,
                    "warning",
                    "label_may_truncate",
                    f"节点 {cell_id} 的标签可能被截断：{label[:24]}",
                    cell_id=cell_id,
                    suggestion="缩短标签，或增大节点宽度并开启自动换行样式。",
                )

        if len(vertices) >= 3 and cell_id not in connected_vertices:
            _append_issue(
                issues,
                "warning",
                "orphan_node",
                f"节点 {cell_id} 未与其他节点建立连接。",
                cell_id=cell_id,
                suggestion="确认该节点是否应与上下游相连；若不是，请在图中明确其角色。",
            )

    for index, first in enumerate(vertices):
        for second in vertices[index + 1:]:
            left = max(float(first["x"]), float(second["x"]))
            top = max(float(first["y"]), float(second["y"]))
            right = min(float(first["x"]) + float(first["width"]), float(second["x"]) + float(second["width"]))
            bottom = min(float(first["y"]) + float(first["height"]), float(second["y"]) + float(second["height"]))
            overlap_width = max(0.0, right - left)
            overlap_height = max(0.0, bottom - top)
            if overlap_width <= 0 or overlap_height <= 0:
                continue
            overlap_area = overlap_width * overlap_height
            first_area = float(first["width"]) * float(first["height"])
            second_area = float(second["width"]) * float(second["height"])
            overlap_ratio = overlap_area / max(min(first_area, second_area), 1.0)
            if overlap_ratio >= 0.2:
                _append_issue(
                    issues,
                    "critical",
                    "node_overlap",
                    f"节点 {first['cell_id']} 与 {second['cell_id']} 存在明显重叠。",
                    suggestion="拉开相邻节点间距，保持至少 24-32px 的留白。",
                )
            elif overlap_ratio >= 0.08:
                _append_issue(
                    issues,
                    "warning",
                    "node_spacing_tight",
                    f"节点 {first['cell_id']} 与 {second['cell_id']} 间距过近。",
                    suggestion="适当增加节点间距，避免文本和连线显得拥挤。",
                )

    if vertices:
        bbox_area = max(max_x - min_x, 1.0) * max(max_y - min_y, 1.0)
        page_area = max(page_width * page_height, 1.0)
        if len(vertices) >= 6 and bbox_area / page_area > 0.82:
            _append_issue(
                issues,
                "warning",
                "dense_layout",
                "当前图在单页内过于拥挤，后续扩展可能继续压缩可读性。",
                suggestion="拆分层级、改成纵向布局，或增大画布尺寸。",
            )

    suggestions: list[str] = []
    seen_suggestions: set[str] = set()
    for issue in issues:
        if issue.suggestion and issue.suggestion not in seen_suggestions:
            seen_suggestions.add(issue.suggestion)
            suggestions.append(issue.suggestion)

    critical_count = sum(1 for issue in issues if issue.level == "critical")
    warning_count = sum(1 for issue in issues if issue.level == "warning")
    score = max(0, 100 - critical_count * 25 - warning_count * 8)
    snapshot_source = "hybrid" if svg or png else "xml"
    return DiagramVisualReviewResult(
        valid=critical_count == 0,
        issues=issues,
        suggestions=suggestions,
        review_mode="heuristic",
        score=score,
        should_retry=critical_count > 0,
        snapshot_source=snapshot_source,
    )


def next_retry_count(
    previous_validation: dict[str, Any] | None,
    *,
    previous_xml: str | None,
    current_xml: str,
) -> int:
    if not previous_validation or not previous_xml or previous_xml == current_xml:
        return 0
    if not previous_validation.get("retry_recommended"):
        return 0
    try:
        return int(previous_validation.get("retry_count") or 0) + 1
    except (TypeError, ValueError):
        return 1


def build_validation_payload(
    structural_validation: dict[str, Any] | Any,
    *,
    review_result: DiagramVisualReviewResult | None = None,
    retry_count: int = 0,
    max_retries: int = MAX_VALIDATION_RETRIES,
) -> dict[str, Any]:
    if hasattr(structural_validation, "to_dict"):
        payload = dict(structural_validation.to_dict())
    else:
        payload = dict(structural_validation or {})

    # Validation payloads are persisted in diagram sessions and tool history.
    # Keep them lightweight by removing raw XML copies that the model can
    # retrieve via diagram tools when needed.
    payload.pop("xml", None)
    payload.pop("fixed_xml", None)

    updated_at = datetime.utcnow().isoformat()
    if review_result is None:
        payload.setdefault("review_passed", bool(payload.get("valid", False)))
        payload.setdefault("review_mode", "structural")
        payload.setdefault("issues", [])
        payload.setdefault("suggestions", [])
        payload.setdefault("retry_recommended", False)
        payload.setdefault("score", 100 if payload.get("valid") else 0)
        payload.setdefault("critical_count", 0 if payload.get("valid") else 1)
        payload.setdefault("warning_count", len(payload.get("warnings") or []))
        payload.setdefault("snapshot_source", "xml")
        payload["retry_count"] = retry_count
        payload["max_retries"] = max_retries
        payload["updated_at"] = updated_at
        return payload

    payload.update(
        {
            "review_passed": review_result.valid,
            "review_mode": review_result.review_mode,
            "issues": [issue.to_dict() for issue in review_result.issues],
            "suggestions": review_result.suggestions,
            "retry_recommended": review_result.should_retry and retry_count < max_retries,
            "retry_count": retry_count,
            "max_retries": max_retries,
            "score": review_result.score,
            "critical_count": review_result.critical_count,
            "warning_count": review_result.warning_count,
            "snapshot_source": review_result.snapshot_source,
            "updated_at": review_result.updated_at,
        }
    )
    return payload
