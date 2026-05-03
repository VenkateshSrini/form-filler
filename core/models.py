from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ── Constants ──────────────────────────────────────────────────────────────────
ROW_TOLERANCE_PT: int = 12
MIN_INPUT_LINE_WIDTH_PT: int = 40
CHECKBOX_MAX_SIZE_PT: int = 20
MIN_TEXTAREA_HEIGHT_PT: int = 40
FONT_SIZE_SECTION_DELTA: float = 2.0

FieldType = Literal["text", "checkbox", "date", "number", "textarea", "dropdown"]


@dataclass(slots=True)
class FormField:
    id: str
    label: str
    field_type: FieldType
    page: int
    x0: float
    top: float
    x1: float
    bottom: float
    options: list[str] = field(default_factory=list)
    required: bool = False
    placeholder: str = ""
    # Where to write the value.
    # input_x0: x start for writing; equals x0 when label is above/left (non-inline),
    #           equals label_word_x1 when label shares the same row (inline).
    # input_y:  pdfplumber `bottom` of the inline label word used as the y-anchor;
    #           0.0 means fall back to the underline-based formula.
    input_x0: float = 0.0
    input_y: float = 0.0

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass(slots=True)
class FormRow:
    fields: list[FormField]
    row_top: float


@dataclass(slots=True)
class FormSection:
    title: str
    rows: list[FormRow]
    page: int


@dataclass(slots=True)
class FormLayout:
    title: str
    source_file: str
    source_hash: str
    page_count: int
    sections: list[FormSection]
    extracted_at: str
    # Keyed by 1-based page number; values are (width, height) in pdfplumber points.
    # Captured at read time so the generator uses the same coordinate space.
    page_dimensions: dict[int, tuple[float, float]] = field(default_factory=dict)


@dataclass(slots=True)
class PageElements:
    page_number: int
    page_width: float
    page_height: float
    chars: list[dict]
    words: list[dict]
    lines: list[dict]
    rects: list[dict]
    # Input cells inferred from table grids: (x0, top, x1, bottom, is_textarea).
    # Populated by the reader; empty for forms with no table structure.
    table_cells: list[tuple[float, float, float, float, bool]] = field(default_factory=list)


class WizardAction(Enum):
    SAVE_ONLY = "save_only"
    GENERATE_ONLY = "generate_only"
    SAVE_AND_GENERATE = "save_and_generate"
