"""
Runtime test: test_db.py
Tests MontyDB CRUD operations for layouts and submissions.
Run from project root: python "run-time test/test_db.py"

NOTE: Creates a temporary MontyDB in ./data/test_db — cleaned up after the test.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# Point to isolated test DB before importing storage modules
_TEST_DB_PATH = str(Path(__file__).parent.parent / "data" / "test_db")
os.environ["DB_TYPE"] = "montydb"
os.environ["DB_PATH"] = _TEST_DB_PATH
os.environ["DB_NAME"] = "formfiller_test"

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import FormField, FormLayout, FormRow, FormSection
from storage.db import (
    get_submission_by_tag,
    insert_submission,
    load_layout_by_id,
    save_layout,
    tag_exists,
    update_submission,
    get_all_submission_summaries,
)


def _make_layout() -> FormLayout:
    f = FormField(
        id="p1_f0", label="Full Name", field_type="text", page=1,
        x0=50.0, top=100.0, x1=250.0, bottom=115.0,
    )
    row = FormRow(fields=[f], row_top=100.0)
    section = FormSection(title="Personal", rows=[row], page=1)
    return FormLayout(
        title="Test Form",
        source_file="test.pdf",
        source_hash="abc123",
        page_count=1,
        sections=[section],
        extracted_at="2026-04-24T00:00:00+00:00",
    )


def test_save_and_load_layout() -> None:
    layout = _make_layout()
    layout_id = save_layout(layout)
    assert isinstance(layout_id, str) and len(layout_id) > 0, "layout_id must be a non-empty str"

    restored = load_layout_by_id(layout_id)
    assert restored.title == layout.title
    assert restored.source_file == layout.source_file
    print(f"✓ save_layout / load_layout_by_id OK (id={layout_id})")


def test_insert_and_get_submission() -> None:
    layout = _make_layout()
    layout_id = save_layout(layout)

    assert not tag_exists("test_user_001"), "Tag should not exist yet"

    insert_submission(
        tag="test_user_001",
        layout_id=layout_id,
        form_title=layout.title,
        source_file=layout.source_file,
        field_values={"p1_f0": "John Doe"},
        layout=layout,
    )

    assert tag_exists("test_user_001"), "Tag should exist after insert"

    doc = get_submission_by_tag("test_user_001")
    assert doc is not None
    assert doc["tag"] == "test_user_001"
    fields = {f["id"]: f["value"] for f in doc["fields"]}
    assert fields["p1_f0"] == "John Doe"
    print("✓ insert_submission / get_submission_by_tag OK")


def test_update_submission() -> None:
    doc_before = get_submission_by_tag("test_user_001")
    assert doc_before is not None

    update_submission("test_user_001", {"p1_f0": "Jane Smith"})

    doc_after = get_submission_by_tag("test_user_001")
    assert doc_after is not None
    fields = {f["id"]: f["value"] for f in doc_after["fields"]}
    assert fields["p1_f0"] == "Jane Smith", f"Expected 'Jane Smith', got {fields['p1_f0']}"
    print("✓ update_submission OK")


def test_get_all_summaries() -> None:
    summaries = get_all_submission_summaries()
    assert isinstance(summaries, list)
    assert len(summaries) >= 1
    # Summaries must NOT contain 'fields' (projection check)
    for s in summaries:
        assert "fields" not in s, "get_all_submission_summaries must not return fields array"
    print(f"✓ get_all_submission_summaries OK ({len(summaries)} record(s))")


def _cleanup() -> None:
    test_db_dir = Path(_TEST_DB_PATH)
    if test_db_dir.exists():
        shutil.rmtree(test_db_dir)
    print("✓ Test DB cleaned up")


if __name__ == "__main__":
    try:
        test_save_and_load_layout()
        test_insert_and_get_submission()
        test_update_submission()
        test_get_all_summaries()
        print("\nAll DB tests passed.")
    finally:
        _cleanup()
