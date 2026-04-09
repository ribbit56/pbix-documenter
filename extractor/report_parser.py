"""
Parses Report/Layout JSON to determine which measures appear in which visuals.
Populates Measure.used_in_visuals for each measure found.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from models.schema import SemanticModel


def parse(report_layout_bytes: bytes | None, model: SemanticModel) -> SemanticModel:
    """
    Walk the report layout and populate Measure.used_in_visuals.
    Accepts raw bytes (read directly from the .pbix ZIP).
    Returns the model (mutated in-place).
    """
    if not report_layout_bytes:
        return model

    raw = report_layout_bytes
    # Report/Layout is UTF-16 LE in most .pbix files
    try:
        text = raw.decode("utf-16-le")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            return model

    try:
        layout = json.loads(text)
    except json.JSONDecodeError:
        return model

    # Build a lookup: measure name (lower) -> Measure object
    measure_map: dict[str, object] = {}
    for table in model.tables:
        for measure in table.measures:
            measure_map[measure.name.lower()] = measure

    sections = layout.get("sections", [])
    for section in sections:
        page_name = section.get("displayName", section.get("name", "unknown page"))
        for visual_container in section.get("visualContainers", []):
            config_str = visual_container.get("config", "{}")
            if isinstance(config_str, str):
                try:
                    config = json.loads(config_str)
                except json.JSONDecodeError:
                    config = {}
            else:
                config = config_str

            visual_name = _get_visual_name(config, visual_container)
            _walk_for_measures(config, measure_map, f"{page_name} / {visual_name}")

            # Also check dataTransforms and query fields
            for field_name in ("dataTransforms", "query", "filters"):
                field_val = visual_container.get(field_name, "{}")
                if isinstance(field_val, str):
                    try:
                        field_data = json.loads(field_val)
                    except json.JSONDecodeError:
                        field_data = {}
                else:
                    field_data = field_val
                _walk_for_measures(field_data, measure_map, f"{page_name} / {visual_name}")

    model.report_parsed = True
    return model


def _get_visual_name(config: dict, container: dict) -> str:
    title = (
        config.get("name")
        or config.get("singleVisual", {}).get("visualType", "")
        or container.get("config", "")[:30]
    )
    return str(title) if title else "visual"


def _walk_for_measures(
    obj,
    measure_map: dict[str, object],
    visual_label: str,
    _depth: int = 0,
) -> None:
    """Recursively walk a JSON object looking for measure name references."""
    if _depth > 15:
        return
    if isinstance(obj, dict):
        # Look for queryRef or Measure patterns in the keys/values
        for key, value in obj.items():
            if key in ("queryRef", "Name", "measureDisplayName", "Column") and isinstance(value, str):
                _try_register(value, measure_map, visual_label)
            else:
                _walk_for_measures(value, measure_map, visual_label, _depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            _walk_for_measures(item, measure_map, visual_label, _depth + 1)
    elif isinstance(obj, str):
        # Try to match patterns like [MeasureName] or Table.[MeasureName]
        for m in re.finditer(r"\[([^\]]+)\]", obj):
            _try_register(m.group(1), measure_map, visual_label)


def _try_register(name: str, measure_map: dict, visual_label: str) -> None:
    key = name.lower().strip()
    if key in measure_map:
        measure = measure_map[key]
        if visual_label not in measure.used_in_visuals:
            measure.used_in_visuals.append(visual_label)
