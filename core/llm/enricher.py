from __future__ import annotations

import json

from core.llm._base import CompletionRequest
from core.llm._factory import get_provider
from core.models import FieldType, FormField, PageElements

# Prompt is provider-agnostic.  OpenAI providers enforce JSON via response_format.
# Anthropic providers append their own JSON enforcement suffix internally.
# Both return {"fields": [...]} so parsing is identical regardless of provider.
_SYSTEM_PROMPT: str = """
You are a form analysis assistant. You will be given:
1. The raw text content of a PDF form (words in reading order, prefixed by page number).
2. A list of detected input fields with their current auto-detected labels AND their
   spatial coordinates on the page (x0 = distance from left edge, top = distance from
   top edge, both in points).

Your task: for each field return an improved label, field_type, and optional placeholder.

Return a JSON object in exactly this shape:
{"fields": [{"id": str, "label": str, "field_type": str, "placeholder": str}, ...]}

Rules:
- One object per input field, in the same order as received.
- field_type must be one of: text, number, date, checkbox, textarea, dropdown
- Labels: concise (≤ 60 chars), title case.
- If the current label is already correct, return it unchanged.
- Ignore decorative text, watermarks, and form titles — they are never field labels.
- Never invent fields. Only improve the ones given.
- Use the x0 and top coordinates to understand WHERE on the form each field is located.
  Fields with similar top values are on the same row. The label printed nearest to and
  to the LEFT (or directly above) a field's x0/top position is that field's label.
  Do NOT assign a label from a different section of the form to a field — e.g. a
  checkbox at top≈176 (time row) cannot be "Annual Leave" (which sits at top≈228 in the
  Leave Information section).
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
    Post-process heuristically detected fields using the configured LLM provider.

    Returns the same list with label/field_type/placeholder potentially improved.
    The coordinates (id, page, x0, top, x1, bottom) are never modified.

    Falls back to original fields silently on any error — enrichment is best-effort.
    Returns fields unchanged when no provider is configured (heuristic-only mode).
    """
    provider = get_provider()
    if provider is None:
        return fields

    field_summaries = [
        {
            "id": f.id,
            "label": f.label,
            "field_type": f.field_type,
            "placeholder": f.placeholder,
            "x0": round(f.x0, 1),
            "top": round(f.top, 1),
        }
        for f in fields
    ]
    user_message: str = (
        f"Form text context:\n{_build_page_context(pages)}\n\n"
        f"Detected fields:\n{json.dumps(field_summaries, separators=(',', ':'))}"
    )

    try:
        raw: str = provider.complete(CompletionRequest(system=_SYSTEM_PROMPT, user=user_message))
        data = json.loads(raw)
        enriched_list: list[dict] = data.get("fields", data) if isinstance(data, dict) else data
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
                    input_x0=f.input_x0, input_y=f.input_y,
                ))
            else:
                result.append(f)
        return result

    except Exception:  # noqa: BLE001 — enrichment is best-effort, never fatal
        return fields

