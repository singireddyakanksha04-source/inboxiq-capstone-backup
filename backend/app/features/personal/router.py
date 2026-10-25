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
    fs.delete_split(uid, fs.CUSTOM_PREFIX + category_id)
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


# ---------------------------------------------------------------- subcategories

# A parent is a built-in category ("promotion") or the account's own ("my:<id>").
Parent = Annotated[str, Query(pattern=r"^(my:)?[a-z0-9_]{1,40}$")]
OTHER = "_other"
_SPLIT_WINDOW = 500  # newest emails of the parent counted for the subcategory totals


class SplitRequest(BaseModel):
    label: str = Field(default="", max_length=60)


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=30)


def _parent_info(uid: str, parent: str) -> tuple[str, str]:
    """Label and description of the parent; 404 for a custom one that is gone."""
    if parent.startswith(fs.CUSTOM_PREFIX):
        cid = parent[len(fs.CUSTOM_PREFIX):]
        own = next((c for c in fs.get_custom_categories(uid) if c["id"] == cid), None)
        if not own:
            raise HTTPException(404, "category not found")
        return own["name"], own["description"]
    return parent.replace("_", " ").capitalize(), ""


def _split_view(uid: str, parent: str, split: dict | None) -> dict:
    """Subcategories with counts over the parent's current emails; the rest is Other."""
    if not split:
        return {"parent": parent, "items": [], "other": 0}
    live = {s["id"] for s in split["subs"]}
    counts: dict[str, int] = {}
    members = fs.list_emails(uid, limit=_SPLIT_WINDOW, category=parent)
    for doc in members:
        sub = (split["results"].get(doc["id"]) or {}).get("sub")
        if sub in live:
            counts[sub] = counts.get(sub, 0) + 1
    placed = sum(counts.values())
    return {"parent": parent,
            "items": [{**s, "count": counts.get(s["id"], 0)} for s in split["subs"]],
            "other": len(members) - placed}


@router.get("/subcategories")
def list_subcategories(uid: Uid, parent: Parent):
    return _split_view(uid, parent, fs.get_split(uid, parent))


@router.post("/split")
def split_category(uid: Uid, parent: Parent, body: SplitRequest | None = None):
    """Ask the model for subcategories of the parent, then sort its newest
    emails into them. Saved only when both steps finish, so a failure leaves
    the category as it was; the failure comes back in `error`."""
    label, description = _parent_info(uid, parent)
    if body and body.label.strip():
        label = body.label.strip()
    members = fs.list_emails(uid, limit=personal_ai.AI_LIMIT, category=parent)
    if len(members) < personal_ai.SPLIT_MIN:
        raise HTTPException(422, f"A category needs at least {personal_ai.SPLIT_MIN} emails to split.")
    try:
        subs = personal_ai.suggest_subcategories(label, description, members)
        if not subs:
            return {**_split_view(uid, parent, fs.get_split(uid, parent)),
                    "error": "Couldn't find clear subcategories in these emails."}
        results: dict[str, dict] = {}
        for start in range(0, len(members), personal_ai.BATCH_SIZE):
            batch = members[start:start + personal_ai.BATCH_SIZE]
            for doc, (sub_id, reason) in zip(batch, personal_ai.sort_batch(subs, batch)):
                results[doc["id"]] = {"sub": sub_id, "reason": reason}
    except personal_ai.AIUnavailable as e:
        return {**_split_view(uid, parent, fs.get_split(uid, parent)), "error": str(e)}
    fs.set_split(uid, parent, subs, results)
    return {**_split_view(uid, parent, fs.get_split(uid, parent)), "error": None}


def _require_split(uid: str, parent: str, sub_id: str) -> dict:
    split = fs.get_split(uid, parent)
    if not split or not any(s["id"] == sub_id for s in split["subs"]):
        raise HTTPException(404, "subcategory not found")
    return split


@router.patch("/subcategories/{sub_id}")
def rename_subcategory(uid: Uid, parent: Parent, sub_id: str, body: Rename):
    split = _require_split(uid, parent, sub_id)
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(422, "Give the subcategory a name.")
    if any(s["id"] != sub_id and s["name"].lower() == name.lower() for s in split["subs"]):
        raise HTTPException(409, f"There is already a subcategory called {name}.")
    subs = [{**s, "name": name} if s["id"] == sub_id else s for s in split["subs"]]
    fs.set_split(uid, parent, subs, split["results"])
    return _split_view(uid, parent, fs.get_split(uid, parent))


@router.delete("/subcategories/{sub_id}")
def delete_subcategory(uid: Uid, parent: Parent, sub_id: str):
    """Its emails go back to Other. One subcategory left is no split at all."""
    split = _require_split(uid, parent, sub_id)
    subs = [s for s in split["subs"] if s["id"] != sub_id]
    results = {mid: r for mid, r in split["results"].items() if r.get("sub") != sub_id}
    if len(subs) < 2:
        fs.delete_split(uid, parent)
    else:
        fs.set_split(uid, parent, subs, results)
    return _split_view(uid, parent, fs.get_split(uid, parent))


@router.get("/subcategories/{sub_id}/emails")
def subcategory_emails(uid: Uid, parent: Parent, sub_id: str, limit: int = Query(50, ge=1, le=200)):
    """The parent's emails in one subcategory, with the reason; "_other" lists the rest."""
    split = fs.get_split(uid, parent)
    if not split or (sub_id != OTHER and not any(s["id"] == sub_id for s in split["subs"])):
        raise HTTPException(404, "subcategory not found")
    live = {s["id"] for s in split["subs"]}
    out = []
    for doc in fs.list_emails(uid, limit=_SPLIT_WINDOW, category=parent):
        r = split["results"].get(doc["id"]) or {}
        sub = r.get("sub") if r.get("sub") in live else None
        if (sub_id == OTHER and sub is None) or (sub is not None and sub == sub_id):
            out.append({**doc, "sub_reason": r.get("reason") if sub else None})
        if len(out) >= limit:
            break
    return out
