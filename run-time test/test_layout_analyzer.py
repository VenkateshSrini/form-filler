"""
Runtime test: test_layout_analyzer.py
Tests row grouping and section detection in layout_analyzer.py using synthetic data.
Run from project root: python "run-time test/test_layout_analyzer.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.layout_analyzer import build_layout
from core.models import FormField, PageElements


def _make_field(fid: str, page: int, top: float, x0: float = 50.0) -> FormField:
    return FormField(
        id=fid, label=f"Label {fid}", field_type="text", page=page,
        x0=x0, top=top, x1=x0 + 150.0, bottom=top + 15.0,
    )


def _make_page(page_num: int = 1) -> PageElements:
    return PageElements(
        page_number=page_num,
        page_width=595.0,
        page_height=842.0,
        chars=[{"text": "x", "x0": 10, "top": 10, "x1": 20, "bottom": 20,
                "size": 10.0, "fontname": "Helvetica"}],
        words=[],
        lines=[],
        rects=[],
    )


def test_row_grouping() -> None:
    """Fields within ROW_TOLERANCE_PT vertical distance → same row."""
    fields = [
        _make_field("p1_f0", page=1, top=100.0, x0=50.0),
        _make_field("p1_f1", page=1, top=105.0, x0=220.0),  # within 12pt → same row
        _make_field("p1_f2", page=1, top=130.0, x0=50.0),   # new row
    ]
    pages = [_make_page(1)]
    layout = build_layout(fields, pages, "test.pdf", "hash123")

    all_rows = [row for sec in layout.sections for row in sec.rows]
    # Should have at least 2 rows
    assert len(all_rows) >= 2, f"Expected >=2 rows, got {len(all_rows)}"
    # First row should have 2 fields (sorted by x0)
    first_row_field_count = sum(
        1 for row in all_rows if len(row.fields) == 2
    )
    assert first_row_field_count >= 1, "Expected at least one row with 2 fields"
    print(f"✓ Row grouping OK ({len(all_rows)} rows)")


def test_empty_fields() -> None:
    """No fields → empty layout with correct metadata."""
    pages = [_make_page(1)]
    layout = build_layout([], pages, "empty.pdf", "hash000")
    assert layout.source_file == "empty.pdf"
    assert layout.page_count == 1
    assert layout.sections == []
    print("✓ Empty fields → empty layout OK")


def test_layout_metadata() -> None:
    fields = [_make_field("p1_f0", page=1, top=100.0)]
    pages = [_make_page(1)]
    layout = build_layout(fields, pages, "myform.pdf", "sha256abc")
    assert layout.source_file == "myform.pdf"
    assert layout.source_hash == "sha256abc"
    assert layout.page_count == 1
    assert layout.extracted_at != ""
    print("✓ Layout metadata OK")


def test_multipage_fields() -> None:
    fields = [
        _make_field("p1_f0", page=1, top=100.0),
        _make_field("p2_f0", page=2, top=100.0),
    ]
    pages = [_make_page(1), _make_page(2)]
    layout = build_layout(fields, pages, "multi.pdf", "hash_multi")
    all_fields = [
        f for sec in layout.sections for row in sec.rows for f in row.fields
    ]
    assert len(all_fields) == 2, f"Expected 2 fields, got {len(all_fields)}"
    print("✓ Multi-page layout OK")


if __name__ == "__main__":
    test_row_grouping()
    test_empty_fields()
    test_layout_metadata()
    test_multipage_fields()
    print("\nAll layout analyzer tests passed.")
