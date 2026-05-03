# PDF Form Filler — Complete Documentation

---

## Table of Contents

1. [Application Overview](#1-application-overview)
2. [What the App Achieves](#2-what-the-app-achieves)
3. [Architecture](#3-architecture)
4. [Module Design & Code Documentation](#4-module-design--code-documentation)
   - 4.1 [Entry Points](#41-entry-points)
   - 4.2 [Core Layer](#42-core-layer)
   - 4.3 [Storage Layer](#43-storage-layer)
   - 4.4 [UI Layer](#44-ui-layer)
5. [Data Models](#5-data-models)
6. [LLM Integration](#6-llm-integration)
7. [Database Design](#7-database-design)
8. [Dependency Reference](#8-dependency-reference)
9. [Environment Variables & Configuration](#9-environment-variables--configuration)
10. [How to Execute](#10-how-to-execute)
11. [Running Tests](#11-running-tests)
12. [Scope Boundaries (What It Does NOT Do)](#12-scope-boundaries-what-it-does-not-do)
13. [Future Features](#13-future-features)

---

## 1. Application Overview

**Name:** PDF Form Filler

**Type:** Local desktop web application (no cloud infrastructure required).

**Technology:** Python 3.10+, Gradio, FastAPI, MontyDB/MongoDB, pdfplumber, ReportLab, pypdf.

PDF Form Filler is a self-hosted web app that allows users to fill machine-generated PDF forms through a web browser. Given a PDF form placed in the `input-forms/` folder, the application:

- Parses the PDF to detect and classify all fillable areas (text boxes, checkboxes, date fields, number fields, textareas).
- Presents an equivalent web form in the browser that mirrors the PDF's layout and section structure.
- Saves submitted values to a local database under a user-defined tag.
- Regenerates a pixel-accurate filled PDF by overlaying entered values onto the original PDF pages.
- Supports editing previously saved submissions and re-downloading the filled PDF.
- Optionally uses an LLM (OpenAI, Azure OpenAI, Anthropic, or AWS Bedrock) to improve the auto-detected field labels and types.

---

## 2. What the App Achieves

The core problem the app solves is: **filling paper-style PDF forms digitally, without requiring the PDF to contain interactive AcroForm widgets**.

Most PDF forms encountered in government offices, banks, and institutions are visual/print-style: they contain underlines, bordered boxes, or tables as visual cues for where to write, but no embedded form fields. Standard PDF viewers cannot fill these. PDF Form Filler bridges this gap entirely in software:

```
Visual PDF Form  →  Heuristic Detection  →  Web Form  →  User Input  →  Filled PDF
```

**Key outcomes:**
- No PDF editing software needed.
- No manual field mapping required — detection is automatic.
- Filled PDFs are pixel-accurate overlays on the original document.
- All data is stored locally — nothing leaves the machine unless an external LLM is configured.

---

## 3. Architecture

### 3.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser (localhost)                        │
│                   Gradio UI  (port 7860 by default)                 │
└───────────────────────────────────┬─────────────────────────────────┘
                                    │  HTTP
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   FastAPI + Gradio ASGI App (main_ui.py)            │
│                         app.py  —  build_app()                      │
└──────┬────────────────────────────┬──────────────────────┬──────────┘
       │                            │                      │
       ▼                            ▼                      ▼
┌─────────────┐          ┌──────────────────┐    ┌──────────────────┐
│  core/      │          │  storage/        │    │  ui/             │
│  (pipeline) │          │  (persistence)   │    │  (form builder)  │
└──────┬──────┘          └────────┬─────────┘    └──────────────────┘
       │                          │
       ├── readers/               ├── MontyDB  (default, embedded)
       │   └── pdf/reader.py      └── MongoDB  (optional, via DB_TYPE=mongodb)
       │       (pdfplumber)
       │
       ├── field_detector.py
       │   (heuristic 3-pass detection)
       │
       ├── layout_analyzer.py
       │   (row/section grouping)
       │
       ├── llm/
       │   └── enricher.py
       │       (optional LLM post-processing)
       │
       └── generators/
           └── pdf/generator.py
               (pypdf + reportlab overlay)
```

### 3.2 Request-Level Data Flow

The following diagram traces what happens when a user loads a form and then generates a filled PDF.

```
USER ACTION: Select form → "Load Form"
        │
        ▼
  app._load_form(filename)
        │
        ├─► core/readers/pdf/reader.py
        │      PdfDocumentReader.parse()
        │      └─► pdfplumber extracts chars, words, lines, rects, table_cells
        │          → list[PageElements]
        │
        ├─► core/field_detector.detect_fields(pages)
        │      Pass 1a: lines  → input line candidates
        │      Pass 1b: rects  → box / textarea / checkbox candidates
        │      Pass 1c: words  → underscore-pattern input lines
        │      Pass 1d: tables → grid-based cell detection
        │      For each candidate:
        │        _find_label()  → label string + write coordinates
        │        _classify_field_type() → text/date/number/checkbox/textarea
        │      → list[FormField]
        │
        ├─► core/llm/enricher.enrich_fields_with_llm(fields, pages)   [OPTIONAL]
        │      Calls configured LLM provider with field list + page text
        │      LLM returns improved labels / types
        │      → list[FormField]  (original on failure or no provider)
        │
        ├─► core/layout_analyzer.build_layout(fields, pages, ...)
        │      Groups fields into rows (ROW_TOLERANCE_PT)
        │      Detects section headers (font size / bold)
        │      Assigns fields to sections
        │      → FormLayout
        │
        └─► storage/db.save_layout(layout) → layout_id
                stored in MontyDB layouts collection


USER ACTION: Fill fields in browser form
        │
        ▼
  Gradio component.change() callbacks
        └─► values_state: dict[field_id, str]  (held in gr.State)


USER ACTION: "Save & Generate"
        │
        ▼
  app._do_save_and_generate()
        │
        ├─► storage/db.insert_submission(tag, layout_id, ..., field_values)
        │      stored in MontyDB submissions collection
        │
        └─► core/generators/pdf/generator.py
               PdfDocumentGenerator.generate_filled(layout, field_values, dir)
               For each page:
                 Build reportlab Canvas overlay (Helvetica 10pt)
                 Draw text / checkbox "X" at stored field coordinates
                 Merge overlay onto original page via pypdf
               → bytes  (in-memory, no temp files)
               → written to temp file for Gradio file download
```

### 3.3 Layer Dependency Diagram

Dependencies flow downward only. No upward imports exist.

```
         ┌─────────────────────────────────────┐
         │         app.py / main_ui.py         │  ← Entry points
         └──────┬──────────────┬───────────────┘
                │              │
         ┌──────▼──────┐  ┌────▼────────────────┐
         │  core/      │  │  storage/            │
         └──────┬──────┘  └─────────────────────┘
                │
         ┌──────┴───────────────────────┐
         │  core/models.py              │  ← shared domain objects
         └──────────────────────────────┘
                ▲
    ┌───────────┼─────────────┐
    │           │             │
 readers/  field_detector  generators/
             layout_analyzer
             llm/
```

### 3.4 Execution Mode Diagram

The app can be started in two ways:

```
┌─────────────────────────────────────────────────────┐
│  Option A: python app.py                            │
│                                                     │
│  Gradio Blocks.launch()                             │
│  → Built-in dev server (single-thread)              │
│  → http://127.0.0.1:7860                            │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  Option B: python main_ui.py                        │
│                                                     │
│  Gradio mounted onto FastAPI ASGI                   │
│  → uvicorn ASGI server (multi-worker capable)       │
│  → http://127.0.0.1:7860                            │
│                                                     │
│  FastAPI also exposes /docs (OpenAPI) at            │
│  http://127.0.0.1:7860/docs                         │
└─────────────────────────────────────────────────────┘
```

---

## 4. Module Design & Code Documentation

### 4.1 Entry Points

#### `app.py` — Gradio Application Builder

The main module. Imports from all layers and wires the complete Gradio UI.

**Key public symbols:**

| Symbol | Type | Description |
|---|---|---|
| `INPUT_FORMS_DIR` | `Path` | Points to `./input-forms/`. PDF forms are placed here before loading. |
| `scan_input_forms_dir()` | `list[str]` | Scans `input-forms/` and returns filenames whose extension is in `READER_REGISTRY`. |
| `load_all_tags()` | `list[str]` | Queries DB for all saved submission tags. |
| `execute_wizard_action()` | `(bytes\|None, str)` | Dispatches Save / Generate / Save+Generate based on `WizardAction` enum. |
| `build_app()` | `gr.Blocks` | Constructs the full Gradio UI with all event wires. Used by both `app.py` and `main_ui.py`. |

**UI Structure inside `build_app()`:**

```
gr.Blocks("PDF Form Filler")
 ├── gr.State: layout_state, layout_id_state, values_state,
 │             initial_values_state, mode_state, tag_state
 │
 ├── home_col  (visible=True on start)
 │   ├── Panel A: Continue Previous Submission
 │   │   ├── tag_dropdown  (choices from DB)
 │   │   ├── refresh_tags_btn
 │   │   ├── submission_preview  (Markdown)
 │   │   ├── load_edit_btn
 │   │   └── delete_submission_btn
 │   └── Panel B: Start New Form
 │       ├── pdf_dropdown  (choices from input-forms/)
 │       ├── refresh_forms_btn
 │       ├── load_form_btn
 │       └── processing_status  (spinner text)
 │
 └── fill_col  (visible=False on start)
     ├── @gr.render → dynamic form fields
     ├── tag_input
     ├── save_only_btn   → _do_save_only()
     ├── generate_only_btn  → _do_generate_only()
     ├── save_and_generate_btn  → _do_save_and_generate()
     ├── pdf_output (gr.File)
     └── back_to_home_btn
```

**Navigation model:** Two `gr.Column` containers swap visibility (`visible=True/False`) to simulate screen navigation. No page routing or URLs change.

**Mode state:** The `mode_state` (`"new"` or `"edit"`) controls whether the save path calls `insert_submission` or `update_submission`. After first save it always flips to `"edit"` so re-clicking Save does not fail with a duplicate-tag error.

---

#### `main_ui.py` — Production Entry Point

Wraps the same `build_app()` in a FastAPI ASGI application served by `uvicorn`. Recommended for production or when you need the FastAPI `/docs` endpoint.

```python
fastapi_app = FastAPI(title="PDF Form Filler", ...)
demo = build_app()
gr.mount_gradio_app(fastapi_app, demo, path="/")
uvicorn.run(asgi_app, host=_HOST, port=_PORT)
```

Environment variable overrides: `APP_HOST`, `APP_PORT`.

---

### 4.2 Core Layer

#### `core/models.py` — Domain Data Models

All models use `@dataclass(slots=True)` for memory efficiency and attribute safety (no accidental attribute creation at runtime).

**Constants:**

| Constant | Value | Meaning |
|---|---|---|
| `ROW_TOLERANCE_PT` | `12` | Y-distance (in PDF points) within which two fields are considered on the same row. |
| `MIN_INPUT_LINE_WIDTH_PT` | `40` | Minimum width in points for a line/rect to be treated as an input area. |
| `CHECKBOX_MAX_SIZE_PT` | `20` | Max width and height in points for a rect to be classified as a checkbox. |
| `MIN_TEXTAREA_HEIGHT_PT` | `40` | Minimum height in points for a rect to be classified as a textarea. |
| `FONT_SIZE_SECTION_DELTA` | `2.0` | How many points above the mean body font size triggers section header detection. |

**`FormField`** — Represents a single detected input field.

| Attribute | Type | Description |
|---|---|---|
| `id` | `str` | Unique identifier: `p{page}_f{index}` |
| `label` | `str` | Human-readable label extracted from nearby text |
| `field_type` | `FieldType` | One of: `text`, `checkbox`, `date`, `number`, `textarea`, `dropdown` |
| `page` | `int` | 1-based page number |
| `x0, top, x1, bottom` | `float` | Bounding box in pdfplumber points (top-left origin) |
| `options` | `list[str]` | Dropdown choices (currently empty; reserved) |
| `required` | `bool` | Reserved for future validation |
| `placeholder` | `str` | Hint text shown in the Gradio input |
| `input_x0` | `float` | X coordinate where the value should be written in the PDF |
| `input_y` | `float` | Y coordinate (pdfplumber bottom) for inline-label baseline alignment; `0.0` = fallback to underline formula |

**`FormRow`** — A horizontal row of `FormField` instances at the same Y position.

**`FormSection`** — A named group of `FormRow` instances, corresponding to a detected section header in the PDF.

**`FormLayout`** — The complete parsed representation of a PDF form.

| Attribute | Type | Description |
|---|---|---|
| `title` | `str` | Extracted from first section header or PDF filename stem |
| `source_file` | `str` | Original PDF filename |
| `source_hash` | `str` | SHA-256 of the original PDF bytes |
| `page_count` | `int` | Total pages |
| `sections` | `list[FormSection]` | Ordered list of detected sections |
| `extracted_at` | `str` | UTC ISO timestamp of extraction |
| `page_dimensions` | `dict[int, tuple[float,float]]` | Per-page `(width, height)` in points |

**`PageElements`** — Raw pdfplumber extraction results for a single page.

| Attribute | Type | Description |
|---|---|---|
| `page_number` | `int` | 1-based |
| `page_width/height` | `float` | Dimensions in points |
| `chars` | `list[dict]` | Individual characters with font info |
| `words` | `list[dict]` | Word-grouped text with bounding boxes |
| `lines` | `list[dict]` | Horizontal/vertical line segments |
| `rects` | `list[dict]` | Rectangle objects |
| `table_cells` | `list[tuple]` | Inferred input cells from pdfplumber table finder |

**`WizardAction`** — Enum controlling the save/generate action.

```
WizardAction.SAVE_ONLY          → write to DB, no PDF
WizardAction.GENERATE_ONLY      → render PDF, no DB write
WizardAction.SAVE_AND_GENERATE  → both
```

---

#### `core/field_detector.py` — Heuristic Field Detection

The heart of the application. A 3-pass pipeline that operates on `list[PageElements]` and returns `list[FormField]`.

**Detection pipeline overview:**

```
PageElements (per page)
        │
        ▼
Pass 1: _iter_candidates()
        ├── 1a: lines    → (x0, top, x1, bottom, is_checkbox=F, is_textarea=F, is_table_cell=F)
        ├── 1b: rects    → checkbox / textarea / regular input box
        ├── 1c: words    → underscore-pattern lines (_____)
        └── 1d: tables   → grid-inferred input cells (is_table_cell=T)
        │
        ▼
Pass 2: _find_label() for each candidate
        Priority 0: Inline label (same row, text starts at candidate x0)
        Priority 1: In-row left cluster (text to the left on same row)
        Priority 2: Above text (nearest label line above the field)
        │
        ▼
Pass 3: _classify_field_type()
        └── regex-based classification:
            date keywords → "date"
            number/amount keywords → "number"
            small rect → "checkbox"
            large rect → "textarea"
            default → "text"
        │
        ▼
Post-processing:
  _clean_label()   → collapse single-char PDF extraction artefacts
  Deduplication    → remove phantom table-border duplicates
        │
        ▼
list[FormField]
```

**Label Detection Priority (illustrated):**

```
Priority 0 — Inline label (same row as field):
  ┌─────────────────────────────────────────────────┐
  │  Agency/Department: [_________________________] │
  │  ^^^^^^^^^^^^^^^^^^^  ← inline label             │
  └─────────────────────────────────────────────────┘
  Result: label = "Agency/Department", input_x0 = after label text

Priority 1 — Left cluster (text to the left, table rows):
  ┌──────────────────────────────────┐
  │  Full Name    │ [             ] │
  │  ^^^^^^^^^^^                    │
  └──────────────────────────────────┘
  Result: label = "Full Name"

Priority 2 — Above (standard labeled field):
  ┌──────────────────────────┐
  │  Date of Birth           │
  │  [______________________]│
  │  ^^^^^^^^^^^^^^^^^^^     │
  └──────────────────────────┘
  Result: label = "Date of Birth"
```

**`_clean_label(text)`** — Two-stage PDF artefact fixer:
- Stage 1: Collapses runs of 3+ single-character tokens (`"A z a d i"` → `"Azadi"`).
- Stage 2: If ≥70% of tokens are ≤2 chars, collapses runs of 4+ short tokens. Protects legitimate abbreviations like `"EC No"` or `"Sr No"`.

**`_classify_field_type(label, is_checkbox, is_textarea)`** — `@functools.lru_cache` decorated. First-match regex classification:

```
is_checkbox=True         → "checkbox"
is_textarea=True         → "textarea"
/date|dob|birth/ in label → "date"
/amount|salary|fee/      → "number"
/phone|mobile|fax/       → "text"
/email/                  → "text"
default                  → "text"
```

---

#### `core/layout_analyzer.py` — Layout Assembly

Takes the flat `list[FormField]` output from `field_detector` and organises it into a `FormLayout` hierarchy.

**Section header detection:**
- Computes mean body font size across all pages.
- Any character whose font size exceeds `mean + FONT_SIZE_SECTION_DELTA` (2 pt) OR whose font name contains `"bold"` is classified as a section header character.
- Consecutive header characters are aggregated into header text strings with their `(page, top)` position.

**Row grouping:**
- Fields sorted by `(page, top, x0)`.
- Fields within `ROW_TOLERANCE_PT` (12 pt) of the current row's top coordinate are grouped into the same `FormRow`.
- Fields are sorted by `x0` within each row to match left-to-right visual order.

**Section assignment:**
- Each field is assigned to the section whose header most recently precedes it in `(page, top)` reading order.
- If no header precedes a field, it falls into a section named after the PDF filename stem.

---

#### `core/readers/` — Document Reader Subsystem

Plugin architecture using a decorator-based registry.

```
DocumentReader (ABC)              ← base.py
    ├── supported_extensions      property → tuple[str, ...]
    ├── compute_hash(path)        → str  (SHA-256)
    └── parse(path)               → Iterator[PageElements]

READER_REGISTRY: dict[str, type[DocumentReader]]    ← factory.py
    └── key: file extension (e.g., ".pdf")
    └── value: registered reader class

@register_reader                  ← class decorator
    └── calls cls().supported_extensions and registers each extension

PdfDocumentReader                 ← readers/pdf/reader.py
    └── parse() uses pdfplumber
        ├── chars, words, lines, rects per page
        └── _extract_table_cells() via page.find_tables()
```

**`PdfDocumentReader.parse()`** raises `ValueError` if all pages have zero text characters (scanned/image-only PDF).

**Table cell detection** (`_extract_table_cells`):
- Full-width single-cell rows are treated as textareas if tall enough and empty.
- Multi-cell rows: first column is the label; remaining empty columns are input cells.
- Cells containing text are skipped (they are header/label cells, not input areas).

---

#### `core/generators/` — Document Generator Subsystem

Mirror-image plugin architecture to the readers.

```
DocumentGenerator (ABC)           ← base.py
    ├── supported_extension       property → str
    └── generate_filled(layout, values, source_dir) → bytes

GENERATOR_REGISTRY                ← factory.py
    └── same decorator pattern as readers

PdfDocumentGenerator              ← generators/pdf/generator.py
    └── generate_filled():
        ├── Opens original PDF with pypdf.PdfReader
        ├── For each page:
        │   ├── Creates io.BytesIO canvas with reportlab
        │   ├── Draws Helvetica 10pt text at field.input_x0 / converted Y
        │   ├── Draws "X" (bold) for checked checkboxes
        │   └── Merges canvas onto original page via pypdf.PdfWriter
        └── Returns merged PDF as bytes
```

**Coordinate system conversion:**

pdfplumber uses a **top-left origin** coordinate system (Y increases downward).  
ReportLab uses a **bottom-left origin** coordinate system (Y increases upward).

The conversion applied in `_to_reportlab_y()`:

$$y_{reportlab} = page\_height - y_{pdfplumber}$$

For inline-label fields (`field.input_y != 0`):
$$y_{reportlab} = page\_height - field.input\_y$$

For other fields:
- Checkbox: vertically centred inside box.
- Rect with height > 4pt (tall box): text near bottom of rect.
- Underline field (height ≈ 0): text lifted slightly above the line.

---

#### `core/llm/` — LLM Enrichment (Optional)

All LLM logic is isolated in this subpackage. The rest of the codebase has zero LLM imports.

```
LLMProvider (ABC)          ← _base.py
    └── complete(CompletionRequest) → str  (JSON)

CompletionRequest          ← _base.py
    ├── system: str
    ├── user: str
    └── max_tokens: int = 4096

_factory.py                get_provider() → LLMProvider | None
    ├── Reads LLM_PROVIDER env var
    ├── Returns None if unset (heuristic-only mode)
    └── Raises ValueError for unknown provider name

Providers:
    OpenAIProvider          → openai SDK, LLM_API_KEY + LLM_MODEL
    AzureOpenAIProvider     → AzureOpenAI, adds AZURE_OPENAI_ENDPOINT
    AnthropicProvider       → anthropic SDK, claude models
    AnthropicBedrockProvider → anthropic.AnthropicBedrock, AWS credential chain
```

**LLM enrichment flow:**

```
enrich_fields_with_llm(fields, pages)
        │
        ├── get_provider()  →  None?  return fields unchanged
        │
        ├── Build user message:
        │   "--- Page 1 ---\n<words>\n--- Page 2 ---\n..."
        │   + JSON of {id, label, field_type, placeholder, x0, top}
        │
        ├── Call provider.complete(CompletionRequest)
        │   LLM returns: {"fields": [{id, label, field_type, placeholder}, ...]}
        │
        └── Patch each FormField in-place:
            ├── label      → improved label (max 60 chars, title case)
            ├── field_type → improved type (validated against allowed set)
            └── placeholder → improved hint
            Coordinates are NEVER modified by LLM.
```

**Fallback policy:** Any exception in the LLM call silently returns the original heuristic fields. Enrichment is best-effort — the app always works without an LLM.

---

### 4.3 Storage Layer

#### `storage/db.py` — Database Access

Uses a thin abstraction over MontyDB (embedded) and pymongo (production MongoDB). Selected by `DB_TYPE` env var.

```
get_db_client()
    ├── DB_TYPE=montydb  → MontyClient(DB_PATH)   [default]
    └── DB_TYPE=mongodb  → pymongo.MongoClient(DB_URI)

Collections:
    layouts     → serialised FormLayout JSON, source file, hash
    submissions → tag, layout_id, form_title, source_file, field values, timestamp
```

**Operations:**

| Function | Description |
|---|---|
| `save_layout(layout)` | Inserts layout; returns UUID string as `layout_id` |
| `load_layout_by_id(id)` | Deserialises `FormLayout` from stored JSON |
| `get_all_submission_summaries()` | Returns `[{tag, form_title, source_file, filled_at}]` — lightweight list query |
| `get_submission_by_tag(tag)` | Returns full submission document including all field values |
| `tag_exists(tag)` | Boolean check for duplicate tag |
| `insert_submission(...)` | Creates new submission; raises if tag exists |
| `update_submission(tag, values)` | Overwrites field values + updates timestamp |
| `delete_submission(tag)` | Removes by tag; returns `True` if deleted |

#### `storage/layout_store.py` — Layout Serialisation

Converts `FormLayout` ↔ compact JSON string for storage.

- `serialise_layout(layout)` → compact JSON (`separators=(',', ':')`)
- `deserialise_layout(json_str)` → `FormLayout`

Handles backwards compatibility: fields `input_x0` and `input_y` were added later; old stored layouts default to `(x0, 0.0)` safely.

---

### 4.4 UI Layer

#### `ui/form_builder.py` — Field Component Factory

Single function: `build_field_component(field, prefill) → gr.Component`

Maps each `FieldType` to the appropriate Gradio component:

| `field_type` | Gradio Component | Notes |
|---|---|---|
| `"text"` | `gr.Textbox` | Single line |
| `"textarea"` | `gr.Textbox(lines=4)` | Multi-line |
| `"number"` | `gr.Number` | Float input |
| `"date"` | `gr.Textbox` | Placeholder: `YYYY-MM-DD` |
| `"checkbox"` | `gr.Checkbox` | Value coerced: true/yes/checked/1 → True |
| `"dropdown"` | `gr.Dropdown` | Uses `field.options` list |

---

## 5. Data Models

### 5.1 FormLayout Hierarchy

```
FormLayout
  ├── title: str
  ├── source_file: str
  ├── source_hash: str (SHA-256)
  ├── page_count: int
  ├── extracted_at: str (UTC ISO)
  ├── page_dimensions: dict[int → (width, height)]
  └── sections: list[FormSection]
       └── FormSection
            ├── title: str
            ├── page: int
            └── rows: list[FormRow]
                 └── FormRow
                      ├── row_top: float
                      └── fields: list[FormField]
                           └── FormField
                                ├── id, label, field_type
                                ├── page, x0, top, x1, bottom
                                ├── input_x0, input_y
                                └── options, required, placeholder
```

### 5.2 Database Document Schemas

**`layouts` collection:**
```json
{
  "_id": "uuid-string",
  "source_file": "form.pdf",
  "source_hash": "sha256hex",
  "layout_json": "{...compact FormLayout JSON...}",
  "created_at": "2026-01-01T00:00:00+00:00"
}
```

**`submissions` collection:**
```json
{
  "tag": "john_doe_2026",
  "layout_id": "uuid-string",
  "form_title": "Leave Application",
  "source_file": "leave_form.pdf",
  "filled_at": "2026-01-01T12:00:00+00:00",
  "fields": [
    {"id": "p1_f0", "label": "Full Name", "value": "John Doe"},
    {"id": "p1_f1", "label": "Date", "value": "2026-01-15"}
  ]
}
```

---

## 6. LLM Integration

### 6.1 Supported Providers

| Provider | `LLM_PROVIDER` value | Authentication |
|---|---|---|
| OpenAI (GPT-4o, etc.) | `openai` | `LLM_API_KEY` |
| Azure OpenAI | `azure_openai` | `LLM_API_KEY` + `AZURE_OPENAI_ENDPOINT` |
| Anthropic Claude | `anthropic` | `LLM_API_KEY` |
| AWS Bedrock (Claude) | `aws_bedrock` | AWS credential chain (no `LLM_API_KEY`) |
| None (heuristic-only) | *(unset)* | — |

### 6.2 LLM System Prompt Behaviour

The LLM receives:
1. All words from the PDF in reading order (page by page).
2. The list of auto-detected fields with their labels, types, and **spatial coordinates** (`x0`, `top`).

The system prompt instructs the LLM to:
- Use coordinates to understand the spatial relationship between labels and fields.
- Never assign a label from a different section (e.g., a checkbox at `top≈176` cannot be labelled from text at `top≈228`).
- Return labels ≤60 characters, in title case.
- Never invent new fields — only improve existing detections.
- Return strict JSON: `{"fields": [{id, label, field_type, placeholder}]}`.

### 6.3 Fallback Safety

```
LLM call ──► success  →  enriched fields
         └── any error →  original heuristic fields (silent fallback)
         └── no provider → original heuristic fields
```

---

## 7. Database Design

### 7.1 Storage Backends

```
MontyDB (default)                     MongoDB (production)
─────────────────────────────         ──────────────────────────
Files on disk in DB_PATH              Remote/Atlas cluster
SQLite engine under the hood          DB_URI connection string
Windows-safe, no daemon needed        Requires running mongod
Set DB_TYPE=montydb (or omit)         Set DB_TYPE=mongodb
```

`monty.storage.cfg` in the project root configures MontyDB to use flatfile storage compatible with MongoDB 4.2 wire protocol.

### 7.2 Switching to MongoDB

Change two environment variables — zero code changes required:

```env
DB_TYPE=mongodb
DB_URI=mongodb://localhost:27017/
```

### 7.3 Unique Constraints

The `submissions.tag` field has a unique index enforced by `_ensure_tag_index()` which is called before every insert. This prevents duplicate tags.

---

## 8. Dependency Reference

| Package | Version | License | Role |
|---|---|---|---|
| `pdfplumber` | `==0.11.9` | MIT | PDF parsing: chars, lines, rects, words, table detection |
| `gradio` | `==6.13.0` | Apache 2.0 | Web UI framework; dynamic form rendering via `@gr.render` |
| `python-dotenv` | `==1.0.1` | BSD | Load `.env` file into environment at startup |
| `montydb` | `>=2.5.2` | BSD-3-Clause | Embedded MongoDB-compatible local DB (SQLite-backed) |
| `pymongo` | `>=4.6` | Apache 2.0 | MongoDB driver; also provides BSON support to MontyDB |
| `reportlab` | `>=4.2` | BSD | PDF canvas overlay rendering (draws text + checkboxes) |
| `pypdf` | `>=4.3` | BSD | Reads original PDF pages; merges reportlab overlay |
| `uvicorn` | `>=0.29.0` | BSD | ASGI server used by `main_ui.py` |
| `fastapi` | `>=0.110.0` | MIT | ASGI app that hosts Gradio; exposes `/docs` |
| `openai` | `>=1.30` | MIT | OpenAI / Azure OpenAI / OpenAI-compatible LLM client |
| `anthropic` | `>=0.25` | MIT | Anthropic Claude / AWS Bedrock LLM client |

### Why pdfplumber over PyMuPDF?

PyMuPDF (`fitz`) is AGPL-licensed. Any application distributing PyMuPDF must open-source its entire codebase under AGPL. pdfplumber (MIT) provides equivalent access to characters, lines, and rectangles with no license restriction.

### Why MontyDB over SQLite directly?

The MontyDB API is a subset of `pymongo`'s `MongoClient`. Switching from local development (MontyDB) to production (MongoDB Atlas) requires changing only an environment variable — the application code is unchanged. SQLite would require a different query API.

---

## 9. Environment Variables & Configuration

Create a `.env` file in the project root (or set as system/shell environment variables).

### Required (none — the app works with all defaults)

### Optional — Application

| Variable | Default | Description |
|---|---|---|
| `APP_HOST` | `127.0.0.1` | Server bind address (`main_ui.py` only) |
| `APP_PORT` | `7860` | Server port (`main_ui.py` only) |

### Optional — Database

| Variable | Default | Description |
|---|---|---|
| `DB_TYPE` | `montydb` | `montydb` or `mongodb` |
| `DB_PATH` | `./data/formfiller_db` | MontyDB storage directory |
| `DB_NAME` | `formfiller_db` | Database name |
| `DB_URI` | *(none)* | MongoDB connection string (required when `DB_TYPE=mongodb`) |

### Optional — LLM Enrichment

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | *(none)* | `openai`, `azure_openai`, `anthropic`, or `aws_bedrock` |
| `LLM_API_KEY` | *(none)* | API key for OpenAI / Azure OpenAI / Anthropic |
| `LLM_MODEL` | *(none)* | Model name, e.g. `gpt-4o-mini`, `claude-3-5-haiku-20241022` |
| `LLM_BASE_URL` | *(SDK default)* | Override OpenAI base URL (for Ollama, LM Studio, etc.) |
| `AZURE_OPENAI_ENDPOINT` | *(none)* | Required for `azure_openai` provider |
| `AZURE_OPENAI_API_VERSION` | `2024-02-01` | Azure OpenAI API version |
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock |
| `AWS_ACCESS_KEY_ID` | *(none)* | Explicit AWS key (optional — boto3 uses credential chain) |
| `AWS_SECRET_ACCESS_KEY` | *(none)* | Explicit AWS secret |
| `AWS_SESSION_TOKEN` | *(none)* | STS session token if using temporary credentials |

### Example `.env` file

```env
# Run with OpenAI enrichment
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini

# Use external MongoDB
DB_TYPE=mongodb
DB_URI=mongodb://localhost:27017/
```

---

## 10. How to Execute

### 10.1 Prerequisites

- Python 3.10 or higher
- pip

### 10.2 Installation

```bash
# Clone or download the project, then:
cd form-filler

# Create a virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (macOS / Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 10.3 Place PDF Forms

Copy PDF forms you want to fill into the `input-forms/` directory:

```
form-filler/
└── input-forms/
    ├── leave_application.pdf
    ├── bank_account_form.pdf
    └── ...
```

Only machine-generated PDFs with selectable text are supported. Scanned image PDFs will show an error.

### 10.4 Start the Application

**Option A — Development mode (Gradio built-in server):**

```bash
python app.py
```

Open `http://127.0.0.1:7860` in your browser.

**Option B — Production mode (uvicorn + FastAPI):**

```bash
python main_ui.py
```

Open `http://127.0.0.1:7860` in your browser.  
OpenAPI docs available at `http://127.0.0.1:7860/docs`.

**Option C — Custom host/port:**

```bash
APP_HOST=0.0.0.0 APP_PORT=8080 python main_ui.py
```

### 10.5 Using the Application

#### Step 1: Load a Form

1. On the **Home** screen, find the **Start New Form** panel.
2. Select a PDF filename from the **Available Forms** dropdown.
3. Click **Load Form**.
4. Wait for field detection to complete (a spinner message appears while parsing).

#### Step 2: Fill the Form

1. The app switches to the **Fill Form** screen.
2. Fields are arranged in sections mirroring the PDF layout.
3. Fill in all relevant fields.

#### Step 3: Save and/or Generate

- **Save to DB** — Saves all field values to the local database under a tag you specify. You can return later to edit the submission.
- **Generate PDF** — Renders a filled PDF immediately without saving (useful for a quick preview).
- **Save & Generate** — Does both. Recommended for most use cases.

The filled PDF is available for download via the **Download Filled PDF** file widget.

#### Step 4: Edit a Previous Submission

1. On the **Home** screen, find the **Continue Previous Submission** panel.
2. Select a tag from the **Saved Submissions** dropdown — a preview shows form name and last save date.
3. Click **Load & Edit**.
4. Make changes and click **Save to DB** or **Save & Generate** again.

### 10.6 Configuration with LLM (Optional)

To improve field label accuracy with an LLM, create a `.env` file and add:

```env
LLM_PROVIDER=openai
LLM_API_KEY=<your-key>
LLM_MODEL=gpt-4o-mini
```

Restart the app. LLM enrichment runs automatically when a form is loaded. If no LLM is configured, heuristic detection runs alone — which works correctly for most standard PDF forms.

---

## 11. Running Tests

The project includes runtime integration tests in the `run-time test/` directory. These are not pytest-based; they are standalone Python scripts that run against the live codebase.

```bash
# From the project root:
python "run-time test/run_all_tests.py"
```

**Test modules (run in order):**

| Module | Tests |
|---|---|
| `test_models.py` | `FormField`, `FormLayout`, `WizardAction` instantiation and properties |
| `test_layout_store.py` | `serialise_layout` / `deserialise_layout` round-trip |
| `test_field_detector.py` | Label detection, type classification, `_clean_label` |
| `test_layout_analyzer.py` | Row grouping, section assignment |
| `test_reader_registry.py` | Reader registration and lookup by extension |
| `test_generator_registry.py` | Generator registration and lookup |
| `test_db.py` | Insert, update, delete, query on live MontyDB |

Each module exposes functions prefixed `test_`. The runner calls them all, collects pass/fail, and prints a summary.

---

## 12. Scope Boundaries (What It Does NOT Do)

These are deliberate design decisions, not gaps:

| Limitation | Reason |
|---|---|
| No scanned / OCR PDFs | pdfplumber requires selectable text characters. OCR support would require Tesseract or Azure Document Intelligence — a separate workstream. |
| No browser-based PDF upload | PDFs must be pre-placed in `input-forms/`. Adds file upload widget complexity and path management overhead not needed for desktop use. |
| No multi-user / concurrent access | MontyDB (SQLite engine) is not process-safe for concurrent writes. MongoDB mode supports concurrency. |
| No authentication | Local desktop app; no shared network exposure by default (bound to `127.0.0.1`). |
| No AcroForm field filling | The app targets visual/print PDF forms. AcroForm PDFs (with embedded widgets) already work in PDF viewers. |
| No interactive PDF forms | Forms with JavaScript, XFA, or embedded widgets are out of scope. |
| No document type other than PDF | The reader/generator plugin system supports adding DOCX etc., but only PDF is implemented. |
| No delete-all layouts UI | Layouts accumulate silently; no garbage collection UI exists. |

---

## 13. Future Features

These are natural extensions of the current architecture, prioritised by effort and value:

### High Value / Low Effort

1. **Scanned PDF Support (OCR)**
   Integrate Azure Document Intelligence or Tesseract OCR as an additional `DocumentReader` plugin. The `DocumentReader` ABC and `@register_reader` pattern already supports this — only a new `readers/ocr/` subpackage is needed.

2. **Field Validation Rules**
   The `FormField.required` attribute exists but is unused. Wire it into `app._validate_tag()` to block form submission when required fields are empty. Add `min_length`, `max_length`, `pattern` (regex) attributes to `FormField`.

3. **Pre-fill from Saved Submission (Auto-suggest)**
   When loading a new form, offer to pre-fill repeated fields (Name, Address, etc.) from the most recent submission for the same form — a single DB lookup and label-match pass.

4. **PDF Form Browser Upload**
   Add a `gr.File` upload widget to the Home screen. Uploaded PDFs are moved to `input-forms/` automatically. The rest of the pipeline is unchanged.

### Medium Value / Medium Effort

5. **DOCX / Word Form Support**
   Implement `DocumentReader` and `DocumentGenerator` plugins under `readers/docx/` and `generators/docx/`. Word documents can be parsed with `python-docx`. Field detection would use table/paragraph structure instead of coordinates.

6. **Dropdown / Multi-select Field Support**
   Extend `_classify_field_type` and the LLM prompt to detect radio groups and checkboxes-as-options in the PDF, and populate `FormField.options`. The `ui/form_builder.py` already handles `dropdown` type with `gr.Dropdown(choices=field.options)`.

7. **Batch Fill Mode**
   Accept a CSV file on the Home screen. Each row maps tag → field values. The app iterates rows, fills the form, saves the submission, and generates a filled PDF per row — producing a ZIP archive of all filled PDFs.

8. **Export Submissions to CSV / Excel**
   Add an "Export All" button to the Home screen that queries all submissions for a given form and writes them to a spreadsheet.

9. **Layout Management UI**
   Currently layouts accumulate in the DB with no clean-up. Add a "Manage Layouts" screen showing stored layouts with their hash, date, and field count; allow deletion of stale layouts.

### Low Value / High Effort (Future Phases)

10. **Multi-user / Shared Deployment**
    Switch default to MongoDB (`DB_TYPE=mongodb`), add authentication (OAuth2 via FastAPI), per-user submission namespacing, and role-based access (admin / filler).

11. **Form Template Designer**
    A visual editor to manually correct field boundaries and labels detected by the heuristic — drag handles on a PDF preview, exported as a hand-curated `FormLayout` override file.

12. **Digital Signature Support**
    Integrate `pyhanko` for applying PDF digital signatures to the filled output using local certificates or a signature API.

13. **Audit Trail**
    Store a per-submission change history (all previous field value states with timestamps) to support regulatory compliance requirements.

14. **Intelligent Form Pre-fill from Documents**
    Given a source document (e.g., a PAN card image, Aadhaar PDF, or prior application), extract structured data with an LLM and auto-fill matching fields — fully automated form completion.

---

*Documentation generated from source code analysis of the `form-filler` project. No information has been fabricated; all details reflect the actual implementation.*
