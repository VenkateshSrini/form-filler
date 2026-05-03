# PDF Form Filler — Code Generation Plan

> **Purpose:** This document is a complete, self-contained specification for generating production-ready Python code. It is written to be handed to a code-generation session (LLM or otherwise) with no prior context. Every architectural decision, data model, UI flow, DB schema, and implementation detail is captured here.

---

## System Prompt for Code Generation

When generating code from this plan, apply these mandates without exception:

1. **Language / runtime:** Python 3.10+. Use `from __future__ import annotations` at the top of every file.
2. **Dataclasses:** Use `@dataclass(slots=True)` on every model class. Never use plain dicts or namedtuples for domain objects.
3. **Type hints:** Every function signature must be fully type-annotated. Return type always explicit.
4. **Imports:** All imports at module top. Never import inside a function body.
5. **Path handling:** `pathlib.Path` everywhere. Never `os.path` or string concatenation for paths.
6. **File handles:** Always use context managers (`with` blocks). No bare `open()` calls.
7. **JSON storage:** `json.dumps(obj, separators=(',', ':'))` (compact, no whitespace) for all DB storage.
8. **Generators:** Use generator expressions for iteration pipelines; only materialise into `list()` when length or random access is needed.
9. **Caching:** `@functools.lru_cache` on any pure, deterministic function (same input always yields same output).
10. **Constants:** Module-level `SCREAMING_SNAKE_CASE` for all magic numbers and strings.
11. **String building in loops:** `"".join(parts)` — never `result += fragment`.
12. **KISS:** No class hierarchies for single-responsibility operations. Prefer module-level functions.
13. **DRY:** Identify every operation that is called from more than one place. Extract to a single private helper (`_name()`). Never copy-paste logic.
14. **Memory:** In-memory buffers (`io.BytesIO`) for PDF operations. Zero temp files.
15. **Security:** No eval/exec on user data. No dynamic SQL. No shell injection. Validate all user inputs at UI boundary before they reach business logic.
16. **LLM integration is opt-in and isolated:** LLM calls are confined to `core/llm/`. The rest of the pipeline (reader, generator, storage, UI) must remain LLM-free. The heuristic pipeline in `core/field_detector.py` is always executed first; LLM enrichment is a post-processing step that operates on the heuristic output.

---

## 1. Project Overview

### What It Does

A local desktop web app (Gradio) that:
1. Reads visual (non-interactive) PDF forms from a local `input-forms/` directory.
2. Extracts form fields and their layout using heuristic analysis (pdfplumber).
3. Renders an equivalent web form in Gradio that mirrors the PDF layout.
4. Saves filled form data to a local NoSQL database (MontyDB, MongoDB-compatible).
5. Can regenerate a filled PDF by overlaying submitted values onto the original PDF pages.
6. Supports editing previously saved submissions and retrieving them by a user-defined tag.

### What It Does NOT Do (Phase 1 Scope Boundary)

- No scanned/OCR PDFs (only machine-generated PDFs with text characters).
- No browser-based PDF upload (PDFs must be pre-placed in `input-forms/`).
- No scanned/OCR PDFs (only machine-generated PDFs with text characters).
- LLM field enrichment is Phase 2 (documented in Section 17). Phase 1 heuristic pipeline remains fully functional without an API key.
- No multi-user / concurrent access (MontyDB is not process-safe).
- No delete/list-all-layouts UI.
- No Azure / MAF infrastructure dependency.
- No authentication.

---

## 2. Technology Stack

### Libraries and Exact Versions

| Package | Version | License | Purpose |
|---|---|---|---|
| `pdfplumber` | `==0.11.9` | MIT | PDF parsing: chars, lines, rects, words with (x0, top, x1, bottom) coords |
| `gradio` | `==6.13.0` | Apache 2.0 | Web UI framework. Python 3.10+ required |
| `montydb` | `>=2.5.2` | BSD-3-Clause | Local embedded MongoDB-compatible DB (SQLite engine, Windows-safe) |
| `pymongo` | `>=4.6` | Apache 2.0 | BSON support for MontyDB + production MongoDB client |
| `reportlab` | `>=4.2` | BSD | PDF overlay canvas generation |
| `pypdf` | `>=4.3` | BSD | PDF page merging / overlay stamping |
| `python-dotenv` | `==1.0.1` | BSD | `.env` file loading |
| `openai` | `>=1.30` | MIT | LLM API client — provider-agnostic (works with OpenAI, Azure OpenAI, or any OpenAI-compatible endpoint via `base_url` + `api_key` env vars) |

### Why These Choices

- **pdfplumber over PyMuPDF:** PyMuPDF is AGPL-licensed (incompatible with free commercial use). pdfplumber (MIT) provides identical low-level access to chars, lines, and rectangles.
- **MontyDB over mongita:** mongita explicitly documents Windows test failures in its own contributing notes. MontyDB uses SQLite as its storage engine and is confirmed Windows-safe.
- **MontyDB over SQLite directly:** The MontyDB API is a subset of PyMongo's `MongoClient` API. Switching to production MongoDB requires only changing an env var — zero application code change.
- **pypdf + reportlab over PDFKit/WeasyPrint:** The fill operation is a lightweight text overlay on existing pages. pypdf stamps the reportlab canvas onto original PDF pages without rerendering or reflowing — pixel-perfect positioning.
- **gradio `@gr.render` over tabs/static layout:** Form fields are unknown until runtime (they come from the parsed PDF). `@gr.render` creates Gradio components dynamically based on state, which is the correct Gradio pattern for this use case.
- **`gr.Column(visible=)` for screen navigation over `gr.Modal`:** Modals dismiss on action and cannot host a file download widget cleanly. Inline column visibility toggling is idiomatic Gradio for multi-step flows.
- **`openai` SDK over Anthropic SDK or Azure AI Foundry (MAF):** This is a standalone local desktop app with no Azure infrastructure dependency. The `openai` Python SDK is provider-agnostic — the same code works with OpenAI, Azure OpenAI, or any OpenAI-compatible endpoint (local models via Ollama/LM Studio, etc.) by changing only env vars. The Anthropic SDK is single-provider and would lock the codebase to Claude. MAF adds an entire Azure deployment layer (resource groups, managed identities, deployment names) that brings zero benefit for a local app.

---

## 3. Project Structure

