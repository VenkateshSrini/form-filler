from __future__ import annotations

import json
from dataclasses import asdict

from core.models import FormField, FormLayout, FormRow, FormSection


def serialise_layout(layout: FormLayout) -> str:
    """Convert FormLayout to compact JSON string."""
    return json.dumps(asdict(layout), separators=(',', ':'))


def _field_from_dict(d: dict) -> FormField:
    return FormField(
        id=d["id"],
        label=d["label"],
        field_type=d["field_type"],
        page=d["page"],
        x0=d["x0"],
        top=d["top"],
        x1=d["x1"],
        bottom=d["bottom"],
        options=d.get("options", []),
        required=d.get("required", False),
        placeholder=d.get("placeholder", ""),
        # input_x0/input_y added in v2; old layouts default to x0/0.0 (safe fallback)
        input_x0=d.get("input_x0", d["x0"]),
        input_y=d.get("input_y", 0.0),
    )


def _row_from_dict(d: dict) -> FormRow:
    return FormRow(
        fields=[_field_from_dict(f) for f in d["fields"]],
        row_top=d["row_top"],
    )


def _section_from_dict(d: dict) -> FormSection:
    return FormSection(
        title=d["title"],
        rows=[_row_from_dict(r) for r in d["rows"]],
        page=d["page"],
    )


def deserialise_layout(json_str: str) -> FormLayout:
    """Reconstruct FormLayout from compact JSON string."""
    d: dict = json.loads(json_str)
    # page_dimensions was added later; JSON keys are always strings so coerce to int.
    raw_dims: dict = d.get("page_dimensions", {})
    page_dimensions: dict[int, tuple[float, float]] = {
        int(k): (float(v[0]), float(v[1])) for k, v in raw_dims.items()
    }
    return FormLayout(
        title=d["title"],
        source_file=d["source_file"],
        source_hash=d["source_hash"],
        page_count=d["page_count"],
        sections=[_section_from_dict(s) for s in d["sections"]],
        extracted_at=d["extracted_at"],
        page_dimensions=page_dimensions,
    )
