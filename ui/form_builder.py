from __future__ import annotations

import gradio as gr

from core.models import FormField, FormLayout


def build_field_component(
    field: FormField, prefill: str = ""
) -> gr.components.Component:
    """
    Returns the appropriate Gradio component for a FormField.
    prefill: previously saved value (empty string for new forms).
    """
    label = field.label or f"Field {field.id}"
    match field.field_type:
        case "text":
            return gr.Textbox(label=label, value=prefill, placeholder=field.placeholder)
        case "textarea":
            return gr.Textbox(
                label=label, value=prefill, lines=4, placeholder=field.placeholder
            )
        case "number":
            return gr.Number(label=label, value=float(prefill) if prefill else None)
        case "date":
            return gr.Textbox(label=label, value=prefill, placeholder="YYYY-MM-DD")
        case "checkbox":
            return gr.Checkbox(
                label=label,
                value=prefill.lower() in ("true", "yes", "checked", "1"),
            )
        case "dropdown":
            return gr.Dropdown(
                label=label, choices=field.options, value=prefill or None
            )
        case _:
            return gr.Textbox(label=label, value=prefill)
