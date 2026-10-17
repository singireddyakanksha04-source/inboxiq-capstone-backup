"""Custom categories: create, list, delete, and AI sorting into them."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services import firestore_client as fs
from app.services import personal_ai

router = APIRouter(prefix="/api/personal", tags=["personal"])

# Only ids make_uid could have produced reach Firestore.
Uid = Annotated[str, Query(pattern=fs.UID_PATTERN)]


class NewCategory(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    description: str = Field(min_length=5, max_length=200)


def _with_counts(uid: str, categories: list[dict]) -> list[dict]:
    counts = fs.count_by_custom(uid)
    return [{**c, "count": counts.get(c["id"], 0)} for c in categories]


@router.get("/categories")
def list_categories(uid: Uid):
    return {"items": _with_counts(uid, fs.get_custom_categories(uid)),
            "max": personal_ai.MAX_CATEGORIES}


@router.post("/categories", status_code=201)
def add_category(uid: Uid, body: NewCategory):
    name, description = body.name.strip(), " ".join(body.description.split())
    if not name or len(description) < 5:
        raise HTTPException(422, "Give the category a name and a short description.")
    categories = fs.get_custom_categories(uid)
    if len(categories) >= personal_ai.MAX_CATEGORIES:
        raise HTTPException(409, f"You can have up to {personal_ai.MAX_CATEGORIES} categories.")
    if any(c["name"].lower() == name.lower() for c in categories):
        raise HTTPException(409, f"You already have a category called {name}.")
    category = {"id": personal_ai.make_id(name, {c["id"] for c in categories}),
                "name": name, "description": description}
    fs.set_custom_categories(uid, categories + [category])
    return category


@router.delete("/categories/{category_id}")
def delete_category(uid: Uid, category_id: str):
    categories = fs.get_custom_categories(uid)
    kept = [c for c in categories if c["id"] != category_id]
    if len(kept) == len(categories):
        raise HTTPException(404, "category not found")
    fs.set_custom_categories(uid, kept)
    return {"deleted": category_id, "emails_cleared": fs.clear_custom_category(uid, category_id)}


@router.post("/sort")
def sort(uid: Uid, limit: int = Query(50, ge=1, le=100)):
    """Ask the model about the newest `limit` emails not yet checked against
    the current category list. A model failure is reported in `error`, not
    raised, so a sync that already succeeded is not shown as failed."""
    categories = fs.get_custom_categories(uid)
    if not categories:
        return {"checked": 0, "matched": 0, "error": None}
    sig = personal_ai.signature(categories)
    pending = [d for d in fs.list_emails(uid, limit=limit) if d.get("custom_sig") != sig]
    checked = matched = 0
    error = None
    for start in range(0, len(pending), personal_ai.BATCH_SIZE):
        batch = pending[start:start + personal_ai.BATCH_SIZE]
        try:
            results = personal_ai.sort_batch(categories, batch)
        except personal_ai.AIUnavailable as e:
            error = str(e)
            break
        for doc, (category_id, reason) in zip(batch, results):
            fs.set_custom_result(uid, doc["id"], category_id, reason, sig)
            checked += 1
            matched += category_id is not None
    return {"checked": checked, "matched": matched, "error": error}
