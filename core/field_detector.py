from __future__ import annotations

import functools
import re
from typing import Iterator

from core.models import (
    CHECKBOX_MAX_SIZE_PT,
    FONT_SIZE_SECTION_DELTA,
    MIN_INPUT_LINE_WIDTH_PT,
    MIN_TEXTAREA_HEIGHT_PT,
    ROW_TOLERANCE_PT,
    FieldType,
    FormField,
    PageElements,
)

# ── Compiled regex patterns (module-level, never inside loops) ─────────────────
_RE_UNDERSCORES: re.Pattern[str] = re.compile(r'^[_]{3,}$')
_RE_BOLD: re.Pattern[str] = re.compile(r'bold', re.IGNORECASE)
_RE_DATE: re.Pattern[str] = re.compile(r'\b(date|dob|d\.o\.b|birth)\b', re.IGNORECASE)
_RE_NUMBER: re.Pattern[str] = re.compile(
    r'\b(amount|total|salary|income|fee|price|cost)\b', re.IGNORECASE
)
_RE_PHONE: re.Pattern[str] = re.compile(r'\b(phone|tel|mobile|fax)\b', re.IGNORECASE)
_RE_EMAIL: re.Pattern[str] = re.compile(r'\b(email|e-mail)\b', re.IGNORECASE)

# ── Tolerance constants ────────────────────────────────────────────────────────
_LABEL_ABOVE_Y_TOLERANCE: float = 5.0
_LABEL_ABOVE_X_TOLERANCE: float = 20.0
_LABEL_ABOVE_MAX_DIST_PT: float = 60.0   # max distance above candidate to search
_LABEL_LINE_BAND_PT: float = 4.0          # band to group words on the same label line above
_LABEL_LEFT_X_TOLERANCE: float = 5.0
_LABEL_LEFT_MAX_DIST_PT: float = 300.0   # max horizontal distance to look left for row labels
_LABEL_LEFT_CELL_GAP_PT: float = 40.0    # gap between words that signals a table cell boundary
_LABEL_INLINE_X_TOLERANCE: float = 10.0  # word may start this far from field.x0 to be inline
_LABEL_RIGHT_GAP_PT: float = 15.0         # max gap between checkbox right edge and its right-side label
_LINE_HEIGHT_MAX_PT: float = 3.0


def _clean_label(text: str) -> str:
    """
    Post-process an extracted label to fix PDF text-extraction artefacts.

    Two-stage approach, from most to least conservative:

    Stage 1 — Single-char runs (unambiguous artefact):
        Collapse runs of 3+ **strictly single-character** tokens, e.g.
        "A z a d i" → "Azadi".  Single-char tokens in a run are never
        legitimate words; real abbreviations are ≥ 2 chars ("EC", "No").

    Stage 2 — Mixed short-token noise (fallback for partially-spaced fonts):
        Only activates when ≥ 70 % of the total tokens are ≤ 2 chars — i.e.
        the *whole* string looks like noise, not an isolated pair of short
        abbreviations.  In that case collapse runs of 4+ ≤ 2-char tokens.
        This catches fragments like "mr it M ah" (from "Amrit Mahotsav")
        while leaving alone real labels such as "EC No" or "Sr No DD No"
        where short tokens are a small minority.

    Finally, strip leading non-alphanumeric noise (e.g. "7° ").
    """
    tokens = text.split()
    if not tokens:
        return text

    def _collapse_runs(toks: list[str], max_len: int, min_run: int) -> list[str]:
        result: list[str] = []
        run: list[str] = []
        for tok in toks:
            if len(tok) <= max_len:
                run.append(tok)
            else:
                result.append("".join(run) if len(run) >= min_run else " ".join(run))
                run = []
                result.append(tok)
        result.append("".join(run) if len(run) >= min_run else " ".join(run))
        # Re-split so joined runs become a single token and spaces are normalised
        return " ".join(result).split()

    # Stage 1: strictly single-char runs of 3+
    tokens = _collapse_runs(tokens, max_len=1, min_run=3)

    # Stage 2: ≤2-char runs of 4+, only when the whole label looks like noise
    if len(tokens) >= 4:
        short_ratio = sum(1 for t in tokens if len(t) <= 2) / len(tokens)
        if short_ratio >= 0.70:
            tokens = _collapse_runs(tokens, max_len=2, min_run=4)

    text = " ".join(tokens)
    # Strip leading non-alphanumeric noise
    text = re.sub(r'^[^a-zA-Z0-9]+', '', text).strip()
    return text


