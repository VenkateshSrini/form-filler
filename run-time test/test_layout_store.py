"""
Runtime test: test_layout_store.py
Tests round-trip serialise/deserialise of FormLayout.
Run from project root: python "run-time test/test_layout_store.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import FormField, FormLayout, FormRow, FormSection
from storage.layout_store import deserialise_layout, serialise_layout


def _make_layout() -> FormLayout:
    f1 = FormField(
        id="p1_f0", label="Full Name", field_type="text", page=1,
        x0=50.0, top=100.0, x1=250.0, bottom=115.0, placeholder="Enter name",
    )
    f2 = FormField(
        id="p1_f1", label="Date of Birth", field_type="date", page=1,
        x0=50.0, top=130.0, x1=200.0, bottom=145.0, placeholder="YYYY-MM-DD",
    )
    f3 = FormField(
        id="p1_f2", label="Agree", field_type="checkbox", page=1,
        x0=50.0, top=160.0, x1=65.0, bottom=175.0,
    )
    row1 = FormRow(fields=[f1, f2], row_top=100.0)
    row2 = FormRow(fields=[f3], row_top=160.0)
    section = FormSection(title="Personal Info", rows=[row1, row2], page=1)
    return FormLayout(
        title="Test Form",
        source_file="test.pdf",
        source_hash="deadbeef" * 8,
        page_count=1,
        sections=[section],
        extracted_at="2026-04-24T00:00:00+00:00",
    )


def test_round_trip() -> None:
    original = _make_layout()
    json_str = serialise_layout(original)
    assert isinstance(json_str, str), "serialise_layout must return a str"
    assert '"title"' in json_str, "JSON must contain title key"

    restored = deserialise_layout(json_str)
    assert restored.title == original.title
    assert restored.source_file == original.source_file
    assert restored.source_hash == original.source_hash
    assert restored.page_count == original.page_count
    assert restored.extracted_at == original.extracted_at
    assert len(restored.sections) == 1
    assert restored.sections[0].title == "Personal Info"
    assert len(restored.sections[0].rows) == 2
    assert len(restored.sections[0].rows[0].fields) == 2

    f_restored = restored.sections[0].rows[0].fields[0]
    assert f_restored.id == "p1_f0"
    assert f_restored.label == "Full Name"
    assert f_restored.field_type == "text"
    assert f_restored.placeholder == "Enter name"
    print("✓ Round-trip serialise/deserialise OK")


def test_compact_json() -> None:
    layout = _make_layout()
    json_str = serialise_layout(layout)
    assert " " not in json_str.split('"')[0], "JSON should be compact (no leading spaces)"
    assert ",'" not in json_str, "JSON should use double quotes"
    print("✓ Compact JSON format OK")


if __name__ == "__main__":
    test_round_trip()
    test_compact_json()
    print("\nAll layout store tests passed.")
