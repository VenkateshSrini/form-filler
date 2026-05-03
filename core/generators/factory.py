from __future__ import annotations

from pathlib import Path

from core.generators.base import DocumentGenerator

GENERATOR_REGISTRY: dict[str, type[DocumentGenerator]] = {}


def register_generator(cls: type[DocumentGenerator]) -> type[DocumentGenerator]:
    """Class decorator. Registers cls for its supported_extension."""
    instance = cls()
    GENERATOR_REGISTRY[instance.supported_extension.lower()] = cls
    return cls


def get_document_generator(source_file: Path) -> DocumentGenerator:
    ext = source_file.suffix.lower()
    if ext not in GENERATOR_REGISTRY:
        raise ValueError(
            f"No generator registered for '{ext}'. Supported: {sorted(GENERATOR_REGISTRY)}"
        )
    return GENERATOR_REGISTRY[ext]()
