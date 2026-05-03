from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator

from core.models import PageElements


class DocumentReader(ABC):
    @property
    @abstractmethod
    def supported_extensions(self) -> tuple[str, ...]:
        """e.g. ('.pdf',) or ('.docx', '.doc')"""
        ...

    @abstractmethod
    def compute_hash(self, file_path: Path) -> str:
        """Returns SHA-256 hex digest of file bytes."""
        ...

    @abstractmethod
    def parse(self, file_path: Path) -> Iterator[PageElements]:
        """Yields one PageElements per page/section."""
        ...