@functools.lru_cache(maxsize=256)
def _classify_field_type(label: str, is_checkbox: bool, is_textarea: bool) -> FieldType:
    """
    Deterministic field type classification.
    lru_cache: safe because label is immutable str, booleans are hashable.
    First match wins.
    """
    if is_checkbox:
        return "checkbox"
    if is_textarea:
        return "textarea"
    if _RE_DATE.search(label):
        return "date"
    if _RE_NUMBER.search(label):
        return "number"
    if _RE_PHONE.search(label):
        return "text"
    if _RE_EMAIL.search(label):
        return "text"
    return "text"


def _get_placeholder(label: str) -> str:
    """Return a helpful placeholder string based on label heuristics."""
    if _RE_PHONE.search(label):
        return "e.g. +1-555-000-0000"
    if _RE_EMAIL.search(label):
        return "e.g. user@example.com"
    if _RE_DATE.search(label):
        return "YYYY-MM-DD"
    return ""


def _find_label(
    candidate_x0: float,
    candidate_top: float,
    candidate_x1: float,
    candidate_bottom: float,
    words: list[dict],
    is_checkbox: bool = False,
    y_tolerance: float = ROW_TOLERANCE_PT,
) -> tuple[str, float, float]:
    """
    Find the label for a candidate input area.
    Returns (label_str, inline_x1, inline_word_bottom).

    inline_x1 and inline_word_bottom are non-zero only when an inline label is
    found (Priority 0).  The caller uses these to compute:
      input_x0 = inline_x1   (write value after the label text)
      input_y  = inline_word_bottom  (write at same baseline as label word)

    Priority:
      0. Inline label — text at the same y-level whose x0 aligns with the
         candidate's x0 (±_LABEL_INLINE_X_TOLERANCE).  Handles table cells where
         label and blank area share the same cell row, e.g.:
             "Agency/Department: [______]  Employee Name: [______]"
      1. Left cluster — rightmost contiguous cluster of words to the left that
         vertically overlap the candidate.
      2. Above — nearest label line above the candidate within horizontal bounds.

    Returns ("", 0.0, 0.0) if no label found.
    """
    inline: list[tuple[float, float, str]] = []              # (x0, x1, text) seeds
    in_row_left: list[tuple[float, float, float, str]] = []  # (top, x0, x1, text)
    above: list[tuple[float, float, str]] = []               # (dist, x0, text)
    right_side: list[tuple[float, float, str]] = []          # (x0, x1, text) for checkbox right-side labels

    for word in words:
        w_x0: float = float(word["x0"])
        w_x1: float = float(word["x1"])
        w_top: float = float(word["top"])
        w_bottom: float = float(word["bottom"])
        w_text: str = str(word.get("text", "")).strip()

        if not w_text:
            continue

        # Checkbox right-side label candidate: same row, starts just right of the checkbox
        if (
            is_checkbox
            and abs(w_top - candidate_top) <= y_tolerance
            and w_x0 >= candidate_x1 - 5.0
            and w_x0 <= candidate_x1 + _LABEL_RIGHT_GAP_PT
        ):
            right_side.append((w_x0, w_x1, w_text))
            continue

        # Priority 0 candidate: inline — same y-level, starts at candidate x0
        if (
            abs(w_top - candidate_top) <= y_tolerance
            and w_x0 >= candidate_x0 - _LABEL_INLINE_X_TOLERANCE
            and w_x0 <= candidate_x0 + _LABEL_INLINE_X_TOLERANCE
            and w_x1 < candidate_x1 - 5.0
        ):
            inline.append((w_x0, w_x1, w_text))

        # Priority 1 candidate: word ends to the left of the candidate
        elif w_x1 <= candidate_x0 + _LABEL_LEFT_X_TOLERANCE:
            if (
                w_bottom >= candidate_top - y_tolerance
                and w_top <= candidate_bottom + y_tolerance
                and w_x0 >= candidate_x0 - _LABEL_LEFT_MAX_DIST_PT
            ):
                in_row_left.append((w_top, w_x0, w_x1, w_text))

        # Priority 2 candidate: word is above the candidate
        else:
            dist_above: float = candidate_top - w_bottom
            if (
                dist_above >= -_LABEL_ABOVE_Y_TOLERANCE
                and dist_above <= _LABEL_ABOVE_MAX_DIST_PT
                and w_x0 >= candidate_x0 - _LABEL_ABOVE_X_TOLERANCE
                and w_x1 <= candidate_x1 + _LABEL_ABOVE_X_TOLERANCE
            ):
                above.append((dist_above, w_x0, w_text))

    # Checkbox right-side label (highest priority for checkboxes).
    # Collect the first consecutive run of words immediately to the right.
    if is_checkbox and right_side:
        right_side.sort(key=lambda t: t[0])
        if right_side[0][0] <= candidate_x1 + _LABEL_RIGHT_GAP_PT:
            collected: list[tuple[float, float, str]] = [right_side[0]]
            for i in range(1, len(right_side)):
                if right_side[i][0] - collected[-1][1] < _LABEL_LEFT_CELL_GAP_PT:
                    collected.append(right_side[i])
                else:
                    break
            return " ".join(t for _, _, t in collected), 0.0, 0.0

    # Priority 0 — inline label
    # Seed is any word at the same y-level starting within _LABEL_INLINE_X_TOLERANCE
    # of candidate_x0.  Walk right collecting consecutive words (gap < cell gap)
    # that end before the field's x1.  Return the label text AND the write coords:
    #   inline_x1     = x1 of the last label word (value is written after this)
    #   inline_bottom = pdfplumber bottom of the last label word (sets the write y)
    if inline:
        inline.sort()
        seed_x0 = inline[0][0]
        # Collect words from seed rightward, including their bottom coord
        all_same_y: list[tuple[float, float, float, str]] = sorted(
            [
                (
                    float(w["x0"]),
                    float(w["x1"]),
                    float(w.get("bottom", float(w["top"]) + 12.0)),
                    str(w.get("text", "")).strip(),
                )
                for w in words
                if (
                    str(w.get("text", "")).strip()
                    and abs(float(w["top"]) - candidate_top) <= ROW_TOLERANCE_PT
                    and float(w["x0"]) >= seed_x0
                    and float(w["x1"]) < candidate_x1 - 5.0
                )
            ],
            key=lambda t: t[0],
        )
        result: list[tuple[float, float, float, str]] = []
        for wx0, wx1, wb, wt in all_same_y:
            if not result:
                result.append((wx0, wx1, wb, wt))
            elif wx0 - result[-1][1] < _LABEL_LEFT_CELL_GAP_PT:
                result.append((wx0, wx1, wb, wt))
            else:
                break
        if result:
            inline_x1 = result[-1][1]
            inline_bottom = result[-1][2]
            return " ".join(t for _, _, _, t in result), inline_x1, inline_bottom

    # Priority 1 — in-row left words (table row labels, inline checkbox labels)
    if in_row_left:
        in_row_left.sort()
        clusters: list[list[tuple[float, float, float, str]]] = []
        current_cluster: list[tuple[float, float, float, str]] = [in_row_left[0]]
        for i in range(1, len(in_row_left)):
            gap = in_row_left[i][1] - in_row_left[i - 1][2]
            if gap > _LABEL_LEFT_CELL_GAP_PT:
                clusters.append(current_cluster)
                current_cluster = [in_row_left[i]]
            else:
                current_cluster.append(in_row_left[i])
        clusters.append(current_cluster)
        return " ".join(text for _, _, _, text in clusters[-1]), 0.0, 0.0

    # Priority 2 — above words (standard labeled fields)
    if above:
        min_dist: float = min(d for d, _, _ in above)
        nearest: list[tuple[float, str]] = [
            (x0, text) for d, x0, text in above
            if d <= min_dist + _LABEL_LINE_BAND_PT
        ]
        nearest.sort()
        return " ".join(text for _, text in nearest), 0.0, 0.0

    return "", 0.0, 0.0