```
form-filler/
├── app.py                        # Gradio Blocks entry point; wires all screens and handlers
├── core/
│   ├── __init__.py
│   ├── models.py                 # All @dataclass(slots=True) domain models + WizardAction enum + PageElements
│   ├── field_detector.py         # 3-pass heuristic: structural → label → type classification
│   ├── layout_analyzer.py        # Row grouping + section detection
│   ├── llm/
│   │   ├── __init__.py           # exports enrich_fields_with_llm()
│   │   └── enricher.py           # LLM post-processing: re-labels + types fields using OpenAI SDK
│   ├── readers/
│   │   ├── __init__.py           # exports get_document_reader, READER_REGISTRY; triggers pdf registration
│   │   ├── base.py               # DocumentReader ABC
│   │   ├── factory.py            # READER_REGISTRY dict + get_document_reader() + @register_reader
│   │   └── pdf/                  # all PDF reading logic isolated here
│   │       ├── __init__.py       # triggers @register_reader on import
│   │       └── reader.py         # PdfDocumentReader — all pdfplumber logic
│   └── generators/
│       ├── __init__.py           # exports get_document_generator; triggers pdf registration
│       ├── base.py               # DocumentGenerator ABC
│       ├── factory.py            # GENERATOR_REGISTRY dict + get_document_generator() + @register_generator
│       └── pdf/                  # all PDF generation logic isolated here
│           ├── __init__.py       # triggers @register_generator on import
│           └── generator.py      # PdfDocumentGenerator — all reportlab+pypdf logic
├── storage/
│   ├── __init__.py
│   ├── db.py                     # DB client factory; all CRUD operations for both collections
│   └── layout_store.py           # FormLayout ↔ compact JSON serialisation / deserialisation
├── ui/
│   ├── __init__.py
│   └── form_builder.py           # build_field_component(); @gr.render dynamic form; wizard panel
├── input-forms/                  # Source documents (scanned by app on startup + refresh)
├── data/                         # MontyDB SQLite files (must be in .gitignore)
├── .env.example                  # Template for environment configuration
├── .gitignore
└── requirements.txt
```

### Adding a New Document Type (e.g., Word)

Adding `.docx` support is **purely additive** — no existing files are modified:

```
core/readers/docx/
├── __init__.py    # from core.readers.docx import reader  (triggers @register_reader)
└── reader.py      # DocxDocumentReader with @register_reader

core/generators/docx/
├── __init__.py    # from core.generators.docx import generator  (triggers @register_generator)
└── generator.py   # DocxDocumentGenerator with @register_generator
```

Then add **one line** each to `core/readers/__init__.py` and `core/generators/__init__.py`:

```python
from core.readers import docx     # registers DocxDocumentReader
from core.generators import docx  # registers DocxDocumentGenerator
```

No other files touched. The registry enforces Open/Closed Principle.

---

## 4. Data Models (`core/models.py`)

### Full Implementation Spec

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal


# ── Constants ──────────────────────────────────────────────────────────────────
ROW_TOLERANCE_PT: int = 12          # fields within 12pt vertical band → same row
MIN_INPUT_LINE_WIDTH_PT: int = 40   # horizontal line must be >40pt to be a field candidate
CHECKBOX_MAX_SIZE_PT: int = 20      # rect ≤ 20pt in both dims → checkbox candidate
MIN_TEXTAREA_HEIGHT_PT: int = 40    # rect taller than 40pt → textarea
FONT_SIZE_SECTION_DELTA: float = 2.0  # font > avg_body + 2pt → section header

FieldType = Literal["text", "checkbox", "date", "number", "textarea", "dropdown"]


@dataclass(slots=True)
class FormField:
    id: str            # unique: "p{page}_f{index}" e.g. "p1_f0"
    label: str         # nearest qualifying text block
    field_type: FieldType
    page: int          # 1-based page number
    x0: float          # pdfplumber coordinate: left edge
    top: float         # pdfplumber coordinate: distance from top of page
    x1: float          # pdfplumber coordinate: right edge
    bottom: float      # pdfplumber coordinate: distance from top of page
    options: list[str] = field(default_factory=list)   # for dropdown / checkbox group
    required: bool = False
    placeholder: str = ""

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
    fields: list[FormField]   # sorted by x0 (left to right)
    row_top: float            # top coordinate of the topmost field in this row


@dataclass(slots=True)
class FormSection:
    title: str
    rows: list[FormRow]
    page: int


@dataclass(slots=True)
class FormLayout:
    title: str
    source_file: str       # original filename (no path) e.g. "application.pdf" or "application.docx"
    source_hash: str       # SHA-256 hex of the document bytes
    page_count: int
    sections: list[FormSection]
    extracted_at: str      # ISO 8601 UTC timestamp


@dataclass(slots=True)
class PageElements:
    page_number: int       # 1-based
    page_width: float
    page_height: float
    chars: list[dict]      # pdfplumber char dicts: {text, x0, top, x1, bottom, size, fontname}
    words: list[dict]      # pdfplumber word dicts: {text, x0, top, x1, bottom}
    lines: list[dict]      # pdfplumber line dicts: {x0, top, x1, bottom, linewidth}
    rects: list[dict]      # pdfplumber rect dicts: {x0, top, x1, bottom, fill}


class WizardAction(Enum):
    SAVE_ONLY = "save_only"
    GENERATE_ONLY = "generate_only"
    SAVE_AND_GENERATE = "save_and_generate"
