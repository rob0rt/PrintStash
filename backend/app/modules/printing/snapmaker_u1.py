"""Snapmaker U1-specific filament metadata and validated tool mapping.

Uses the existing Moonraker transport; this module has no printer I/O.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

_TOOL = re.compile(r"^\s*T(\d{1,2})\s*(?:;.*)?$", re.IGNORECASE)
_HEADER = re.compile(r"^\s*;\s*(filament_type|filament_colou?r|filament_used_g)\s*=\s*(.+)$", re.IGNORECASE)
_COLOR = re.compile(r"^#?[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


def color_hex(value: object) -> str | None:
    if not isinstance(value, str) or not _COLOR.fullmatch(value.strip()):
        return None
    return "#" + value.strip().lstrip("#")[:6].upper()


def _field(values: object, index: int) -> str | None:
    if not isinstance(values, list) or index >= len(values):
        return None
    value = values[index]
    return value.strip() if isinstance(value, str) and value.strip() else None


def loaded_slots(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    status = response.get("result")
    config = status.get("status") if isinstance(status, dict) else None
    config = config.get("print_task_config") if isinstance(config, dict) else None
    if not isinstance(config, dict):
        raise ValueError("snapmaker_u1_state_unavailable")
    present = config.get("filament_exist")
    if not isinstance(present, list) or len(present) < 4 or not all(type(x) is bool for x in present[:4]):
        raise ValueError("snapmaker_u1_state_unavailable")
    return [
        {
            "index": i,
            "present": present[i],
            "material": _field(config.get("filament_type"), i),
            "subtype": _field(config.get("filament_sub_type"), i),
            "vendor": _field(config.get("filament_vendor"), i),
            "color": color_hex(_field(config.get("filament_color_rgba"), i)),
        }
        for i in range(4)
    ]


def logical_filaments(lines: Iterable[str]) -> list[dict[str, Any]]:
    tools: set[int] = set()
    headers: dict[str, list[str]] = {}
    for line in lines:
        tool = _TOOL.match(line)
        if tool:
            index = int(tool.group(1))
            if index > 31:
                raise ValueError("snapmaker_u1_invalid_tool")
            tools.add(index)
        header = _HEADER.match(line)
        if header:
            headers[header.group(1).lower()] = [x.strip() for x in re.split(r"\s*[,;]\s*", header.group(2))]
    if not tools:
        # Single-filament slicer output may omit an explicit T0.
        if len(headers.get("filament_type", [])) == 1:
            tools.add(0)
        else:
            raise ValueError("snapmaker_u1_tools_unknown")
    if len(tools) > 4:
        raise ValueError("snapmaker_u1_too_many_filaments")
    colors = headers.get("filament_colour", headers.get("filament_color", []))
    weights = headers.get("filament_used_g", [])
    result = []
    for index in sorted(tools):
        weight = None
        if index < len(weights):
            try:
                weight = float(weights[index])
            except ValueError:
                pass
        result.append({
            "index": index,
            "material": _field(headers.get("filament_type"), index),
            "color": color_hex(colors[index]) if index < len(colors) else None,
            "grams": weight,
        })
    return result


def file_filaments(file_row: Any, backend: Any) -> list[dict[str, Any]]:
    """Parse the actual authorized vault G-code, including large streamed files."""
    from app.modules.storage.artifact_content import resolve

    with resolve(file_row, backend=backend).materialize() as local:
        with open(local, encoding="utf-8", errors="replace") as handle:
            return logical_filaments(handle)


def _base_material(value: str | None) -> str | None:
    if not value:
        return None
    return re.split(r"[\s_-]", value.upper(), maxsplit=1)[0]


def validate_mapping(
    filaments: list[dict[str, Any]],
    slots: list[dict[str, Any]],
    mapping: list[tuple[int, int]],
    *,
    allow_material_mismatch: bool,
) -> None:
    if len(mapping) != len(filaments) or {a for a, _ in mapping} != {f["index"] for f in filaments}:
        raise ValueError("snapmaker_u1_mapping_incomplete")
    heads = [b for _, b in mapping]
    if len(set(heads)) != len(heads) or any(type(b) is not int or not 0 <= b < 4 for b in heads):
        raise ValueError("snapmaker_u1_mapping_invalid")
    slot_by_id = {slot["index"]: slot for slot in slots}
    fil_by_id = {f["index"]: f for f in filaments}
    for tool, head in mapping:
        slot = slot_by_id[head]
        if not slot["present"]:
            raise ValueError("snapmaker_u1_head_empty")
        expected = _base_material(fil_by_id[tool]["material"])
        actual = _base_material(slot["material"])
        if expected and actual and expected != actual and not allow_material_mismatch:
            raise ValueError("snapmaker_u1_material_mismatch")
