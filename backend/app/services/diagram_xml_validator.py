from __future__ import annotations

import re
import uuid
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any
from xml.etree import ElementTree as ET


BLANK_MXFILE = (
    '<mxfile host="app.diagrams.net">'
    '<diagram id="{diagram_id}" name="Page-1">'
    '<mxGraphModel dx="1000" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" '
    'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="827" pageHeight="1169" '
    'math="0" shadow="0">'
    '<root><mxCell id="0"/><mxCell id="1" parent="0"/></root>'
    '</mxGraphModel></diagram></mxfile>'
)

_ARTIFACT_RE = re.compile(r"<general-artifact\s+type=\"drawio\">([\s\S]*?)</general-artifact>", re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:xml|drawio)?\s*\n([\s\S]*?)\n```", re.IGNORECASE)


@dataclass
class DiagramXmlValidationResult:
    valid: bool
    xml: str = ""
    fixed: bool = False
    fixes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _new_cell_id(existing_ids: set[str]) -> str:
    while True:
        candidate = f"cell_{uuid.uuid4().hex[:8]}"
        if candidate not in existing_ids:
            return candidate


def _strip_wrappers(raw: str) -> str:
    content = (raw or "").strip()
    if not content:
        return ""

    artifact_match = _ARTIFACT_RE.search(content)
    if artifact_match:
        content = artifact_match.group(1).strip()

    code_match = _CODE_FENCE_RE.search(content)
    if code_match:
        content = code_match.group(1).strip()

    return content.strip()


def build_blank_mxfile() -> str:
    return BLANK_MXFILE.format(diagram_id=f"diagram_{uuid.uuid4().hex[:8]}")


def is_mxcell_fragment_complete(fragment: str) -> bool:
    snippet = (fragment or "").strip()
    if not snippet:
        return False
    wrapped = f"<fragment>{snippet}</fragment>"
    try:
        ET.fromstring(wrapped)
        return True
    except ET.ParseError:
        return False


def _clone_cell(cell: ET.Element) -> ET.Element:
    return deepcopy(cell)


def _parse_xml(xml: str) -> ET.Element:
    return ET.fromstring(xml)


def _graph_root(mxfile_root: ET.Element) -> ET.Element:
    if mxfile_root.tag == "mxGraphModel":
        graph_model = mxfile_root
    elif mxfile_root.tag == "mxfile":
        diagram = mxfile_root.find("diagram")
        if diagram is None:
            diagram = ET.SubElement(mxfile_root, "diagram", {"id": f"diagram_{uuid.uuid4().hex[:8]}", "name": "Page-1"})
        graph_model = diagram.find("mxGraphModel")
        if graph_model is None:
            graph_model = ET.SubElement(diagram, "mxGraphModel")
    else:
        raise ValueError(f"unsupported root tag: {mxfile_root.tag}")

    root = graph_model.find("root")
    if root is None:
        root = ET.SubElement(graph_model, "root")
    return root


def _wrap_graph_model(graph_model: ET.Element) -> ET.Element:
    blank = _parse_xml(build_blank_mxfile())
    diagram = blank.find("diagram")
    if diagram is None:
        raise ValueError("blank mxfile missing diagram")
    existing = diagram.find("mxGraphModel")
    if existing is not None:
        diagram.remove(existing)
    diagram.append(graph_model)
    return blank


def _wrap_root(root_element: ET.Element) -> ET.Element:
    graph_model = ET.Element("mxGraphModel")
    graph_model.append(root_element)
    return _wrap_graph_model(graph_model)


def wrap_mxcells_with_mxfile(fragment: str) -> str:
    container = ET.fromstring(f"<fragment>{fragment}</fragment>")
    blank = _parse_xml(build_blank_mxfile())
    graph_root = _graph_root(blank)
    for child in list(container):
        if child.tag != "mxCell":
            raise ValueError(f"unsupported fragment tag: {child.tag}")
        graph_root.append(_clone_cell(child))
    return ET.tostring(blank, encoding="unicode")


def _normalize_to_mxfile(content: str, fixes: list[str]) -> str:
    if "<mxfile" in content:
        start = content.find("<mxfile")
        end = content.rfind("</mxfile>")
        if end == -1:
            raise ValueError("draw.io XML 缺少 </mxfile>")
        return content[start:end + len("</mxfile>")]

    if "<mxGraphModel" in content:
        start = content.find("<mxGraphModel")
        end = content.rfind("</mxGraphModel>")
        if end == -1:
            raise ValueError("draw.io XML 缺少 </mxGraphModel>")
        graph_model = _parse_xml(content[start:end + len("</mxGraphModel>")])
        fixes.append("wrapped_mxgraphmodel")
        return ET.tostring(_wrap_graph_model(graph_model), encoding="unicode")

    if "<root" in content:
        start = content.find("<root")
        end = content.rfind("</root>")
        if end == -1:
            raise ValueError("draw.io XML 缺少 </root>")
        root = _parse_xml(content[start:end + len("</root>")])
        fixes.append("wrapped_root")
        return ET.tostring(_wrap_root(root), encoding="unicode")

    if "<mxCell" in content:
        if not is_mxcell_fragment_complete(content):
            raise ValueError("mxCell fragment 不完整")
        fixes.append("wrapped_mxcell_fragment")
        return wrap_mxcells_with_mxfile(content)

    raise ValueError("未检测到 draw.io XML 或 mxCell fragment")


def _ensure_root_cells(root: ET.Element, fixes: list[str]) -> None:
    cells_by_id = {cell.get("id"): cell for cell in root.findall("mxCell")}
    if "0" not in cells_by_id:
        root.insert(0, ET.Element("mxCell", {"id": "0"}))
        fixes.append("inserted_root_cell_0")
    if "1" not in cells_by_id:
        index = 1 if len(root) > 0 else 0
        root.insert(index, ET.Element("mxCell", {"id": "1", "parent": "0"}))
        fixes.append("inserted_root_cell_1")


def _validate_cells(root: ET.Element, fixes: list[str], warnings: list[str]) -> tuple[bool, str | None]:
    existing_ids: set[str] = set()
    for cell in root.findall("mxCell"):
        cell_id = cell.get("id")
        if not cell_id:
            cell_id = _new_cell_id(existing_ids)
            cell.set("id", cell_id)
            fixes.append("generated_missing_cell_id")
        if cell_id in existing_ids:
            return False, f"检测到重复 cell id: {cell_id}"
        existing_ids.add(cell_id)

    for cell in root.findall("mxCell"):
        cell_id = cell.get("id") or ""
        if cell_id in {"0", "1"}:
            continue

        if not cell.get("parent"):
            cell.set("parent", "1")
            fixes.append(f"assigned_default_parent:{cell_id}")

        parent = cell.get("parent")
        if parent and parent not in existing_ids:
            return False, f"cell {cell_id} 引用了不存在的 parent: {parent}"

        source = cell.get("source")
        if source and source not in existing_ids:
            return False, f"cell {cell_id} 引用了不存在的 source: {source}"

        target = cell.get("target")
        if target and target not in existing_ids:
            return False, f"cell {cell_id} 引用了不存在的 target: {target}"

        nested_cells = cell.findall("mxCell")
        if nested_cells:
            return False, f"cell {cell_id} 存在非法嵌套 mxCell"

        geometry = cell.find("mxGeometry")
        if geometry is None and cell.get("vertex") == "1":
            ET.SubElement(
                cell,
                "mxGeometry",
                {"x": "0", "y": "0", "width": "120", "height": "60", "as": "geometry"},
            )
            warnings.append(f"vertex {cell_id} 缺少 geometry，已补默认尺寸")
        elif geometry is not None and geometry.get("as") != "geometry":
            geometry.set("as", "geometry")
            fixes.append(f"fixed_geometry_as_attr:{cell_id}")

    return True, None


def validate_and_fix_xml(raw_xml: str, *, allow_fragment: bool = True) -> DiagramXmlValidationResult:
    content = _strip_wrappers(raw_xml)
    if not content:
        return DiagramXmlValidationResult(valid=False, error="draw.io XML 不能为空")

    fixes: list[str] = []
    warnings: list[str] = []

    try:
        xml = _normalize_to_mxfile(content, fixes)
    except ValueError as exc:
        if not allow_fragment:
            return DiagramXmlValidationResult(valid=False, error=str(exc))
        return DiagramXmlValidationResult(valid=False, error=str(exc))

    try:
        root = _parse_xml(xml)
    except ET.ParseError as exc:
        return DiagramXmlValidationResult(valid=False, error=f"XML 解析失败: {exc}")

    try:
        graph_root = _graph_root(root)
    except ValueError as exc:
        return DiagramXmlValidationResult(valid=False, error=str(exc))

    _ensure_root_cells(graph_root, fixes)
    is_valid, error = _validate_cells(graph_root, fixes, warnings)
    if not is_valid:
        return DiagramXmlValidationResult(valid=False, error=error)

    normalized = ET.tostring(root, encoding="unicode")
    return DiagramXmlValidationResult(
        valid=True,
        xml=normalized,
        fixed=bool(fixes),
        fixes=fixes,
        warnings=warnings,
    )


def extract_mx_cells(xml_or_fragment: str) -> list[ET.Element]:
    result = validate_and_fix_xml(xml_or_fragment, allow_fragment=True)
    if not result.valid:
        raise ValueError(result.error or "invalid diagram xml")
    root = _parse_xml(result.xml)
    graph_root = _graph_root(root)
    return [_clone_cell(cell) for cell in graph_root.findall("mxCell") if cell.get("id") not in {"0", "1"}]


def _extract_appendable_cells(xml_or_fragment: str) -> list[ET.Element]:
    content = _strip_wrappers(xml_or_fragment)
    if not content:
        raise ValueError("fragment 不能为空")

    if "<mxfile" in content or "<mxGraphModel" in content or "<root" in content:
        return extract_mx_cells(content)

    if "<mxCell" not in content:
        raise ValueError("未检测到可追加的 mxCell")

    try:
        container = ET.fromstring(f"<fragment>{content}</fragment>")
    except ET.ParseError as exc:
        raise ValueError(f"mxCell fragment 不完整: {exc}") from exc

    cells: list[ET.Element] = []
    existing_ids: set[str] = set()
    for child in list(container):
        if child.tag != "mxCell":
            raise ValueError(f"unsupported fragment tag: {child.tag}")
        cell = _clone_cell(child)
        cell_id = cell.get("id")
        if not cell_id:
            cell_id = _new_cell_id(existing_ids)
            cell.set("id", cell_id)
        existing_ids.add(cell_id)
        if cell.get("id") not in {"0", "1"} and not cell.get("parent"):
            cell.set("parent", "1")
        cells.append(cell)
    return cells


def append_cells_to_xml(base_xml: str, fragment: str) -> DiagramXmlValidationResult:
    base_result = validate_and_fix_xml(base_xml, allow_fragment=False)
    if not base_result.valid:
        return base_result

    try:
        new_cells = _extract_appendable_cells(fragment)
    except ValueError as exc:
        return DiagramXmlValidationResult(valid=False, error=str(exc))

    root = _parse_xml(base_result.xml)
    graph_root = _graph_root(root)
    existing_ids = {cell.get("id") or "" for cell in graph_root.findall("mxCell")}
    renamed: dict[str, str] = {}

    for cell in new_cells:
        cell_id = cell.get("id") or ""
        if not cell_id or cell_id in existing_ids or cell_id in renamed.values():
            new_id = _new_cell_id(existing_ids | set(renamed.values()))
            if cell_id:
                renamed[cell_id] = new_id
            cell.set("id", new_id)
            existing_ids.add(new_id)
        else:
            existing_ids.add(cell_id)

    for cell in new_cells:
        for ref_attr in ("parent", "source", "target"):
            ref = cell.get(ref_attr)
            if ref in renamed:
                cell.set(ref_attr, renamed[ref])
        if cell.get("id") not in {"0", "1"} and not cell.get("parent"):
            cell.set("parent", "1")

    for cell in new_cells:
        graph_root.append(cell)

    return validate_and_fix_xml(ET.tostring(root, encoding="unicode"), allow_fragment=False)


def summarize_diagram_xml(xml: str) -> dict[str, int | str]:
    result = validate_and_fix_xml(xml, allow_fragment=False)
    if not result.valid:
        return {"nodes": 0, "edges": 0, "cells": 0, "summary": "无效图"}

    root = _parse_xml(result.xml)
    graph_root = _graph_root(root)
    cells = [cell for cell in graph_root.findall("mxCell") if cell.get("id") not in {"0", "1"}]
    nodes = sum(1 for cell in cells if cell.get("vertex") == "1")
    edges = sum(1 for cell in cells if cell.get("edge") == "1" or (cell.get("source") and cell.get("target")))
    summary = f"{nodes} nodes, {edges} edges, {len(cells)} cells"
    return {"nodes": nodes, "edges": edges, "cells": len(cells), "summary": summary}