```

### Design Notes

- `slots=True` prevents `__dict__` creation per instance — ~20% memory reduction and faster attribute access via C-level slot descriptors.
- `from __future__ import annotations` defers annotation evaluation — no runtime cost for type strings.
- `FormField.id` format `"p{page}_f{index}"` is deterministic and stable for a given PDF + extraction run. Stored in DB submissions so field values can always be matched back to their definitions.
- `source_hash` (SHA-256) enables future deduplication: if the same document is loaded again, the app can check whether the layout already exists in DB before re-extracting.
- `source_file` stores the full filename including extension (e.g. `"application.pdf"`). The generator factory uses `Path(layout.source_file).suffix` to select the correct generator for fill operations.
- `PageElements` lives in `models.py` (not in the reader) so `field_detector.py` and `layout_analyzer.py` can import it without coupling to any specific document format.

---

## 5. Readers — Factory & Registration

### Architecture Overview

Document reading uses a registry-based factory. Each format registers its reader via `@register_reader`. New formats are additive — no existing files are modified.

### `core/readers/base.py` — `DocumentReader` ABC

```python
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
```

### `core/readers/factory.py` — Registry + Decorator

```python
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
```

### `core/readers/pdf/reader.py` — PDF Reader (pdfplumber)

```python
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Iterator
import pdfplumber
from core.models import PageElements
from core.readers.factory import register_reader
from core.readers.base import DocumentReader


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
        Raises pdfplumber.pdfminer.pdfdocument.PDFPasswordIncorrect if encrypted.
        """
        with pdfplumber.open(file_path) as pdf:
            all_scanned = True
            for i, page in enumerate(pdf.pages, start=1):
                elements = PageElements(
                    page_number=i,
                    page_width=float(page.width),
                    page_height=float(page.height),
                    chars=page.chars or [],
                    words=page.extract_words() or [],
                    lines=page.lines or [],
                    rects=page.rects or [],
                )
                if elements.chars:
                    all_scanned = False
                yield elements
            if all_scanned:
                raise ValueError(
                    "This PDF appears to be scanned (no text characters found). "
                    "Only machine-generated PDFs are supported in this version."
                )
```

### `core/readers/pdf/__init__.py` — Trigger Registration

```python
from core.readers.pdf import reader  # side-effect: @register_reader fires
```

### `core/readers/__init__.py` — Public API + Auto-register All Formats

```python
from core.readers.factory import get_document_reader, READER_REGISTRY
from core.readers import pdf   # registers PdfDocumentReader
# To add Word support: from core.readers import docx
```

### Design Notes

- `pdfplumber.open()` always used as a context manager — guaranteed handle cleanup.
- `page.extract_words()` aggregates individual chars into word-level bounding boxes — better for label detection than raw chars.
- `lines` in pdfplumber includes explicit drawn lines and borders of unfilled rectangles.
- `rects` provides bounding boxes of rectangles — empty rects are the primary source of input box candidates.
- A page with `len(elements.chars) == 0` is a scanned/image-only page.
- `compute_hash` is on the reader (not a standalone function) so each format can choose its own hashing strategy (e.g. a docx reader might hash only the document body XML).

---

## 6. Field Detector (`core/field_detector.py`)

### 3-Pass Heuristic Pipeline

**Pass 1 — Structural Element Classification**

Scan `lines` and `rects` from `PageElements` to identify input areas:

| Condition | Candidate type |
|---|---|
| line with `width > MIN_INPUT_LINE_WIDTH_PT` and `height < 3pt` | input line (text field) |
| rect with `width > MIN_INPUT_LINE_WIDTH_PT`, `height < MIN_TEXTAREA_HEIGHT_PT`, no fill, no interior text | input box (text field) |
| rect with `height >= MIN_TEXTAREA_HEIGHT_PT`, no fill | textarea candidate |
| rect with `width <= CHECKBOX_MAX_SIZE_PT` and `height <= CHECKBOX_MAX_SIZE_PT` | checkbox candidate |
| word matching `r'^[_]{3,}$'` | underscore input line |

**Pass 2 — Label Association**

For each candidate input area `C` at `(x0, top, x1, bottom)`:

Search `words` for the nearest qualifying label using this priority:
1. Word that is directly above C: `word.bottom <= C.top + 5` and `word.x0 >= C.x0 - 20` and `word.x1 <= C.x1 + 20` — pick closest by `C.top - word.bottom`.
2. Word to the left of C on the same row: `abs(word.top - C.top) <= ROW_TOLERANCE_PT` and `word.x1 <= C.x0 + 5` — pick closest by `C.x0 - word.x1`.

If no label found → `label = ""` (unlabelled field — still included).

**Pass 3 — Field Type Classification**

```python
@functools.lru_cache(maxsize=256)
def _classify_field_type(label: str, is_checkbox: bool, is_textarea: bool) -> FieldType:
```

Rules applied in order (first match wins):

| Label contains (case-insensitive) | Assigned type |
|---|---|
| `is_checkbox == True` | `"checkbox"` |
| `is_textarea == True` | `"textarea"` |
| `"date"`, `"dob"`, `"d.o.b"`, `"birth"` | `"date"` |
| `"amount"`, `"total"`, `"salary"`, `"income"`, `"fee"`, `"price"`, `"cost"` | `"number"` |
| `"phone"`, `"tel"`, `"mobile"`, `"fax"` | `"text"` (placeholder: phone format) |
| `"email"`, `"e-mail"` | `"text"` (placeholder: email format) |
| default | `"text"` |

### Key Function Signature

```python
def detect_fields(pages: list[PageElements]) -> list[FormField]:
    """
    Run 3-pass detection on all pages.
    Returns list of FormField instances, IDs assigned as p{page}_f{index}.
    """
```

### Design Notes

- `@lru_cache` on `_classify_field_type` is safe because label strings are immutable and the classification is purely deterministic. Cache eliminates repeated regex/string checks for PDFs with many identical labels.
- All regex patterns are compiled at module level (not inside the function loop):
  ```python
  _RE_UNDERSCORES = re.compile(r'^[_]{3,}$')
  _RE_DATE = re.compile(r'\b(date|dob|d\.o\.b|birth)\b', re.IGNORECASE)
  # etc.
  ```
- Prefer `word` bounding boxes (not `char` bounding boxes) for label search — words aggregate chars, reducing iteration count significantly for dense pages.
- `extract_words(x_tolerance=5, y_tolerance=3)` is used instead of the default (3, 3) to correctly merge characters from PDFs with decorative spaced fonts (e.g. government forms with wide letter-spacing).
- `_filter_header_words()` strips words whose y-coordinate aligns with bold/large-font characters before label search — prevents form titles and section headers from being assigned as field labels.
- `_clean_label()` is a two-stage post-processor: Stage 1 collapses single-char runs (always active); Stage 2 collapses short-token-dominated strings (activates when ≥ 70% of tokens are ≤ 2 chars), handling residual spaced-font artefacts without affecting real short labels like "EC No".

---

## 7. Layout Analyzer (`core/layout_analyzer.py`)

### Responsibilities

Takes a flat `list[FormField]` and organises them into `FormSection` → `FormRow` hierarchy, reflecting their visual arrangement on the PDF.

### Algorithm

```
1. Sort all fields by (page, top, x0)

2. ROW GROUPING:
   Iterate through sorted fields.
   Start a new FormRow when: field.top > current_row_top + ROW_TOLERANCE_PT
   Otherwise append to current row.
   After adding all fields to a row, sort row.fields by x0.
   Set row.row_top = min(f.top for f in row.fields)

3. SECTION DETECTION:
   Before grouping into rows, scan words for section headers:
   - Compute avg_body_font_size = mean of all char['size'] values
   - A text block is a section header if:
       - its char['size'] > avg_body_font_size + FONT_SIZE_SECTION_DELTA, OR
       - 'Bold' in char['fontname'] (case-insensitive)
   - Section headers define boundaries: all rows until the next header → one FormSection
   - First section title = PDF filename stem if no header found before first field

4. ASSEMBLY:
   Return FormLayout(
       title = first section title or document stem,
       source_file = filename,
       source_hash = computed hash,
       page_count = max page seen,
       sections = [...],
       extracted_at = datetime.now(timezone.utc).isoformat()
   )
```

### Key Function Signature

```python
def build_layout(
    fields: list[FormField],
    pages: list[PageElements],
    source_file_name: str,
    source_hash: str,
) -> FormLayout:
```

---

## 8. Storage Layer

### 8a. Layout Serialisation (`storage/layout_store.py`)

FormLayout objects are stored in MongoDB/MontyDB as a compact JSON string in the `layout_json` field of the `layouts` collection.

```python
def serialise_layout(layout: FormLayout) -> str:
    """Convert FormLayout to compact JSON string."""
    # Use dataclasses.asdict() then json.dumps with compact separators

def deserialise_layout(json_str: str) -> FormLayout:
    """Reconstruct FormLayout from JSON string."""
    # json.loads → nested dict reconstruction using FormLayout, FormSection, FormRow, FormField
    # Must handle nested dataclass reconstruction manually (dataclasses.asdict is one-way)
```

**Important:** `dataclasses.asdict()` recursively converts nested dataclasses to dicts. `deserialise_layout` must reconstruct them by calling each constructor explicitly:

```python
def _field_from_dict(d: dict) -> FormField:
    return FormField(**d)

def _row_from_dict(d: dict) -> FormRow:
    return FormRow(fields=[_field_from_dict(f) for f in d["fields"]], row_top=d["row_top"])

def _section_from_dict(d: dict) -> FormSection:
    return FormSection(title=d["title"], rows=[_row_from_dict(r) for r in d["rows"]], page=d["page"])

def deserialise_layout(json_str: str) -> FormLayout:
    d = json.loads(json_str)
    return FormLayout(
        title=d["title"],
        source_file=d["source_file"],
        source_hash=d["source_hash"],
        page_count=d["page_count"],
        sections=[_section_from_dict(s) for s in d["sections"]],
        extracted_at=d["extracted_at"],
    )
```

### 8b. Database Layer (`storage/db.py`)

#### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_TYPE` | `montydb` | `montydb` for local, `mongodb` for production |
| `DB_PATH` | `./data/formfiller_db` | MontyDB storage directory |
| `DB_URI` | *(none)* | PyMongo connection string (used only when `DB_TYPE=mongodb`) |
| `DB_NAME` | `formfiller_db` | Database name |

#### DB Client Factory

```python
DB_NAME: str = "formfiller_db"

def get_db_client():
    """Returns MontyClient or pymongo.MongoClient based on DB_TYPE env var."""
    db_type = os.getenv("DB_TYPE", "montydb").lower()
    if db_type == "mongodb":
        uri = os.environ["DB_URI"]  # Raise if not set — fail fast in production
        return pymongo.MongoClient(uri)
    else:
        db_path = os.getenv("DB_PATH", "./data/formfiller_db")
        Path(db_path).mkdir(parents=True, exist_ok=True)
        return MontyClient(host=db_path)

def get_collection(name: str):
    client = get_db_client()
    return client[DB_NAME][name]
```

**Note:** `MontyClient` (not `MontyCient`) — the correct spelling is `MontyClient`. Import: `from montydb import MontyClient`.

#### Collections Schema

**`layouts` collection:**
```json
{
  "_id": ObjectId,
  "source_file": "application.pdf",
  "source_hash": "abc123...",
  "layout_json": "{\"title\":\"Application Form\",...}",
  "created_at": "2026-04-22T10:00:00+00:00"
}
```

**`submissions` collection:**
```json
{
  "_id": ObjectId,
  "tag": "john_doe_2026",
  "layout_id": "6629f1a2b3c4d5e6f7a8b9c0",
  "form_title": "Application Form",
  "source_file": "application.pdf",
  "filled_at": "2026-04-22T11:30:00+00:00",
  "fields": [
    {"id": "p1_f0", "label": "Full Name", "value": "John Doe"},
    {"id": "p1_f1", "label": "Date of Birth", "value": "1990-01-15"}
  ]
}
```

**Index:** `submissions.tag` must have a unique index. Create on first write if absent.

#### CRUD Functions

```python
def save_layout(layout: FormLayout) -> str:
    """Insert layout into layouts collection. Returns inserted _id as string."""

def load_layout_by_id(layout_id: str) -> FormLayout:
    """Fetch layout by _id string, deserialise and return FormLayout."""

def get_all_submission_summaries() -> list[dict]:
    """
    Lazy query — returns only tag, form_title, source_file, filled_at.
    Does NOT return full fields list (performance: avoids loading large field arrays).
    """

def get_submission_by_tag(tag: str) -> dict | None:
    """Returns full submission document or None if not found."""

def tag_exists(tag: str) -> bool:
    """Check if tag is already in use."""

def insert_submission(
    tag: str,
    layout_id: str,
    form_title: str,
    source_file: str,
    field_values: dict[str, str],
    layout: FormLayout,
) -> None:

def update_submission(tag: str, field_values: dict[str, str]) -> None:
    """Overwrite fields and update filled_at timestamp for existing tag."""
```

---

## 9. Generators — Factory & Registration

### Architecture Overview

Identical factory/registry pattern as Readers. Each format registers its generator via `@register_generator`. New formats are additive — no existing files modified.

### `core/generators/base.py` — `DocumentGenerator` ABC

```python
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
```

### `core/generators/factory.py` — Registry + Decorator

```python
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
```

### `core/generators/pdf/generator.py` — PDF Generator (reportlab + pypdf)

#### Approach

1. Load original PDF bytes from `source_dir/<layout.source_file>` using `pypdf.PdfReader`.
2. For each page, create a blank canvas (same dimensions as original) using `reportlab.pdfgen.canvas.Canvas` writing to an `io.BytesIO` buffer.
3. On the canvas, draw each field's submitted value at the correct position.
4. Use `pypdf.PdfWriter` to overlay (stamp) each canvas page onto the corresponding original page.
5. Write the final merged PDF to `io.BytesIO` and return its bytes.

#### Coordinate Conversion

pdfplumber measures `top` from the **top** of the page downward.
reportlab measures `y` from the **bottom** of the page upward.

```python
def _to_reportlab_y(field: FormField, page_height: float) -> float:
    """Convert pdfplumber top-origin y to reportlab bottom-origin y."""
    return page_height - field.top - field.height / 2
```

#### Full Implementation

```python
from __future__ import annotations
import io
from collections import defaultdict
from pathlib import Path
import pypdf
from reportlab.pdfgen import canvas as rl_canvas
from core.models import FormField, FormLayout
from core.generators.factory import register_generator
from core.generators.base import DocumentGenerator


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

        fields_by_page: dict[int, list[FormField]] = defaultdict(list)
        for section in layout.sections:
            for row in section.rows:
                for f in row.fields:
                    fields_by_page[f.page].append(f)

        for page_num, page_obj in enumerate(reader.pages, start=1):
            page_height = float(page_obj.mediabox.height)
            page_width = float(page_obj.mediabox.width)

            overlay_buf = io.BytesIO()
            c = rl_canvas.Canvas(overlay_buf, pagesize=(page_width, page_height))

            for field in fields_by_page.get(page_num, []):
                value = field_values.get(field.id, "").strip()
                if not value:
                    continue
                if field.field_type == "checkbox":
                    draw_text = "X" if value.lower() in ("true", "yes", "checked", "1") else ""
                else:
                    draw_text = value

                if draw_text:
                    c.setFont("Helvetica", 10)
                    rl_y = page_height - field.top - field.height / 2
                    c.drawString(field.x0 + 2, rl_y, draw_text)

            c.save()
            overlay_buf.seek(0)

            overlay_reader = pypdf.PdfReader(overlay_buf)
            page_obj.merge_page(overlay_reader.pages[0])
            writer.add_page(page_obj)

        output_buf = io.BytesIO()
        writer.write(output_buf)
        return output_buf.getvalue()
```

### `core/generators/pdf/__init__.py` — Trigger Registration

```python
from core.generators.pdf import generator  # side-effect: @register_generator fires
```

### `core/generators/__init__.py` — Public API + Auto-register All Formats

```python
from core.generators.factory import get_document_generator, GENERATOR_REGISTRY
from core.generators import pdf   # registers PdfDocumentGenerator
# To add Word support: from core.generators import docx
```

### Design Notes

- Font: Helvetica 10pt (standard form fill size). No external font dependency.
- For checkbox fields: draw "X" only when value is `"true"`, `"yes"`, `"checked"`, or `"1"`.
- Only draw non-empty, non-whitespace values — never draws empty strings onto PDF.
- `source_dir` parameter instead of hardcoded path — generator is testable in isolation.
- reportlab canvas `x` = from left edge, `y` = from bottom edge: `x = field.x0 + 2`, `y = _to_reportlab_y(field, page_height)`.

---

## 10. UI — Form Builder (`ui/form_builder.py`)

### `build_field_component()`

The single function for rendering one FormField as a Gradio component. Used in both new and edit modes — **never duplicated**.

```python
def build_field_component(field: FormField, prefill: str = "") -> gr.components.Component:
    """
    Returns the appropriate Gradio component for a FormField.
    prefill: previously saved value (empty string for new forms).
    """
    label = field.label or f"Field {field.id}"
    match field.field_type:
        case "text":
            return gr.Textbox(label=label, value=prefill, placeholder=field.placeholder)
        case "textarea":
            return gr.Textbox(label=label, value=prefill, lines=4, placeholder=field.placeholder)
        case "number":
            return gr.Number(label=label, value=float(prefill) if prefill else None)
        case "date":
            return gr.Textbox(label=label, value=prefill, placeholder="YYYY-MM-DD")
        case "checkbox":
            return gr.Checkbox(label=label, value=prefill.lower() in ("true", "yes", "checked", "1"))
        case "dropdown":
            return gr.Dropdown(label=label, choices=field.options, value=prefill or None)
        case _:
            return gr.Textbox(label=label, value=prefill)
```

### `@gr.render` Dynamic Form

```python
@gr.render(inputs=[layout_state, values_state, mode_state])
def render_form(layout: FormLayout | None, values: dict, mode: str):
    if layout is None:
        gr.Markdown("*No form loaded. Return to Home to select a PDF.*")
        return
    for section in layout.sections:
        if section.title:
            gr.Markdown(f"### {section.title}")
        for row in section.rows:
            with gr.Row():
                for field in row.fields:
                    prefill = values.get(field.id, "")
                    component = build_field_component(field, prefill)
                    # Capture field.id in closure with default argument
                    component.change(
                        fn=lambda val, fid=field.id, s=values: {**s, fid: val},
                        inputs=[component],
                        outputs=[values_state],
                    )
```

**Warning on closures:** The `fid=field.id` default-argument pattern is mandatory. Without it, all lambdas capture the same final `field` reference (Python late-binding closure bug).

---

## 11. Application Entry Point (`app.py`)

### Screen Architecture

All three screens exist in one `gr.Blocks()` instance. Screens are `gr.Column` components toggled via `visible=True/False`. This is the correct Gradio pattern — no routing library needed.

```
gr.Blocks()
├── home_col (Column, visible=True initially)
│   ├── Panel A: "Continue Previous Submission"
│   │   ├── gr.Dropdown (saved tags)
│   │   ├── gr.Button("Refresh")
│   │   ├── gr.Markdown (preview info)
│   │   └── gr.Button("Load & Edit", variant="primary")
│   └── Panel B: "Start New Form"
│       ├── gr.Dropdown (PDF files from input-forms/)
│       ├── gr.Button("Refresh")
│       └── gr.Button("Load Form", variant="primary")
│
├── fill_col (Column, visible=False)
│   ├── @gr.render (dynamic form components)
│   ├── gr.Button("Save Form")
│   └── gr.Button("← Back to Home")
│
└── wizard_col (Column, visible=False)
    ├── gr.Markdown("## Save Options")
    ├── tag_input (gr.Textbox, editable in new mode, read-only in edit mode)
    ├── gr.Row()
    │   ├── gr.Button("Save to DB")
    │   ├── gr.Button("Generate Form")
    │   └── gr.Button("Save & Generate", variant="primary")
    ├── status_out (gr.Markdown)
    └── pdf_output (gr.File, visible only when Generate or Save & Generate was clicked)
```

### Application State Variables

```python
layout_state    = gr.State(None)         # FormLayout | None
layout_id_state = gr.State("")           # str: _id of layout in DB
values_state    = gr.State({})           # dict[str, str]: {field_id: value}
mode_state      = gr.State("new")        # "new" | "edit"
tag_state       = gr.State("")           # current tag (used in edit mode prefill)
```

### Navigation Handlers (return tuples updating Column visibility)

```python
def go_to_fill():
    return gr.update(visible=False), gr.update(visible=True), gr.update(visible=False)

def go_to_home():
    return gr.update(visible=True), gr.update(visible=False), gr.update(visible=False)

def go_to_wizard():
    return gr.update(visible=False), gr.update(visible=False), gr.update(visible=True)
```

### Wizard: Single DRY Handler

```python
def execute_wizard_action(
    action: WizardAction,
    tag: str,
    field_values: dict[str, str],
    layout_id: str,
    form_title: str,
    source_file: str,
    is_edit_mode: bool,
) -> tuple[bytes | None, str]:
    """
    Single handler for all 3 wizard buttons.
    Returns (pdf_bytes_or_None, status_message).
    After returning, the caller navigates back to Home.
    """
    pdf_bytes: bytes | None = None
    status_parts: list[str] = []

    if action in (WizardAction.SAVE_ONLY, WizardAction.SAVE_AND_GENERATE):
        msg = _persist_submission(tag, layout_id, form_title, source_file, field_values, is_edit_mode)
        status_parts.append(msg)

    if action in (WizardAction.GENERATE_ONLY, WizardAction.SAVE_AND_GENERATE):
        pdf_bytes = _render_filled_pdf(layout_id, field_values)
        status_parts.append("PDF generated.")

    return pdf_bytes, " ".join(status_parts)


def _persist_submission(
    tag: str,
    layout_id: str,
    form_title: str,
    source_file: str,
    field_values: dict[str, str],
    is_edit_mode: bool,
) -> str:
    if is_edit_mode:
        update_submission(tag, field_values)
        return f"Submission '{tag}' updated."
    else:
        insert_submission(tag, layout_id, form_title, source_file, field_values, ...)
        return f"Submission '{tag}' saved."


def _render_filled_pdf(layout_id: str, field_values: dict[str, str]) -> bytes:
    layout = load_layout_by_id(layout_id)
    input_forms_dir = Path("./input-forms")
    generator = get_document_generator(Path(layout.source_file))
    return generator.generate_filled(layout, field_values, input_forms_dir)
```

### Home Screen Data Loading

```python
def scan_input_forms_dir() -> list[str]:
    """Returns list of supported document filenames in input-forms/. Creates dir if absent."""
    from core.readers import READER_REGISTRY
    supported: tuple[str, ...] = tuple(READER_REGISTRY.keys())
    d = Path("./input-forms")
    d.mkdir(exist_ok=True)
    return sorted(p.name for p in d.iterdir() if p.suffix.lower() in supported)

def load_all_tags() -> list[str]:
    """Returns sorted list of all saved tags from DB."""
    summaries = get_all_submission_summaries()
    return sorted(s["tag"] for s in summaries)
```

Both functions are registered to their respective Refresh buttons. Both are also called on app startup to populate initial dropdown values.

### Key Imports in `app.py`

```python
from core.readers import get_document_reader, READER_REGISTRY
from core.generators import get_document_generator
from core.field_detector import detect_fields
from core.layout_analyzer import build_layout
from storage.db import (
    save_layout, load_layout_by_id,
    get_all_submission_summaries, get_submission_by_tag,
    tag_exists, insert_submission, update_submission,
)
```

### Panel A Preview Markdown

When user selects a tag from the dropdown (before clicking Load & Edit), show a preview:

```
**Form:** Application Form
**Source PDF:** application.pdf
**Last Saved:** 2026-04-22 11:30 UTC
```

This requires a `gr.Dropdown.change` event that calls `get_submission_by_tag(tag)` and returns a formatted markdown string.

### Tag Validation (New Mode)

Before any wizard action in new mode:
1. If `tag.strip() == ""` → show error "Tag cannot be empty." Block action.
2. If `tag_exists(tag)` → show error "Tag '{tag}' already exists. Choose a different name." Block action.

This validation runs inside `execute_wizard_action` or as a pre-check before calling it.

---

## 12. Wizard State Machine (Detailed Flow)

```
[Home Screen]
     │
     ├──(Panel A) User selects tag → clicks "Load & Edit"
     │        load_submission_by_tag(tag)
     │        load_layout_by_id(layout_id)
     │        populate values_state with saved field values
     │        mode_state = "edit", tag_state = tag
     │        → navigate to [Fill Screen]
     │
     └──(Panel B) User selects PDF → clicks "Load Form"
              process_pdf(filename):
                get_document_reader(path).parse(path) → detect_fields → build_layout
                save_layout to DB → layout_id_state
                layout_state = FormLayout
                values_state = {}, mode_state = "new"
              → navigate to [Fill Screen]

[Fill Screen]
     │
     ├── User fills/edits fields (values_state updated on each change)
     │
     ├── "Save Form" button clicked
     │        → navigate to [Wizard Screen]
     │
     └── "← Back to Home" button clicked
              → navigate to [Home Screen]

[Wizard Screen]
     │
     ├── tag_input shown:
     │       mode="new" → editable Textbox, empty
     │       mode="edit" → read-only Textbox, pre-filled with tag_state
     │
     ├── "Save to DB" clicked
     │        validate_tag → execute_wizard_action(SAVE_ONLY, ...)
     │        show status → navigate to [Home Screen]
     │
     ├── "Generate Form" clicked
     │        validate_tag → execute_wizard_action(GENERATE_ONLY, ...)
     │        show pdf_output → navigate to [Home Screen]
     │
     └── "Save & Generate" clicked
              validate_tag → execute_wizard_action(SAVE_AND_GENERATE, ...)
              show status + pdf_output → navigate to [Home Screen]
```

---

## 13. Error Handling Specification

All errors are surfaced to the user through Gradio UI (not raw Python tracebacks).

| Error Condition | Where Raised | How Surfaced |
|---|---|---|
| Scanned PDF (all pages image-only) | `PdfDocumentReader.parse()` | `ValueError` caught in `process_pdf()` → `gr.Warning` toast |
| Password-protected PDF | `pdfplumber.open()` | `Exception` caught → `gr.Warning` toast |
| No fields detected | `detect_fields()` returns empty list | `gr.Info` toast: "No fields detected. Check if the PDF is a form." — allow proceed |
| Duplicate tag (new mode) | `tag_exists()` in wizard | `gr.Warning` toast, action blocked |
| Empty tag (new mode) | Pre-check in wizard handler | `gr.Warning` toast, action blocked |
| Source document missing for Generate | `generate_filled()` | `FileNotFoundError` caught → `gr.Warning` toast |
| `input-forms/` dir missing | `scan_input_forms_dir()` | Auto-creates dir, `gr.Info` toast "input-forms/ directory created" |
| No saved tags | `load_all_tags()` returns `[]` | Panel A shows disabled button with caption "No previous submissions found" |
| DB connection failure | `get_db_client()` | `Exception` propagated → `gr.Error` toast (fatal) |

---

## 14. Configuration Files

### `requirements.txt`

```
pdfplumber==0.11.9
gradio==6.13.0
python-dotenv==1.0.1
montydb>=2.5.2
pymongo>=4.6
reportlab>=4.2
pypdf>=4.3
openai>=1.30
```

### `.env.example`

```dotenv
# Database configuration
# Set DB_TYPE=montydb for local development (default)
# Set DB_TYPE=mongodb for production MongoDB
DB_TYPE=montydb

# MontyDB: path to local storage directory (used when DB_TYPE=montydb)
DB_PATH=./data/formfiller_db

# MongoDB: connection URI (used only when DB_TYPE=mongodb)
# DB_URI=mongodb://localhost:27017

# Database name
DB_NAME=formfiller_db

# ── LLM Field Enrichment (Phase 2 — optional) ─────────────────────────────────
# If LLM_API_KEY is absent or empty the app runs in heuristic-only mode.
# Provider selection is done entirely through env vars — no code change needed.

# OpenAI (default)
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# Azure OpenAI (uncomment and fill)
# LLM_API_KEY=<azure-key>
# LLM_BASE_URL=https://<resource>.openai.azure.com/openai/deployments/<deployment>
# LLM_MODEL=gpt-4o

# Local / OpenAI-compatible (e.g. Ollama, LM Studio)
# LLM_API_KEY=ollama
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=mistral
```

### `.gitignore`

```gitignore
# Environment
.env

# MontyDB data files
data/

# Python
__pycache__/
*.pyc
*.pyo
.venv/
venv/

# Gradio temp files
gradio_cached_examples/
```

---

## 15. Startup Sequence (`app.py` main block)

```python
if __name__ == "__main__":
    # 1. Load environment variables
    from dotenv import load_dotenv
    load_dotenv()

    # 2. Ensure input-forms/ directory exists
    input_dir = Path("./input-forms")
    input_dir.mkdir(exist_ok=True)

    # 3. Ensure data/ directory exists (MontyDB will also do this, but belt-and-suspenders)
    Path(os.getenv("DB_PATH", "./data/formfiller_db")).mkdir(parents=True, exist_ok=True)

    # 4. Build and launch Gradio app
    demo = build_app()
    demo.launch(server_name="127.0.0.1", server_port=7860)
```

---

## 16. Implementation Order

Implement files in this dependency order to enable incremental testing:

1. `core/models.py` — No dependencies. Includes `PageElements`. Verify dataclass instantiation.
2. `core/readers/base.py` — Depends on `models.py`. `DocumentReader` ABC.
3. `core/readers/factory.py` — Depends on `base.py`. Registry + decorator + `get_document_reader()`.
4. `core/readers/pdf/reader.py` — Depends on `factory.py`. `PdfDocumentReader` with all pdfplumber logic.
5. `core/readers/pdf/__init__.py` — One import line. Triggers `@register_reader`.
6. `core/readers/__init__.py` — Imports factory exports + pdf subpackage. Test reader lookup by extension.
7. `core/field_detector.py` — Depends on `models.py`. Test field list output.
8. `core/layout_analyzer.py` — Depends on `field_detector.py` + `models.py`. Test section/row grouping.
9. `core/llm/enricher.py` — Depends on `models.py`. Callable independently; returns enriched `list[FormField]`. Gracefully no-ops when `LLM_API_KEY` is unset.
10. `core/llm/__init__.py` — Exports `enrich_fields_with_llm()`.
11. `storage/layout_store.py` — Depends on `models.py`. Test round-trip serialise/deserialise.
10. `storage/db.py` — Depends on `layout_store.py`. Test CRUD with MontyDB.
11. `core/generators/base.py` — Depends on `models.py`. `DocumentGenerator` ABC.
12. `core/generators/factory.py` — Depends on `base.py`. Registry + decorator + `get_document_generator()`.
13. `core/generators/pdf/generator.py` — Depends on `factory.py`. `PdfDocumentGenerator` with reportlab+pypdf logic.
14. `core/generators/pdf/__init__.py` — One import line. Triggers `@register_generator`.
15. `core/generators/__init__.py` — Imports factory exports + pdf subpackage.
16. `ui/form_builder.py` — Depends on `models.py`. Test `build_field_component` for each field type.
17. `app.py` — Depends on all above. Wires everything; final integration.
18. `requirements.txt`, `.env.example`, `.gitignore` — Created alongside step 1.

---

## 17. Verification Checklist

All of these must pass before the implementation is considered complete:

1. `pip install -r requirements.txt` succeeds on Windows Python 3.10+.
2. `python app.py` starts without errors. Gradio app launches at `http://127.0.0.1:7860`.
3. `input-forms/` directory auto-created if missing. Info toast shown.
4. Home screen Panel A: shows "No previous submissions found" with disabled button when DB is empty.
5. Home screen Panel B: lists supported document files from `input-forms/` (all extensions in `READER_REGISTRY`).
6. Panel B Refresh button: detects newly added PDFs without app restart.
7. Select a PDF → "Load Form" → fields extracted → Fill Form screen opens.
8. Fill Form screen renders components matching detected field types (text, checkbox, etc.).
9. Rows of fields render in `gr.Row()` blocks, approximating PDF horizontal layout.
10. Fill values → "Save Form" → Wizard screen appears.
11. Wizard new mode: tag input is empty and editable.
12. Enter tag → "Save to DB" → saved to MontyDB → returned to Home screen.
13. Relaunch app → Panel A shows the saved tag in dropdown.
14. Select tag → "Load & Edit" → Fill Form screen opens with values pre-populated.
15. Edit a value → "Save Form" → Wizard shows tag pre-filled (read-only).
16. "Save to DB" in edit mode → overwrites existing record (same `_id`, updated `filled_at`).
17. "Generate Form" → `gr.File` download appears with filled PDF.
18. Open downloaded PDF → submitted values visible at correct field positions.
19. "Save & Generate" → both DB save and PDF download occur.
20. Duplicate tag attempt in new mode → warning shown, save blocked.
21. Empty tag in new mode → warning shown, action blocked.
22. Place a scanned PDF in `input-forms/` → select it → warning toast, no crash.
23. Remove source PDF from `input-forms/` then click "Generate Form" → clear error shown.
24. Set `DB_TYPE=mongodb` in `.env` (with local MongoDB running) → all operations work identically.

---

## 18. Architecture Decision Record (ADR)

### ADR-001: Screen Navigation via `gr.Column(visible=)` not `gr.Tab`

**Decision:** Use three `gr.Column` blocks with `visible` toggling for Home → Fill → Wizard flow.

**Rationale:** `gr.Tab` shows all tabs simultaneously and cannot be programmatically switched. `gr.Column(visible=)` allows imperative navigation controlled by button click event handlers. This is the standard Gradio pattern for multi-step wizard flows.

---

### ADR-002: Single `execute_wizard_action()` for 3 Buttons

**Decision:** One function handles Save Only, Generate Only, and Save & Generate.

**Rationale:** Three separate handlers would contain duplicated `_persist_submission` and `_render_filled_pdf` logic. The `WizardAction` enum makes the branching explicit and exhaustive. Adding a 4th action in the future requires one `case` branch, not a new handler.

---

### ADR-003: Store `layout_json` as Compact JSON String in DB

**Decision:** Serialise `FormLayout` to a JSON string and store it as a single field in the `layouts` document, rather than as nested BSON subdocuments.

**Rationale:** MontyDB's subdocument query support is a subset of MongoDB's. Storing as a string avoids potential incompatibilities and ensures zero changes are needed when migrating to production MongoDB. Deserialisation is fast (`json.loads` + constructor calls). The `layout_json` field is only loaded when needed (not in `get_all_submission_summaries()`).

---

### ADR-004: `layout_id` Foreign Key in Submissions

**Decision:** Every submission document stores the `_id` of its parent layout document as a string field `layout_id`.

**Rationale:** The same PDF can be loaded multiple times. Storing the layout separately and referencing it from submissions avoids duplicating the (potentially large) layout JSON in every submission. When editing a previous submission, the app fetches the layout once by `layout_id` and reuses it.

---

### ADR-005: No Temp Files for PDF Operations

**Decision:** All PDF generation uses `io.BytesIO` buffers. Nothing is written to disk.

**Rationale:** Temp file cleanup is error-prone (crash before cleanup = leaked files). `io.BytesIO` lives in process memory and is garbage-collected automatically. Gradio's `gr.File` accepts `bytes` directly, making disk writes unnecessary.

---

### ADR-006: `@dataclass(slots=True)` on All Models

**Decision:** Apply `slots=True` to every domain dataclass.

**Rationale:** A typical form extraction run creates hundreds of `FormField` instances. `slots=True` eliminates the `__dict__` per instance, reducing memory by ~20% and improving attribute access speed via C-level slot descriptors. Available since Python 3.10 (matching our minimum version requirement).

---

### ADR-007: MontyDB for Local, PyMongo for Production

**Decision:** MontyDB in development, PyMongo + MongoDB Atlas/Server in production. Switch via `DB_TYPE` env var.

**Rationale:** MontyDB's `MontyClient` is API-compatible with `pymongo.MongoClient` for all operations used here (find, insert_one, update_one, find_one, create_index). Zero application code changes between environments. MontyDB uses SQLite as its engine — safe on Windows, no separate process to manage.

---

### ADR-008: pdfplumber Coordinate System

**Decision:** All field coordinates stored in pdfplumber's coordinate system (`top` = distance from top of page, `y0` = bottom from top).

**Rationale:** pdfplumber is the parsing library. Storing in its native coordinate system avoids a conversion at parse time. The only conversion needed is when generating the filled PDF overlay (once, in `PdfDocumentGenerator`). This single conversion point is explicitly documented.

---

### ADR-009: Reader and Generator Factory (Open/Closed Principle)

**Decision:** Document reading and generation use a registry-based factory with class decorator registration (`@register_reader`, `@register_generator`). Each format lives in its own subfolder (`core/readers/pdf/`, `core/generators/pdf/`). New formats are added by: (a) creating new files in a new subfolder, (b) adding one import line to the corresponding `__init__.py`. No existing files are modified.

**Rationale:** Without a factory, adding Word support would require modifying existing modules — touching tested code and violating Open/Closed Principle. With the factory, adding `.docx` support is purely additive. The registry also provides a runtime list of supported extensions (`READER_REGISTRY.keys()`) that `scan_input_forms_dir()` uses to automatically support all registered formats — no hardcoded extension lists anywhere in the application.

---

## 19. Known Limitations and Future Phases

| Limitation | Future Resolution |
|---|---|
| Cannot detect radio button groups (visually similar to checkboxes) | Pass 4 heuristic: cluster nearby checkboxes with same label prefix → radio group |
| Section detection relies on font size — not all PDFs use larger fonts for headers | Fallback: detect bold font weight as secondary header signal (already partially planned) |
| Layout may misalign for PDFs with rotated pages | Detect `page.rotation` in `PdfDocumentReader.parse()` and adjust coordinates |
| MontyDB not process-safe (no concurrent writes) | Switch to MongoDB for any multi-user deployment (ADR-007 handles this) |
| Checkbox label association can be ambiguous for tight checkbox grids | Spatial clustering heuristic in Pass 2 can be enhanced |
| LLM field enrichment is optional / best-effort | Phase 2 implemented in `core/llm/enricher.py` — see Section 17 |

---

## 20. Phase 2 — Hybrid LLM Field Enrichment

### Motivation

The heuristic pipeline in `core/field_detector.py` is reliable for structural detection (finding *where* input areas are on the page) but has inherent semantic limitations:

- Cannot understand table column headers (e.g. "1st Applicant / 2nd Applicant / 3rd Applicant" as column context)
- Cannot detect fields indicated by dotted lines (`..........`) or sentence-embedded blanks
- Label association is purely geometric — no understanding of form intent

An LLM, given the word list with positions, understands form semantics. The hybrid approach uses pdfplumber for coordinates (exact) and the LLM for labelling (semantic).

### Architecture

```
pdfplumber ──► field_detector.py ──► list[FormField]   (coordinates exact, labels may be imprecise)
                                           │
                                 enrich_fields_with_llm()  ◄── LLM_API_KEY present?
                                           │                         No → return as-is
                                           ▼
                                 list[FormField]   (same ids + coords, labels/types improved)
                                           │
                                 layout_analyzer.py ──► FormLayout ──► DB + UI
```

**Key invariant:** `enrich_fields_with_llm()` may only modify `label`, `field_type`, and `placeholder`. It must **never** change `id`, `x0`, `top`, `x1`, `bottom`, or `page` — those are the coordinates the generator uses to place text on the PDF.

### SDK Choice: `openai` (provider-agnostic)

The `openai` Python SDK is used instead of the Anthropic SDK or Azure AI Foundry SDK because:

| Concern | `openai` SDK |
|---|---|
| Provider lock-in | None — `base_url` env var selects the provider |
| Local models | Yes — Ollama, LM Studio, any OpenAI-compatible server |
| Azure OpenAI | Yes — same SDK, different `base_url` |
| Anthropic/Claude | No — different protocol; use an OpenAI-compatible proxy if needed |
| MAF (Azure AI Foundry) | No — MAF adds Azure deployment infrastructure with zero benefit for a local app |

### `core/llm/enricher.py`

```python
from __future__ import annotations

import json
import os

from openai import OpenAI

from core.models import FieldType, FormField, PageElements

_SYSTEM_PROMPT: str = """
You are a form analysis assistant. You will be given:
1. The raw text content of a PDF form (words in reading order, prefixed by page number).
2. A list of detected input fields with their current auto-detected labels.

