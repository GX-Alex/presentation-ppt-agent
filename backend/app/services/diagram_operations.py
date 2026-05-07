from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

from app.services.diagram_xml_validator import _graph_root, validate_and_fix_xml


@dataclass
class DiagramOperation:
    action: str
    cell_id: str | None = None
    parent_id: str | None = None
    cell_xml: str | None = None
    cell: dict[str, Any] | None = None
    value: str | None = None
    style: str | None = None
    geometry: dict[str, Any] | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagramOperationApplyResult:
    success: bool
    xml: str
    operations_applied: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _find_cell(root: ET.Element, cell_id: str) -> ET.Element | None:
    for cell in root.findall("mxCell"):
        if cell.get("id") == cell_id:
            return cell
    return None


def _build_cell_from_payload(operation: DiagramOperation) -> ET.Element:
    if operation.cell_xml:
        try:
            cell = ET.fromstring(operation.cell_xml)
        except ET.ParseError as exc:
            raise ValueError(f"cell_xml 解析失败: {exc}") from exc
        if cell.tag != "mxCell":
            raise ValueError("cell_xml 必须以 <mxCell> 作为根节点")
        return cell

    payload = dict(operation.cell or {})
    attrs: dict[str, str] = {}
    for key in ("id", "value", "style", "vertex", "edge", "parent", "source", "target"):
        value = payload.get(key)
        if value is not None:
            attrs[key] = str(value)

    attrs["id"] = attrs.get("id") or f"cell_{uuid.uuid4().hex[:8]}"
    if operation.parent_id and not attrs.get("parent"):
        attrs["parent"] = operation.parent_id
    if not attrs.get("parent") and attrs.get("id") not in {"0", "1"}:
        attrs["parent"] = "1"

    cell = ET.Element("mxCell", attrs)
    geometry = operation.geometry or payload.get("geometry")
    if geometry:
        ET.SubElement(
            cell,
            "mxGeometry",
            {**{k: str(v) for k, v in geometry.items()}, "as": str(geometry.get("as", "geometry"))},
        )
    elif attrs.get("vertex") == "1":
        ET.SubElement(cell, "mxGeometry", {"x": "0", "y": "0", "width": "120", "height": "60", "as": "geometry"})
    return cell


def _set_geometry(cell: ET.Element, geometry_payload: dict[str, Any]) -> None:
    geometry = cell.find("mxGeometry")
    if geometry is None:
        geometry = ET.SubElement(cell, "mxGeometry", {"as": "geometry"})
    for key, value in geometry_payload.items():
        geometry.set(key, str(value))
    if geometry.get("as") is None:
        geometry.set("as", "geometry")


def _ensure_safe_delete(root: ET.Element, cell_id: str) -> str | None:
    for cell in root.findall("mxCell"):
        if cell.get("parent") == cell_id or cell.get("source") == cell_id or cell.get("target") == cell_id:
            return f"cell {cell_id} 仍被其他节点引用，不能删除"
    return None


def apply_diagram_operations(xml: str, operations: list[dict[str, Any] | DiagramOperation]) -> DiagramOperationApplyResult:
    base_result = validate_and_fix_xml(xml, allow_fragment=False)
    if not base_result.valid:
        return DiagramOperationApplyResult(success=False, xml=xml, errors=[base_result.error or "无效图"])

    tree_root = ET.fromstring(base_result.xml)
    graph_root = _graph_root(tree_root)
    normalized_operations = [op if isinstance(op, DiagramOperation) else DiagramOperation(**op) for op in operations]

    applied = 0
    for operation in normalized_operations:
        action = operation.action
        if action not in {"add", "update", "delete"}:
            return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"不支持的操作: {action}"])

        if action == "add":
            try:
                cell = _build_cell_from_payload(operation)
            except ValueError as exc:
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[str(exc)])

            cell_id = cell.get("id") or ""
            if _find_cell(graph_root, cell_id) is not None:
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"cell {cell_id} 已存在"])

            parent_id = cell.get("parent") or operation.parent_id or "1"
            if _find_cell(graph_root, parent_id) is None and parent_id != "1":
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"parent {parent_id} 不存在"])
            cell.set("parent", parent_id)

            for ref_attr in ("source", "target"):
                ref = cell.get(ref_attr)
                if ref and _find_cell(graph_root, ref) is None:
                    return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"{ref_attr} {ref} 不存在"])

            graph_root.append(cell)
            applied += 1
            continue

        if not operation.cell_id:
            return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"{action} 操作缺少 cell_id"])

        cell = _find_cell(graph_root, operation.cell_id)
        if cell is None:
            return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"cell {operation.cell_id} 不存在"])

        if action == "delete":
            if operation.cell_id in {"0", "1"}:
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=["根节点不能删除"])
            delete_error = _ensure_safe_delete(graph_root, operation.cell_id)
            if delete_error:
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[delete_error])
            graph_root.remove(cell)
            applied += 1
            continue

        if operation.value is not None:
            cell.set("value", operation.value)
        if operation.style is not None:
            cell.set("style", operation.style)
        if operation.parent_id is not None:
            if operation.parent_id not in {c.get("id") or "" for c in graph_root.findall("mxCell")}:
                return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[f"parent {operation.parent_id} 不存在"])
            cell.set("parent", operation.parent_id)
        if operation.geometry:
            _set_geometry(cell, operation.geometry)
        for attr_name, attr_value in operation.attributes.items():
            if attr_value is None:
                cell.attrib.pop(attr_name, None)
            else:
                cell.set(attr_name, str(attr_value))
        applied += 1

    final_result = validate_and_fix_xml(ET.tostring(tree_root, encoding="unicode"), allow_fragment=False)
    if not final_result.valid:
        return DiagramOperationApplyResult(success=False, xml=base_result.xml, errors=[final_result.error or "更新后 XML 无效"])

    return DiagramOperationApplyResult(
        success=True,
        xml=final_result.xml,
        operations_applied=applied,
        warnings=final_result.warnings,
    )