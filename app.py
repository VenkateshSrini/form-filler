from __future__ import annotations

import os
import tempfile
from pathlib import Path

import gradio as gr
from dotenv import load_dotenv

from core.field_detector import detect_fields
from core.generators import get_document_generator
from core.layout_analyzer import build_layout
from core.llm import enrich_fields_with_llm
from core.models import FormLayout, WizardAction
from core.readers import READER_REGISTRY, get_document_reader
from storage.db import (
    delete_submission,
    get_all_submission_summaries,
    get_submission_by_tag,
    insert_submission,
    save_layout,
    tag_exists,
    update_submission,
)
from ui.form_builder import build_field_component

# ── Constants ──────────────────────────────────────────────────────────────────
INPUT_FORMS_DIR: Path = Path("./input-forms")
_SERVER_NAME: str = "127.0.0.1"
_SERVER_PORT: int = 7860


# ── Helper: scan input-forms directory ────────────────────────────────────────

def scan_input_forms_dir() -> list[str]:
    """Returns list of supported document filenames in input-forms/. Creates dir if absent."""
    supported: tuple[str, ...] = tuple(READER_REGISTRY.keys())
    INPUT_FORMS_DIR.mkdir(exist_ok=True)
    return sorted(p.name for p in INPUT_FORMS_DIR.iterdir() if p.suffix.lower() in supported)


def load_all_tags() -> list[str]:
    """Returns sorted list of all saved tags from DB."""
    summaries = get_all_submission_summaries()
    return sorted(s["tag"] for s in summaries)


# ── Navigation helpers ─────────────────────────────────────────────────────────

def go_to_home():
    return gr.update(visible=True), gr.update(visible=False)


def go_to_fill():
    return gr.update(visible=False), gr.update(visible=True)


# ── Business logic helpers ─────────────────────────────────────────────────────

def _persist_submission(
    tag: str,
    layout_id: str,
    form_title: str,
    source_file: str,
    field_values: dict[str, str],
    is_edit_mode: bool,
    layout: FormLayout,
) -> str:
    if is_edit_mode:
        update_submission(tag, field_values)
        return f"Submission '{tag}' updated."
    insert_submission(tag, layout_id, form_title, source_file, field_values, layout)
    return f"Submission '{tag}' saved."


def _render_filled_pdf(layout: FormLayout, field_values: dict[str, str]) -> bytes:
    generator = get_document_generator(Path(layout.source_file))
    return generator.generate_filled(layout, field_values, INPUT_FORMS_DIR)


def execute_wizard_action(
    action: WizardAction,
    tag: str,
    field_values: dict[str, str],
    layout_id: str,
    form_title: str,
    source_file: str,
    is_edit_mode: bool,
    layout: FormLayout | None,
) -> tuple[bytes | None, str]:
    """
    Single handler for all 3 wizard buttons.
    Returns (pdf_bytes_or_None, status_message).
    """
    pdf_bytes: bytes | None = None
    status_parts: list[str] = []

    if action in (WizardAction.SAVE_ONLY, WizardAction.SAVE_AND_GENERATE):
        assert layout is not None
        msg = _persist_submission(
            tag, layout_id, form_title, source_file, field_values, is_edit_mode, layout
        )
        status_parts.append(msg)

    if action in (WizardAction.GENERATE_ONLY, WizardAction.SAVE_AND_GENERATE):
        assert layout is not None
        try:
            pdf_bytes = _render_filled_pdf(layout, field_values)
            status_parts.append("PDF generated.")
        except FileNotFoundError as exc:
            status_parts.append(f"Error: {exc}")

    return pdf_bytes, " ".join(status_parts)


# ── Gradio app builder ─────────────────────────────────────────────────────────

