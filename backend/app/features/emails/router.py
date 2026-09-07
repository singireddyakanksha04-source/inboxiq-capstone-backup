"""Reading stored mail. Owner: Akansha."""

from fastapi import APIRouter, HTTPException

from app.services import firestore_client as fs

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("")
def list_emails(uid: str, limit: int = 20, category: str | None = None):
    return fs.list_emails(uid, limit=limit, category=category)


@router.get("/stats")
def stats(uid: str):
    return {"by_category": fs.count_by_category(uid)}


@router.get("/{message_id}")
def get_email(uid: str, message_id: str):
    doc = fs.get_email(uid, message_id)
    if not doc:
        raise HTTPException(404, "email not found")
    return doc
