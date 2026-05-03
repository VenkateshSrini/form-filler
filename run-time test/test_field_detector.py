"""
Runtime test: test_field_detector.py
Tests the 3-pass heuristic field detection logic using synthetic PageElements.
Run from project root: python "run-time test/test_field_detector.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.field_detector import detect_fields, _classify_field_type
from core.models import PageElements


def _make_page(
    lines: list[dict] | None = None,
    rects: list[dict] | None = None,
    words: list[dict] | None = None,
    chars: list[dict] | None = None,
) -> PageElements:
    return PageElements(
        page_number=1,
        page_width=595.0,
        page_height=842.0,
        chars=chars or [{"text": "x", "x0": 10, "top": 10, "x1": 20, "bottom": 20,
                          "size": 10.0, "fontname": "Helvetica"}],
        words=words or [],
        lines=lines or [],
        rects=rects or [],
    )


def test_line_creates_text_field() -> None:
    page = _make_page(
        lines=[{"x0": 50.0, "top": 100.0, "x1": 250.0, "bottom": 101.0, "linewidth": 1}],
        words=[{"text": "Name", "x0": 10.0, "top": 99.0, "x1": 45.0, "bottom": 109.0}],
    )
    fields = detect_fields([page])
    assert len(fields) >= 1, f"Expected at least 1 field, got {len(fields)}"
    assert fields[0].field_type == "text"
    print(f"✓ Line → text field (label='{fields[0].label}')")


def test_checkbox_rect() -> None:
    page = _make_page(
        rects=[{"x0": 50.0, "top": 100.0, "x1": 65.0, "bottom": 115.0, "fill": False}],
        words=[{"text": "Agree", "x0": 10.0, "top": 100.0, "x1": 45.0, "bottom": 112.0}],
    )
    fields = detect_fields([page])
    assert any(f.field_type == "checkbox" for f in fields), "Expected a checkbox field"
    print("✓ Small rect → checkbox field")


def test_textarea_rect() -> None:
    page = _make_page(
        rects=[{"x0": 50.0, "top": 100.0, "x1": 400.0, "bottom": 200.0, "fill": False}],
        words=[{"text": "Comments", "x0": 10.0, "top": 100.0, "x1": 48.0, "bottom": 112.0}],
    )
    fields = detect_fields([page])
    assert any(f.field_type == "textarea" for f in fields), "Expected a textarea field"
    print("✓ Tall rect → textarea field")


def test_date_classification() -> None:
    assert _classify_field_type("Date of Birth", False, False) == "date"
    assert _classify_field_type("DOB", False, False) == "date"
    assert _classify_field_type("birth date", False, False) == "date"
    print("✓ Date classification OK")


def test_number_classification() -> None:
    assert _classify_field_type("Total Amount", False, False) == "number"
    assert _classify_field_type("Salary", False, False) == "number"
    print("✓ Number classification OK")


def test_field_ids_unique() -> None:
    lines = [
        {"x0": 50.0, "top": float(100 + i * 30), "x1": 250.0, "bottom": float(101 + i * 30),
         "linewidth": 1}
        for i in range(5)
    ]
    page = _make_page(lines=lines)
    fields = detect_fields([page])
    ids = [f.id for f in fields]
    assert len(ids) == len(set(ids)), "Field IDs must be unique"
    print(f"✓ {len(fields)} fields with unique IDs")


def test_lru_cache_consistency() -> None:
    r1 = _classify_field_type("email address", False, False)
    r2 = _classify_field_type("email address", False, False)
    assert r1 == r2 == "text"
    print("✓ lru_cache returns consistent results")


if __name__ == "__main__":
    test_line_creates_text_field()
    test_checkbox_rect()
    test_textarea_rect()
    test_date_classification()
    test_number_classification()
    test_field_ids_unique()
    test_lru_cache_consistency()
    print("\nAll field detector tests passed.")
