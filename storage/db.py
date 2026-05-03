from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pymongo
from montydb import MontyClient

from core.models import FormField, FormLayout
from storage.layout_store import deserialise_layout, serialise_layout

# ── Constants ──────────────────────────────────────────────────────────────────
DB_NAME: str = os.getenv("DB_NAME", "formfiller_db")
_LAYOUTS_COLLECTION: str = "layouts"
_SUBMISSIONS_COLLECTION: str = "submissions"


def get_db_client():
    """Returns MontyClient or pymongo.MongoClient based on DB_TYPE env var."""
    db_type = os.getenv("DB_TYPE", "montydb").lower()
    if db_type == "mongodb":
        uri = os.environ["DB_URI"]  # Raise if not set — fail fast in production
        return pymongo.MongoClient(uri)
    db_path = os.getenv("DB_PATH", "./data/formfiller_db")
    Path(db_path).mkdir(parents=True, exist_ok=True)
    return MontyClient(host=db_path)


def get_collection(name: str):
    """Return a collection from the configured DB. Creates a new client each call (MontyDB-safe)."""
    client = get_db_client()
    return client[DB_NAME][name]


def _ensure_tag_index() -> None:
    """Ensure unique index on submissions.tag. Safe to call multiple times."""
    col = get_collection(_SUBMISSIONS_COLLECTION)
    col.create_index("tag", unique=True)


# ── Layout CRUD ────────────────────────────────────────────────────────────────

def save_layout(layout: FormLayout) -> str:
    """Insert layout into layouts collection. Returns inserted _id as string."""
    import uuid
    col = get_collection(_LAYOUTS_COLLECTION)
    layout_id = str(uuid.uuid4())
    doc = {
        "_id": layout_id,
        "source_file": layout.source_file,
        "source_hash": layout.source_hash,
        "layout_json": serialise_layout(layout),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    col.insert_one(doc)
    return layout_id


def load_layout_by_id(layout_id: str) -> FormLayout:
    """Fetch layout by _id string, deserialise and return FormLayout."""
    col = get_collection(_LAYOUTS_COLLECTION)
    doc = col.find_one({"_id": layout_id})
    if doc is None:
        raise ValueError(f"Layout not found: {layout_id}")
    return deserialise_layout(doc["layout_json"])


# ── Submission CRUD ────────────────────────────────────────────────────────────

def get_all_submission_summaries() -> list[dict]:
    """
    Lazy query — returns only tag, form_title, source_file, filled_at.
    Does NOT return full fields list.
    """
    col = get_collection(_SUBMISSIONS_COLLECTION)
    cursor = col.find({}, {"tag": 1, "form_title": 1, "source_file": 1, "filled_at": 1, "_id": 0})
    return list(cursor)


def get_submission_by_tag(tag: str) -> dict | None:
    """Returns full submission document or None if not found."""
    col = get_collection(_SUBMISSIONS_COLLECTION)
    return col.find_one({"tag": tag})


def tag_exists(tag: str) -> bool:
    """Check if tag is already in use."""
    col = get_collection(_SUBMISSIONS_COLLECTION)
    return col.find_one({"tag": tag}, {"_id": 1}) is not None


def insert_submission(
    tag: str,
    layout_id: str,
    form_title: str,
    source_file: str,
    field_values: dict[str, str],
    layout: FormLayout,
) -> None:
    """Insert a new submission document. Raises if tag already exists."""
    _ensure_tag_index()

    # Build fields list from layout to get labels
    field_map: dict[str, FormField] = {
        f.id: f
        for section in layout.sections
        for row in section.rows
        for f in row.fields
    }

    fields_list: list[dict] = [
        {"id": fid, "label": field_map[fid].label if fid in field_map else "", "value": val}
        for fid, val in field_values.items()
    ]

    col = get_collection(_SUBMISSIONS_COLLECTION)
    col.insert_one({
        "tag": tag,
        "layout_id": layout_id,
        "form_title": form_title,
        "source_file": source_file,
        "filled_at": datetime.now(timezone.utc).isoformat(),
        "fields": fields_list,
    })


def update_submission(tag: str, field_values: dict[str, str]) -> None:
    """Overwrite fields and update filled_at timestamp for existing tag."""
    fields_list: list[dict] = [
        {"id": fid, "value": val}
        for fid, val in field_values.items()
    ]
    col = get_collection(_SUBMISSIONS_COLLECTION)
    col.update_one(
        {"tag": tag},
        {"$set": {
            "fields": fields_list,
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


def delete_submission(tag: str) -> bool:
    """Delete submission by tag. Returns True if a document was deleted."""
    col = get_collection(_SUBMISSIONS_COLLECTION)
    result = col.delete_one({"tag": tag})
    return result.deleted_count > 0
