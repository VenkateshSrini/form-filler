from __future__ import annotations

from pathlib import Path

from core.readers.base import DocumentReader

READER_REGISTRY: dict[str, type[DocumentReader]] = {}


def register_reader(cls: type[DocumentReader]) -> type[DocumentReader]:
    """Class decorator. Registers cls for each of its supported_extensions."""
    instance = cls()
    for ext in instance.supported_extensions:
        READER_REGISTRY[ext.lower()] = cls
    return cls


def get_document_reader(file_path: Path) -> DocumentReader:
    ext = file_path.suffix.lower()
    if ext not in READER_REGISTRY:
        raise ValueError(
            f"No reader registered for '{ext}'. Supported: {sorted(READER_REGISTRY)}"
        )
    return READER_REGISTRY[ext]()
