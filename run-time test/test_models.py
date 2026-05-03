"""
Runtime test: test_models.py
Tests all dataclass instantiation and property access for core/models.py
Run from project root: python "run-time test/test_models.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import (
    FormField,
    FormLayout,
    FormRow,
    FormSection,
    PageElements,
    WizardAction,
)


def test_form_field() -> None:
    f = FormField(
        id="p1_f0",
        label="Full Name",
        field_type="text",
        page=1,
        x0=50.0,
        top=100.0,
        x1=250.0,
        bottom=115.0,
        placeholder="Enter name",
    )
    assert f.width == 200.0, f"Expected 200.0, got {f.width}"
    assert f.height == 15.0, f"Expected 15.0, got {f.height}"
    assert f.center_y == 107.5, f"Expected 107.5, got {f.center_y}"
    print("✓ FormField properties OK")


def test_form_row() -> None:
    f1 = FormField(id="p1_f0", label="A", field_type="text", page=1,
                   x0=10.0, top=50.0, x1=100.0, bottom=65.0)
    f2 = FormField(id="p1_f1", label="B", field_type="text", page=1,
                   x0=120.0, top=50.0, x1=200.0, bottom=65.0)
    row = FormRow(fields=[f1, f2], row_top=50.0)
    assert len(row.fields) == 2
    print("✓ FormRow OK")


def test_form_section() -> None:
    f = FormField(id="p1_f0", label="X", field_type="checkbox", page=1,
                  x0=10.0, top=10.0, x1=20.0, bottom=20.0)
    row = FormRow(fields=[f], row_top=10.0)
    section = FormSection(title="Personal Info", rows=[row], page=1)
    assert section.title == "Personal Info"
    print("✓ FormSection OK")


def test_form_layout() -> None:
    layout = FormLayout(
        title="Test Form",
        source_file="test.pdf",
        source_hash="abc123",
        page_count=2,
        sections=[],
        extracted_at="2026-04-24T00:00:00+00:00",
    )
    assert layout.page_count == 2
    print("✓ FormLayout OK")


def test_page_elements() -> None:
    pe = PageElements(
        page_number=1,
        page_width=595.0,
        page_height=842.0,
        chars=[],
        words=[],
        lines=[],
        rects=[],
    )
    assert pe.page_height == 842.0
    print("✓ PageElements OK")


def test_wizard_action_enum() -> None:
    assert WizardAction.SAVE_ONLY.value == "save_only"
    assert WizardAction.GENERATE_ONLY.value == "generate_only"
    assert WizardAction.SAVE_AND_GENERATE.value == "save_and_generate"
    print("✓ WizardAction enum OK")


if __name__ == "__main__":
    test_form_field()
    test_form_row()
    test_form_section()
    test_form_layout()
    test_page_elements()
    test_wizard_action_enum()
    print("\nAll model tests passed.")
