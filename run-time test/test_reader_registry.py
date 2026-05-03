"""
Runtime test: test_reader_registry.py
Tests the reader factory registry — extension lookup, error on unknown ext.
Run from project root: python "run-time test/test_reader_registry.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.readers import READER_REGISTRY, get_document_reader


def test_pdf_registered() -> None:
    assert ".pdf" in READER_REGISTRY, "PDF reader must be registered"
    print(f"✓ Registered readers: {sorted(READER_REGISTRY.keys())}")


def test_get_document_reader_pdf() -> None:
    reader = get_document_reader(Path("some/form.pdf"))
    from core.readers.pdf.reader import PdfDocumentReader
    assert isinstance(reader, PdfDocumentReader)
    assert ".pdf" in reader.supported_extensions
    print("✓ get_document_reader returns PdfDocumentReader for .pdf")


def test_get_document_reader_unknown() -> None:
    try:
        get_document_reader(Path("some/file.xyz"))
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "No reader registered" in str(exc)
        print(f"✓ Unknown extension raises ValueError: {exc}")


def test_case_insensitive() -> None:
    reader_upper = get_document_reader(Path("form.PDF"))
    reader_lower = get_document_reader(Path("form.pdf"))
    assert type(reader_upper) is type(reader_lower)
    print("✓ Extension lookup is case-insensitive")


if __name__ == "__main__":
    test_pdf_registered()
    test_get_document_reader_pdf()
    test_get_document_reader_unknown()
    test_case_insensitive()
    print("\nAll reader registry tests passed.")