def build_app() -> gr.Blocks:  # noqa: PLR0915  (large function — UI wiring)
    with gr.Blocks(title="PDF Form Filler") as demo:

        # ── Application state ──────────────────────────────────────────────────
        layout_state: gr.State = gr.State(None)       # FormLayout | None
        layout_id_state: gr.State = gr.State("")      # str
        values_state: gr.State = gr.State({})         # dict[str, str]
        initial_values_state: gr.State = gr.State({}) # dict[str, str] — pre-fill only; never updated while typing
        mode_state: gr.State = gr.State("new")        # "new" | "edit"
        tag_state: gr.State = gr.State("")            # str

        gr.Markdown("# PDF Form Filler")

        # ══════════════════════════════════════════════════════════════════════
        # HOME SCREEN
        # ══════════════════════════════════════════════════════════════════════
        with gr.Column(visible=True) as home_col:

            # Panel A — Continue Previous Submission
            with gr.Group():
                gr.Markdown("## Continue Previous Submission")
                _initial_tags: list[str] = load_all_tags()
                tag_dropdown = gr.Dropdown(
                    label="Saved Submissions",
                    choices=_initial_tags,
                    value=None,
                    interactive=True,
                )
                refresh_tags_btn = gr.Button("Refresh", size="sm")
                submission_preview = gr.Markdown("*Select a submission to preview.*")
                with gr.Row():
                    load_edit_btn = gr.Button(
                        "Load & Edit",
                        variant="primary",
                        interactive=bool(_initial_tags),
                    )
                    delete_submission_btn = gr.Button(
                        "Delete",
                        variant="stop",
                        interactive=bool(_initial_tags),
                    )

            gr.Markdown("---")

            # Panel B — Start New Form
            with gr.Group():
                gr.Markdown("## Start New Form")
                pdf_dropdown = gr.Dropdown(
                    label="Available Forms",
                    choices=scan_input_forms_dir(),
                    value=None,
                    interactive=True,
                )
                refresh_forms_btn = gr.Button("Refresh", size="sm")
                load_form_btn = gr.Button("Load Form", variant="primary")
                processing_status = gr.Markdown("", visible=False)

        # ══════════════════════════════════════════════════════════════════════
        # FILL SCREEN  (save options live here — no separate wizard screen)
        # ══════════════════════════════════════════════════════════════════════
        with gr.Column(visible=False) as fill_col:
            gr.Markdown("## Fill Form")

            @gr.render(inputs=[layout_state, initial_values_state])
            def render_form(layout: FormLayout | None, values: dict) -> None:
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
                                # Accumulate typed value into values_state.
                                # values_state is NOT listed in @gr.render inputs so
                                # updating it here never triggers a re-render.
                                component.change(
                                    fn=lambda val, cur, fid=field.id: {**cur, fid: str(val) if val is not None else ""},
                                    inputs=[component, values_state],
                                    outputs=[values_state],
                                )

            gr.Markdown("---")
            gr.Markdown("## Save Options")

            tag_input = gr.Textbox(
                label="Submission Tag",
                placeholder="e.g. john_doe_2026",
                interactive=True,
            )
            action_status = gr.Markdown("")

            with gr.Row():
                save_only_btn = gr.Button("Save to DB")
                generate_only_btn = gr.Button("Generate PDF")
                save_and_generate_btn = gr.Button("Save & Generate", variant="primary")

            pdf_output = gr.File(label="Download Filled PDF", visible=False)
            back_to_home_btn = gr.Button("← Back to Home")

        # ══════════════════════════════════════════════════════════════════════
        # EVENT HANDLERS
        # ══════════════════════════════════════════════════════════════════════

        # ── Home: refresh buttons ──────────────────────────────────────────────
        def _refresh_tags():
            tags = load_all_tags()
            has = bool(tags)
            return gr.update(choices=tags, value=None), gr.update(interactive=has), gr.update(interactive=has)

        refresh_tags_btn.click(
            fn=_refresh_tags,
            inputs=[],
            outputs=[tag_dropdown, load_edit_btn, delete_submission_btn],
        )

        # ── Home Panel A: Delete submission ────────────────────────────────────
        def _delete_submission(tag: str):
            if not tag:
                gr.Warning("Please select a submission to delete.")
                tags = load_all_tags()
                has = bool(tags)
                return (gr.update(), gr.update(),
                        gr.update(interactive=has), gr.update(interactive=has))
            deleted = delete_submission(tag)
            if deleted:
                gr.Info(f"Submission '{tag}' deleted.")
            else:
                gr.Warning(f"Submission '{tag}' not found.")
            tags = load_all_tags()
            has = bool(tags)
            return (gr.update(choices=tags, value=None),
                    gr.update(value="*Select a submission to preview.*"),
                    gr.update(interactive=has),
                    gr.update(interactive=has))

        delete_submission_btn.click(
            fn=_delete_submission,
            inputs=[tag_dropdown],
            outputs=[tag_dropdown, submission_preview, load_edit_btn, delete_submission_btn],
        )

        refresh_forms_btn.click(
            fn=lambda: gr.update(choices=scan_input_forms_dir()),
            inputs=[],
            outputs=[pdf_dropdown],
        )

        # ── Home Panel A: preview on tag select ───────────────────────────────
        def _preview_submission(tag: str) -> str:
            if not tag:
                return "*Select a submission to preview.*"
            doc = get_submission_by_tag(tag)
            if doc is None:
                return "*Submission not found.*"
            return (
                f"**Form:** {doc.get('form_title', 'N/A')}  \n"
                f"**Source:** {doc.get('source_file', 'N/A')}  \n"
                f"**Last Saved:** {doc.get('filled_at', 'N/A')}"
            )

        tag_dropdown.change(
            fn=_preview_submission,
            inputs=[tag_dropdown],
            outputs=[submission_preview],
        )

        # ── Home Panel A: Load & Edit ──────────────────────────────────────────
        def _load_edit(tag: str):
            _err = (
                gr.update(visible=True), gr.update(visible=False),
                None, "", {}, {}, "new", "",
                gr.update(value="", interactive=True), gr.update(value=""), gr.update(visible=False),
                gr.update(visible=False),
            )
            if not tag:
                gr.Warning("Please select a submission to load.")
                yield _err
                return
            doc = get_submission_by_tag(tag)
            if doc is None:
                gr.Warning(f"Submission '{tag}' not found.")
                yield _err
                return
            source_file = doc.get("source_file", "")
            file_path = INPUT_FORMS_DIR / source_file
            # Show loading indicator while re-detecting
            yield (
                gr.update(visible=True), gr.update(visible=False),
                None, "", {}, {}, "new", "",
                gr.update(value="", interactive=True), gr.update(value=""),
                gr.update(visible=False),
                gr.update(value="⏳ Re-detecting form fields, please wait…", visible=True),
            )
            # Always re-detect fields fresh so coordinates reflect current code,
            # never the stale layout stored when the submission was first created.
            try:
                reader = get_document_reader(file_path)
                pages = list(reader.parse(file_path))
                source_hash = reader.compute_hash(file_path)
                fields = detect_fields(pages)
                fields = enrich_fields_with_llm(fields, pages)
                layout = build_layout(fields, pages, source_file, source_hash)
                layout_id = save_layout(layout)
            except Exception as exc:  # noqa: BLE001
                gr.Warning(f"Could not re-detect form: {exc}")
                yield _err
                return
            # Remap saved values to new field IDs.
            # Prefer label match (normalized) so values survive label-text changes;
            # fall back to ID match for fields whose labels couldn't be compared.
            def _norm(lbl: str) -> str:
                return lbl.strip().rstrip(":").strip().lower()
            saved_fields: list[dict] = doc.get("fields", [])
            label_to_val = {
                _norm(f["label"]): str(f["value"])
                for f in saved_fields
                if f.get("label") and f.get("value", "") != ""
            }
            id_to_val = {
                f["id"]: str(f["value"])
                for f in saved_fields
                if f.get("value", "") != ""
            }
            all_fields = [f for sec in layout.sections for row in sec.rows for f in row.fields]
            values: dict[str, str] = {}
            for f in all_fields:
                norm = _norm(f.label)
                if norm in label_to_val:
                    values[f.id] = label_to_val[norm]
                elif f.id in id_to_val:
                    values[f.id] = id_to_val[f.id]
            yield (
                gr.update(visible=False), gr.update(visible=True),
                layout, layout_id, values, values, "edit", tag,
                gr.update(value=tag, interactive=False),
                gr.update(value=""),
                gr.update(visible=False),
                gr.update(visible=False),
            )

        load_edit_btn.click(
            fn=_load_edit,
            inputs=[tag_dropdown],
            outputs=[
                home_col, fill_col,
                layout_state, layout_id_state, values_state, initial_values_state, mode_state, tag_state,
                tag_input, action_status, pdf_output,
                processing_status,
            ],
        )

        # ── Home Panel B: Load Form ────────────────────────────────────────────
        def _load_form(filename: str):
            _err = (
                gr.update(visible=True), gr.update(visible=False),
                None, "", {}, {}, "new", "",
                gr.update(value="", interactive=True), gr.update(value=""), gr.update(visible=False),
                gr.update(visible=False),
            )
            if not filename:
                gr.Warning("Please select a form to load.")
                yield _err
                return
            # Show processing indicator before starting heavy work
            yield (
                gr.update(visible=True), gr.update(visible=False),
                None, "", {}, {}, "new", "",
                gr.update(value="", interactive=True), gr.update(value=""), gr.update(visible=False),
                gr.update(value="⏳ Parsing form and detecting fields, please wait…", visible=True),
            )
            file_path = INPUT_FORMS_DIR / filename
            try:
                reader = get_document_reader(file_path)
                pages = list(reader.parse(file_path))
                source_hash = reader.compute_hash(file_path)
                fields = detect_fields(pages)
                fields = enrich_fields_with_llm(fields, pages)
                layout = build_layout(fields, pages, filename, source_hash)
                layout_id = save_layout(layout)
                if not fields:
                    gr.Info("No fields detected. Check if the PDF is a form.")
            except ValueError as exc:
                gr.Warning(str(exc))
                yield _err
                return
            except Exception as exc:  # noqa: BLE001
                gr.Warning(f"Could not open document: {exc}")
                yield _err
                return
            yield (
                gr.update(visible=False), gr.update(visible=True),
                layout, layout_id, {}, {}, "new", "",
                gr.update(value="", interactive=True), gr.update(value=""), gr.update(visible=False),
                gr.update(visible=False),
            )

        load_form_btn.click(
            fn=_load_form,
            inputs=[pdf_dropdown],
            outputs=[
                home_col, fill_col,
                layout_state, layout_id_state, values_state, initial_values_state, mode_state, tag_state,
                tag_input, action_status, pdf_output,
                processing_status,
            ],
        )

        # ── Fill: Back to Home ─────────────────────────────────────────────────
        back_to_home_btn.click(
            fn=go_to_home,
            inputs=[],
            outputs=[home_col, fill_col],
        )

        # ── Fill: shared validation ────────────────────────────────────────────
        def _validate_tag(tag: str, mode: str) -> str | None:
            if not tag.strip():
                return "Tag cannot be empty."
            if mode == "new" and tag_exists(tag):
                return f"Tag '{tag}' already exists. Choose a different name."
            return None

        # ── Fill: Save to DB ───────────────────────────────────────────────────
        def _do_save_only(tag: str, values: dict, layout_id: str, mode: str, layout: FormLayout | None):
            err = _validate_tag(tag, mode)
            if err:
                gr.Warning(err)
                return gr.update(value=f"⚠ {err}"), gr.update(visible=False), mode
            assert layout is not None
            _, status = execute_wizard_action(
                WizardAction.SAVE_ONLY, tag, values, layout_id,
                layout.title, layout.source_file, mode == "edit", layout,
            )
            # Stay on fill screen so user can continue to Generate if they want.
            # Switch mode to edit so a second Save won't fail with duplicate-tag error.
            return gr.update(value=status), gr.update(visible=False), "edit"

        save_only_btn.click(
            fn=_do_save_only,
            inputs=[tag_input, values_state, layout_id_state, mode_state, layout_state],
            outputs=[action_status, pdf_output, mode_state],
        )

        # ── Fill: Generate PDF ─────────────────────────────────────────────────
        def _do_generate_only(values: dict, layout: FormLayout | None):
            # No tag required — we are only generating, not saving.
            if layout is None:
                return gr.update(value="⚠ No form loaded."), gr.update(visible=False)
            try:
                pdf_bytes = _render_filled_pdf(layout, values)
            except FileNotFoundError as exc:
                return gr.update(value=f"Error: {exc}"), gr.update(visible=False)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="filled_")
            tmp.write(pdf_bytes)
            tmp.flush()
            tmp.close()
            return gr.update(value="PDF generated."), gr.update(value=tmp.name, visible=True)

        generate_only_btn.click(
            fn=_do_generate_only,
            inputs=[values_state, layout_state],
            outputs=[action_status, pdf_output],
        )

        # ── Fill: Save & Generate ──────────────────────────────────────────────
        def _do_save_and_generate(tag: str, values: dict, layout_id: str, mode: str, layout: FormLayout | None):
            err = _validate_tag(tag, mode)
            if err:
                gr.Warning(err)
                return gr.update(value=f"⚠ {err}"), gr.update(visible=False), mode
            assert layout is not None
            pdf_bytes, status = execute_wizard_action(
                WizardAction.SAVE_AND_GENERATE, tag, values, layout_id,
                layout.title, layout.source_file, mode == "edit", layout,
            )
            # After first save switch to edit mode so re-clicking Save & Generate
            # updates the existing submission instead of failing with duplicate-tag.
            new_mode = "edit"
            if pdf_bytes is not None:
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", prefix="filled_")
                tmp.write(pdf_bytes)
                tmp.flush()
                tmp.close()
                return gr.update(value=status), gr.update(value=tmp.name, visible=True), new_mode
            return gr.update(value=status), gr.update(visible=False), new_mode

        save_and_generate_btn.click(
            fn=_do_save_and_generate,
            inputs=[tag_input, values_state, layout_id_state, mode_state, layout_state],
            outputs=[action_status, pdf_output, mode_state],
        )

    return demo


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_dotenv()

    # Ensure required directories exist
    INPUT_FORMS_DIR.mkdir(exist_ok=True)
    db_path = Path(os.getenv("DB_PATH", "./data/formfiller_db"))
    db_path.mkdir(parents=True, exist_ok=True)

    demo = build_app()
    demo.launch(server_name=_SERVER_NAME, server_port=_SERVER_PORT)
