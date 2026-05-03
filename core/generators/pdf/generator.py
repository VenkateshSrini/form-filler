from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path

import pypdf
from reportlab.pdfgen import canvas as rl_canvas

from core.generators.base import DocumentGenerator
from core.generators.factory import register_generator
from core.models import FormField, FormLayout

_FILL_FONT: str = "Helvetica"
_FILL_FONT_SIZE: int = 10
_TEXT_X_OFFSET: float = 3.0   # small padding after the inline label / from field edge
_TEXT_Y_OFFSET: float = 3.0   # lift text above an underline field
_RECT_FIELD_MIN_HEIGHT: float = 4.0
_CHECKBOX_TRUE_VALUES: frozenset[str] = frozenset({"true", "yes", "checked", "1"})


def _to_reportlab_y(field: FormField, page_height: float) -> float:
    """Convert pdfplumber top-origin y to reportlab bottom-origin y.

    Used only when no inline label was detected (field.input_y == 0).

    Three cases:
    • checkbox  → vertically centred inside the box.
    • rect field (height > threshold) → text baseline near the bottom of the rect.
    • line/underline field (height ≈ 0) → text baseline lifted slightly above the line.
    """
    if field.field_type == "checkbox":
        return page_height - field.top - field.height / 2

    if field.height > _RECT_FIELD_MIN_HEIGHT:
        return page_height - field.bottom + _TEXT_Y_OFFSET

    return page_height - field.top + _TEXT_Y_OFFSET


@register_generator
class PdfDocumentGenerator(DocumentGenerator):
    @property
    def supported_extension(self) -> str:
        return '.pdf'

    def generate_filled(
        self,
        layout: FormLayout,
        field_values: dict[str, str],
        source_dir: Path,
    ) -> bytes:
        """
        Returns bytes of the filled PDF.
        Raises FileNotFoundError if source PDF not found in source_dir.
        Purely in-memory — zero temp files.
        """
        pdf_path = source_dir / layout.source_file
        if not pdf_path.exists():
            raise FileNotFoundError(f"Original PDF not found: {pdf_path}")

        reader = pypdf.PdfReader(str(pdf_path))
        writer = pypdf.PdfWriter()

        # Build page → fields index
        fields_by_page: dict[int, list[FormField]] = defaultdict(list)
        for section in layout.sections:
            for row in section.rows:
                for f in row.fields:
                    fields_by_page[f.page].append(f)

        for page_num, page_obj in enumerate(reader.pages, start=1):
            # Use page dimensions from pdfplumber (captured at read time) so that
            # field coordinates and the overlay canvas share the same coordinate space.
            # Fall back to pypdf mediabox only for layouts stored before this change.
            if page_num in layout.page_dimensions:
                page_width, page_height = layout.page_dimensions[page_num]
            else:
                page_height = float(page_obj.mediabox.height)
                page_width = float(page_obj.mediabox.width)

            overlay_buf = io.BytesIO()
            c = rl_canvas.Canvas(overlay_buf, pagesize=(page_width, page_height))

            for field in fields_by_page.get(page_num, []):
                value = field_values.get(field.id, "").strip()
                if not value:
                    continue

                if field.field_type == "checkbox":
                    if value.lower() not in _CHECKBOX_TRUE_VALUES:
                        continue
                    # Draw bold "X" centred inside the checkbox rectangle
                    c.setFont("Helvetica-Bold", _FILL_FONT_SIZE)
                    rl_y = _to_reportlab_y(field, page_height)
                    cx = field.x0 + field.width / 2 - 3
                    c.drawString(cx, rl_y - _FILL_FONT_SIZE / 2 + 1, "X")
                else:
                    c.setFont(_FILL_FONT, _FILL_FONT_SIZE)
                    # X: write after the inline label when present, else at field edge
                    write_x = field.input_x0 + _TEXT_X_OFFSET
                    # Y: align to label word baseline when inline; else underline formula
                    if field.input_y > 0.0:
                        # input_y is pdfplumber `bottom` of the label word.
                        # reportlab draws text with baseline at y; bottom of a word ≈ baseline.
                        rl_y = page_height - field.input_y + 1.0
                    else:
                        rl_y = _to_reportlab_y(field, page_height)
                    c.drawString(write_x, rl_y, value)

            c.save()
            overlay_buf.seek(0)

            overlay_reader = pypdf.PdfReader(overlay_buf)
            page_obj.merge_page(overlay_reader.pages[0])
            writer.add_page(page_obj)

        output_buf = io.BytesIO()
        writer.write(output_buf)
        return output_buf.getvalue()