Your task: for each field return an improved label (what information the form is asking for),
an appropriate field_type, and an optional placeholder.

Rules:
- Return ONLY valid JSON: a list of objects, one per field, in the same order received.
- Each object: {"id": str, "label": str, "field_type": str, "placeholder": str}
- field_type must be one of: text, number, date, checkbox, textarea, dropdown
- Never invent fields. Only improve the ones given.
- Labels must be concise (≤ 60 chars), title case.
- If the current label is already correct, return it unchanged.
- Ignore decorative text, watermarks, and form titles — they are never field labels.
""".strip()

_VALID_FIELD_TYPES: frozenset[str] = frozenset(
    {"text", "number", "date", "checkbox", "textarea", "dropdown"}
)


def _build_page_context(pages: list[PageElements]) -> str:
    lines: list[str] = []
    for page in pages:
        lines.append(f"--- Page {page.page_number} ---")
        lines.extend(w["text"] for w in page.words if str(w.get("text", "")).strip())
    return "\n".join(lines)


def enrich_fields_with_llm(
    fields: list[FormField],
    pages: list[PageElements],
) -> list[FormField]:
    """
    Post-process heuristically detected fields using an LLM.
    Returns the same list with label/field_type/placeholder potentially improved.
    Falls back to original fields silently on any error — LLM enrichment is best-effort.
    If LLM_API_KEY is absent or empty, returns fields unchanged (heuristic-only mode).
    """
    api_key: str = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        return fields

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    context: str = _build_page_context(pages)

    field_summaries = [
        {"id": f.id, "label": f.label, "field_type": f.field_type, "placeholder": f.placeholder}
        for f in fields
    ]
    user_message: str = (
        f"Form text context:\n{context}\n\n"
        f"Detected fields:\n{json.dumps(field_summaries, separators=(',', ':'))}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw: str = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        enriched_list: list[dict] = data if isinstance(data, list) else data.get("fields", [])
        enriched_map: dict[str, dict] = {item["id"]: item for item in enriched_list}

        result: list[FormField] = []
        for f in fields:
            patch = enriched_map.get(f.id)
            if patch:
                new_type: FieldType = (
                    patch["field_type"]
                    if patch.get("field_type") in _VALID_FIELD_TYPES
                    else f.field_type
                )
                result.append(FormField(
                    id=f.id,
                    label=str(patch.get("label", f.label))[:80],
                    field_type=new_type,
                    placeholder=str(patch.get("placeholder", f.placeholder)),
                    page=f.page, x0=f.x0, top=f.top, x1=f.x1, bottom=f.bottom,
                    options=f.options, required=f.required,
                ))
            else:
                result.append(f)
        return result

    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        return fields
```

### `core/llm/__init__.py`

```python
from core.llm.enricher import enrich_fields_with_llm

__all__ = ["enrich_fields_with_llm"]
```

### Integration in `app.py`

Insert between `detect_fields()` and `build_layout()` in `process_pdf()`:

```python
from core.llm import enrich_fields_with_llm

# inside process_pdf():
fields = detect_fields(pages)
fields = enrich_fields_with_llm(fields, pages)   # no-op when LLM_API_KEY unset
layout = build_layout(fields, pages, filename, source_hash)
```

### Provider Reference

| Provider | `LLM_BASE_URL` | `LLM_MODEL` | Notes |
|---|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | Default |
| Azure OpenAI | `https://<resource>.openai.azure.com/openai/deployments/<deployment>` | deployment name | Same SDK |
| Ollama (local) | `http://localhost:11434/v1` | `mistral`, `llama3` | Free, offline |
| LM Studio | `http://localhost:1234/v1` | loaded model name | Free, offline |