def _iter_candidates(
    page: PageElements,
) -> Iterator[tuple[float, float, float, float, bool, bool, bool]]:
    """
    Yield (x0, top, x1, bottom, is_checkbox, is_textarea, is_table_cell) for each
    candidate input area found in lines, rects, underscore words, and table grids.
    """
    # Pass 1a: lines → input line candidates
    for ln in page.lines:
        x0: float = float(ln["x0"])
        top: float = float(ln["top"])
        x1: float = float(ln["x1"])
        bottom: float = float(ln["bottom"])
        width: float = x1 - x0
        height: float = bottom - top
        if width > MIN_INPUT_LINE_WIDTH_PT and height < _LINE_HEIGHT_MAX_PT:
            yield x0, top, x1, bottom, False, False, False

    # Pass 1b: rects → input box / textarea / checkbox candidates
    for rect in page.rects:
        x0 = float(rect["x0"])
        top = float(rect["top"])
        x1 = float(rect["x1"])
        bottom = float(rect["bottom"])
        width = x1 - x0
        height = bottom - top

        # Skip filled rects (decorative shading, logo backgrounds, etc.).
        # Table-based input cells are detected via find_tables() in Pass 1d.
        if rect.get("fill", False):
            continue

        if width <= CHECKBOX_MAX_SIZE_PT and height <= CHECKBOX_MAX_SIZE_PT:
            yield x0, top, x1, bottom, True, False, False
        elif width > MIN_INPUT_LINE_WIDTH_PT and height >= MIN_TEXTAREA_HEIGHT_PT:
            yield x0, top, x1, bottom, False, True, False
        elif width > MIN_INPUT_LINE_WIDTH_PT and height < MIN_TEXTAREA_HEIGHT_PT:
            yield x0, top, x1, bottom, False, False, False

    # Pass 1c: words matching underscore pattern → underscore input line
    for word in page.words:
        w_text: str = str(word.get("text", ""))
        if _RE_UNDERSCORES.match(w_text):
            x0 = float(word["x0"])
            top = float(word["top"])
            x1 = float(word["x1"])
            bottom = float(word["bottom"])
            yield x0, top, x1, bottom, False, False, False

    # Pass 1d: table cells inferred from grid lines (forms with no individual rect fields).
    # Yield as a 7-tuple with is_table_cell=True so detect_fields can use tight y_tolerance.
    yielded: set[tuple[float, float, float, float]] = set()
    for x0, top, x1, bottom, is_textarea in page.table_cells:
        key = (round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1))
        if key not in yielded:
            yielded.add(key)
            yield x0, top, x1, bottom, False, is_textarea, True


