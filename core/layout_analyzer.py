from __future__ import annotations

import re
from datetime import datetime, timezone
from statistics import mean

from core.models import (
    FONT_SIZE_SECTION_DELTA,
    ROW_TOLERANCE_PT,
    FormField,
    FormLayout,
    FormRow,
    FormSection,
    PageElements,
)

_RE_BOLD: re.Pattern[str] = re.compile(r'bold', re.IGNORECASE)


def _is_section_header(char: dict, avg_body_size: float) -> bool:
    """Return True if a char qualifies as a section header based on font size or bold."""
    size: float = float(char.get("size", 0.0))
    fontname: str = str(char.get("fontname", ""))
    return size > avg_body_size + FONT_SIZE_SECTION_DELTA or bool(_RE_BOLD.search(fontname))


def _avg_body_font_size(pages: list[PageElements]) -> float:
    """Compute mean font size across all chars in all pages."""
    sizes: list[float] = [
        float(ch.get("size", 0.0))
        for page in pages
        for ch in page.chars
        if float(ch.get("size", 0.0)) > 0
    ]
    return mean(sizes) if sizes else 10.0


def _extract_section_headers(
    pages: list[PageElements], avg_body_size: float
) -> list[tuple[int, float, str]]:
    """
    Return list of (page_number, top_coord, header_text) for all detected section headers.
    Aggregates consecutive header chars into words.
    """
    headers: list[tuple[int, float, str]] = []

    for page in pages:
        if not page.chars:
            continue

        current_word_chars: list[dict] = []

        for ch in page.chars:
            if _is_section_header(ch, avg_body_size):
                current_word_chars.append(ch)
            else:
                if current_word_chars:
                    text = "".join(c.get("text", "") for c in current_word_chars).strip()
                    if text:
                        top = float(min(c.get("top", 0.0) for c in current_word_chars))
                        headers.append((page.page_number, top, text))
                    current_word_chars = []

        if current_word_chars:
            text = "".join(c.get("text", "") for c in current_word_chars).strip()
            if text:
                top = float(min(c.get("top", 0.0) for c in current_word_chars))
                headers.append((page.page_number, top, text))

    return headers


def _group_fields_into_rows(fields: list[FormField]) -> list[FormRow]:
    """
    Group a sorted list of FormField into FormRow instances using ROW_TOLERANCE_PT.
    Input fields must already be sorted by (page, top, x0).
    """
    if not fields:
        return []

    rows: list[FormRow] = []
    current_row_fields: list[FormField] = [fields[0]]
    current_row_top: float = fields[0].top

    for f in fields[1:]:
        if f.top > current_row_top + ROW_TOLERANCE_PT:
            # Finalise current row
            sorted_row = sorted(current_row_fields, key=lambda ff: ff.x0)
            rows.append(FormRow(
                fields=sorted_row,
                row_top=min(ff.top for ff in sorted_row),
            ))
            current_row_fields = [f]
            current_row_top = f.top
        else:
            current_row_fields.append(f)

    # Flush last row
    sorted_row = sorted(current_row_fields, key=lambda ff: ff.x0)
    rows.append(FormRow(
        fields=sorted_row,
        row_top=min(ff.top for ff in sorted_row),
    ))

    return rows


def build_layout(
    fields: list[FormField],
    pages: list[PageElements],
    source_file_name: str,
    source_hash: str,
) -> FormLayout:
    """
    Organise flat list of FormField into FormLayout with FormSection → FormRow hierarchy.
    """
    # Sort all fields by (page, top, x0)
    sorted_fields: list[FormField] = sorted(fields, key=lambda f: (f.page, f.top, f.x0))

    avg_body_size: float = _avg_body_font_size(pages)
    section_headers: list[tuple[int, float, str]] = _extract_section_headers(pages, avg_body_size)

    # Assign each field to a section based on header boundaries
    # section_headers sorted by (page, top)
    sorted_headers = sorted(section_headers, key=lambda h: (h[0], h[1]))

    def _get_section_title_for_field(f: FormField) -> str:
        """Return the title of the most recent header before this field's (page, top)."""
        title = ""
        for h_page, h_top, h_text in sorted_headers:
            if (h_page, h_top) <= (f.page, f.top):
                title = h_text
            else:
                break
        return title

    if not sorted_fields:
        # No fields: return empty layout
        from pathlib import Path
        doc_stem = Path(source_file_name).stem
        return FormLayout(
            title=doc_stem,
            source_file=source_file_name,
            source_hash=source_hash,
            page_count=len(pages),
            sections=[],
            extracted_at=datetime.now(timezone.utc).isoformat(),
            page_dimensions={p.page_number: (p.page_width, p.page_height) for p in pages},
        )

    # Group fields by section title
    from collections import OrderedDict
    # Use insertion-ordered dict: key = (section_title, page_of_first_field_in_section)
    section_buckets: dict[tuple[str, int], list[FormField]] = OrderedDict()

    for f in sorted_fields:
        sec_title = _get_section_title_for_field(f)
        # Each section is keyed by title + first page it appears on (handles repeated titles)
        key = (sec_title, f.page if not any(k[0] == sec_title for k in section_buckets) else
               next(k[1] for k in section_buckets if k[0] == sec_title))
        if key not in section_buckets:
            section_buckets[key] = []
        section_buckets[key].append(f)

    from pathlib import Path as _Path
    doc_stem = _Path(source_file_name).stem
    first_title = sorted_headers[0][2] if sorted_headers else doc_stem

    sections: list[FormSection] = []
    for (sec_title, sec_page), sec_fields in section_buckets.items():
        rows = _group_fields_into_rows(sec_fields)
        display_title = sec_title if sec_title else doc_stem
        sections.append(FormSection(
            title=display_title,
            rows=rows,
            page=sec_page,
        ))

    layout_title = first_title if first_title else doc_stem

    page_dimensions: dict[int, tuple[float, float]] = {
        p.page_number: (p.page_width, p.page_height) for p in pages
    }

    return FormLayout(
        title=layout_title,
        source_file=source_file_name,
        source_hash=source_hash,
        page_count=len(pages),
        sections=sections,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        page_dimensions=page_dimensions,
    )
