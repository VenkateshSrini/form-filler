"""
Runtime test: test_generator_registry.py
Tests the generator factory registry.
Run from project root: python "run-time test/test_generator_registry.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.generators import GENERATOR_REGISTRY, get_document_generator


def test_pdf_registered() -> None:
    assert ".pdf" in GENERATOR_REGISTRY, "PDF generator must be registered"
    print(f"✓ Registered generators: {sorted(GENERATOR_REGISTRY.keys())}")


def test_get_document_generator_pdf() -> None:
    gen = get_document_generator(Path("some/form.pdf"))
    from core.generators.pdf.generator import PdfDocumentGenerator
    assert isinstance(gen, PdfDocumentGenerator)
    assert gen.supported_extension == ".pdf"
    print("✓ get_document_generator returns PdfDocumentGenerator for .pdf")


def test_get_document_generator_unknown() -> None:
    try:
        get_document_generator(Path("some/file.xyz"))
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "No generator registered" in str(exc)
        print(f"✓ Unknown extension raises ValueError: {exc}")


def test_case_insensitive() -> None:
    gen_upper = get_document_generator(Path("form.PDF"))
    gen_lower = get_document_generator(Path("form.pdf"))
    assert type(gen_upper) is type(gen_lower)
    print("✓ Generator extension lookup is case-insensitive")


if __name__ == "__main__":
    test_pdf_registered()
    test_get_document_generator_pdf()
    test_get_document_generator_unknown()
    test_case_insensitive()
    print("\nAll generator registry tests passed.")