def _avg_body_font_size(pages: list[PageElements]) -> float:
    """Mean font size across all pages; used to identify header chars."""
    sizes = [
        float(ch.get("size", 0.0))
        for page in pages
        for ch in page.chars
        if float(ch.get("size", 0.0)) > 0
    ]
    return sum(sizes) / len(sizes) if sizes else 10.0


def _filter_header_words(words: list[dict], page: PageElements, avg_body_size: float) -> list[dict]:
    """
    Remove words that sit on the same y-line as section header characters
    (identified by large or bold font).  This prevents form titles like
    "FOR USE OF POST OFFICE" or "POST OFFICE SAVINGS BANK" from ever
    being used as field labels.
    """
    header_tops: set[float] = set()
    for ch in page.chars:
        size: float = float(ch.get("size", 0.0))
        fontname: str = str(ch.get("fontname", ""))
        if size > avg_body_size + FONT_SIZE_SECTION_DELTA or _RE_BOLD.search(fontname):
            header_tops.add(round(float(ch.get("top", 0.0)), 1))

    if not header_tops:
        return words

    return [
        w for w in words
        if not any(abs(round(float(w["top"]), 1) - h) < 2.0 for h in header_tops)
    ]


def detect_fields(pages: list[PageElements]) -> list[FormField]:
    """
    Run 3-pass detection on all pages.
    Returns list of FormField instances, IDs assigned as p{page}_f{index}.

    Two write-coordinate fields are set per field:
      input_x0 — x position to start writing the value (after inline label when present)
      input_y  — pdfplumber bottom of inline label word (for y baseline alignment);
                 0.0 means fall back to the underline-based formula.

    After detection, phantom table-border lines are removed: if an inline-labeled
    field and a non-inline field share the same (page, label), the non-inline
    duplicate is discarded.
    """
    fields: list[FormField] = []
    global_index: int = 0
    avg_body_size: float = _avg_body_font_size(pages)

    for page in pages:
        page_num: int = page.page_number
        words: list[dict] = _filter_header_words(page.words, page, avg_body_size)
        # For table-cell fields we use unfiltered words so bold column headers
        # (filtered out as "section headers" by font size) are still found by P2.
        raw_words: list[dict] = page.words

        for x0, top, x1, bottom, is_checkbox, is_textarea, is_table_cell in _iter_candidates(page):
            lbl_y_tol = 2.0 if is_table_cell else ROW_TOLERANCE_PT
            label_words = raw_words if is_table_cell else words
            label_raw, inline_x1, inline_bottom = _find_label(x0, top, x1, bottom, label_words, is_checkbox=is_checkbox, y_tolerance=lbl_y_tol)
            label: str = _clean_label(label_raw)
            field_type: FieldType = _classify_field_type(label, is_checkbox, is_textarea)
            placeholder: str = _get_placeholder(label)

            # Inline label detected: write value after the label text, at same baseline.
            # Non-inline: write at field's x0 (left edge), using line-based y formula.
            input_x0: float = inline_x1 if inline_x1 > 0.0 else x0
            input_y: float = inline_bottom  # 0.0 when no inline label

            form_field = FormField(
                id=f"p{page_num}_f{global_index}",
                label=label,
                field_type=field_type,
                page=page_num,
                x0=x0,
                top=top,
                x1=x1,
                bottom=bottom,
                placeholder=placeholder,
                input_x0=input_x0,
                input_y=input_y,
            )
            fields.append(form_field)
            global_index += 1

    # Deduplicate phantom table-border detections.
    # When an inline-labeled field (input_x0 > x0) and a non-inline field share the
    # same (page, label), the non-inline field is a table border that inherited the
    # label from above-detection; remove it to avoid writing the same value twice.
    inline_keys: set[tuple[int, str]] = {
        (f.page, f.label)
        for f in fields
        if f.label and f.input_x0 > f.x0
    }
    fields = [
        f for f in fields
        if not (
            f.label
            and (f.page, f.label) in inline_keys
            and not (f.input_x0 > f.x0)  # keep only if NOT inline
        )
    ]

    return fields
