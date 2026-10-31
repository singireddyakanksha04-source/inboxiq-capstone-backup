"""Reply drafts: the user picks one stored email, the model drafts the reply."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.services import firestore_client as fs
from app.services import reply_ai
from app.services.personal_ai import AIUnavailable

router = APIRouter(prefix="/api/reply", tags=["reply"])

# Only ids make_uid could have produced reach Firestore.
Uid = Annotated[str, Query(pattern=fs.UID_PATTERN)]


@router.post("/draft")
def draft(
    uid: Uid,
    email_id: str = Query(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    name: str = Query("", max_length=60),
    note: str = Query("", max_length=300),
    previous: str = Query("", max_length=2000),
):
    """The draft is only returned, never sent. A model failure is reported in
    `error` so the page can offer Try again."""
    email = fs.get_email(uid, email_id)
    if not email:
        raise HTTPException(404, "email not found")
    try:
        result = reply_ai.draft_reply(email, " ".join(name.split()), note, previous)
    except AIUnavailable as e:
        return {"draft": None, "error": str(e)}
    return {"draft": {"email_id": email_id, "to": email.get("sender_email") or "",
                      "subject": email.get("subject") or "", **result}, "error": None}
