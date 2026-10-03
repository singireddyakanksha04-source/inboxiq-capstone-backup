"""Reading stored mail. Owner: Akansha."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.services import firestore_client as fs

router = APIRouter(prefix="/api/emails", tags=["emails"])

Uid = Annotated[str, Query(pattern=fs.UID_PATTERN)]


@router.get("")
def list_emails(uid: str, limit: int = 20, category: str | None = None):
    return fs.list_emails(uid, limit=limit, category=category)


@router.get("/search")
def search_emails(
    uid: Uid,
    q: str = Query(..., min_length=1, max_length=500),
    limit: int = Query(50, ge=1, le=200),
    category: str | None = None,
):
    """Search the current mailbox. Must stay above /{message_id}."""
    q = q.strip()
    if not q:
        raise HTTPException(422, "q must not be blank")
    return fs.search_emails(uid, q, limit=limit, category=category)


@router.get("/search/page")
def search_page(
    uid: Uid,
    q: str = Query("", max_length=500),
    sender: str = Query("", max_length=254),
    category: str | None = None,
    after: date | None = None,
    before: date | None = None,
    offset: int = Query(0, ge=0, le=500),
    limit: int = Query(50, ge=1, le=200),
):
    """Bounded read-only search, with filter-only queries and further pages."""
    if after and before and after > before:
        raise HTTPException(422, "From date must be on or before To date")
    rows = fs.search_emails(uid, q.strip(), limit=limit + 1, category=category,
                            sender=sender, after=after, before=before, offset=offset)
    return {"items": rows[:limit],
            "next_offset": offset + limit if len(rows) > limit else None,
            "search_window": fs.SEARCH_WINDOW}


@router.get("/stats")
def stats(uid: str):
    return {"by_category": fs.count_by_category(uid)}


@router.get("/subscriptions")
def subscriptions(uid: str):
    subs = fs.list_subscriptions(uid)
    return {
        "items": subs,
        "estimated_monthly_cost": fs.estimate_monthly_cost(subs),
        "stale_count": sum(1 for s in subs if s.get("is_stale")),
    }


@router.get("/unsubscribe-suggestions")
def unsubscribe_suggestions(uid: str, limit: int = 20):
    """Read-only list for the cleanup view; links are only shown, never followed."""
    return {"items": fs.unsubscribe_suggestions(uid, limit=limit)}


@router.get("/{message_id}")
def get_email(uid: str, message_id: str):
    doc = fs.get_email(uid, message_id)
    if not doc:
        raise HTTPException(404, "email not found")
    return doc
