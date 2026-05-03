from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterator

import pdfplumber

from core.models import MIN_INPUT_LINE_WIDTH_PT, MIN_TEXTAREA_HEIGHT_PT, PageElements
from core.readers.base import DocumentReader
from core.readers.factory import register_reader


def _extract_table_cells(
    page: object,
) -> list[tuple[float, float, float, float, bool]]:
    """
    Use pdfplumber's table finder to reconstruct input cells from grid lines.

    For each table:
    - Rows with multiple cells: every cell except the first (leftmost label)
      column is an input cell.
    - Rows with a single cell spanning the full row width: treated as a
      textarea when tall enough, ignored otherwise (e.g. header rows).

    Returns list of (x0, top, x1, bottom, is_textarea) tuples.
    """
    cells: list[tuple[float, float, float, float, bool]] = []
    for table in page.find_tables():
        for row in table.rows:
            non_none = [(ci, cell) for ci, cell in enumerate(row.cells) if cell is not None]
            if not non_none:
                continue
            if len(non_none) == 1:
                # Merged / full-width cell — include only if tall (textarea)
                _, cell = non_none[0]
                x0, top, x1, bot = cell
                if (x1 - x0) > MIN_INPUT_LINE_WIDTH_PT and (bot - top) >= MIN_TEXTAREA_HEIGHT_PT:
                    # Skip if the cell has text content (title/header row)
                    if not page.crop(cell).extract_words():
                        cells.append((float(x0), float(top), float(x1), float(bot), True))
            else:
                # First column is the label; all other columns are input cells.
                # Skip any cell that already contains text (column header rows).
                for ci, cell in non_none[1:]:
                    x0, top, x1, bot = cell
                    if page.crop(cell).extract_words():
                        continue  # header / label cell, not an input area
                    h = bot - top
                    is_textarea = h >= MIN_TEXTAREA_HEIGHT_PT
                    cells.append((float(x0), float(top), float(x1), float(bot), is_textarea))
    return cells


@register_reader
class PdfDocumentReader(DocumentReader):
    @property
    def supported_extensions(self) -> tuple[str, ...]:
        return ('.pdf',)

    def compute_hash(self, file_path: Path) -> str:
        return hashlib.sha256(file_path.read_bytes()).hexdigest()

    def parse(self, file_path: Path) -> Iterator[PageElements]:
        """
        Yields PageElements for each page.
        Raises ValueError if all pages are scanned (no chars on any page).
        """
        with pdfplumber.open(file_path) as pdf:
            all_scanned = True
            for i, page in enumerate(pdf.pages, start=1):
                elements = PageElements(
                    page_number=i,
                    page_width=float(page.width),
                    page_height=float(page.height),
                    chars=page.chars or [],
                    words=page.extract_words(x_tolerance=5, y_tolerance=3) or [],
                    lines=page.lines or [],
                    rects=page.rects or [],
                    table_cells=_extract_table_cells(page),
                )
                if elements.chars:
                    all_scanned = False
                yield elements
            if all_scanned:
                raise ValueError(
                    "This PDF appears to be scanned (no text characters found). "
                    "Only machine-generated PDFs are supported in this version."
                )
