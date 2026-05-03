from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.models import FormLayout


class DocumentGenerator(ABC):
    @property
    @abstractmethod
    def supported_extension(self) -> str:
        """The source extension this generator fills: '.pdf', '.docx', etc."""
        ...

    @abstractmethod
    def generate_filled(
        self,
        layout: FormLayout,
        field_values: dict[str, str],
        source_dir: Path,
    ) -> bytes:
        """Returns filled document bytes. Zero temp files."""
        ...
