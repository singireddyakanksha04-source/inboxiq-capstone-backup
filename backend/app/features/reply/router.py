"""Reply drafts: the user picks one stored email, the model drafts the reply."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.services import firestore_client as fs
from app.services import needs_ai, reply_ai
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
    tone: str = Query(reply_ai.TONES[0], pattern="^(" + "|".join(reply_ai.TONES) + ")$"),
    length: str = Query(reply_ai.LENGTHS[0], pattern="^(" + "|".join(reply_ai.LENGTHS) + ")$"),
):
    """The draft is only returned, never sent. A model failure is reported in
    `error` so the page can offer Try again."""
    email = fs.get_email(uid, email_id)
    if not email:
        raise HTTPException(404, "email not found")
    me = str((fs.get_user(uid) or {}).get("email") or "").lower()
    # What came before it in the thread, so the reply knows what was said.
    earlier = [{"from": "the user" if me and str(e.get("sender_email") or "").lower() == me else e.get("sender", ""),
                "text": reply_ai.email_text(e)}
               for e in fs.thread_emails(uid, email.get("thread_id") or "")
               if e.get("id") != email_id and email.get("date") and e["date"] < email["date"]]
    try:
        result = reply_ai.draft_reply(email, " ".join(name.split()), note, previous,
                                      {"tone": tone, "length": length}, earlier)
    except AIUnavailable as e:
        return {"draft": None, "error": str(e)}
    return {"draft": {"email_id": email_id, "to": email.get("sender_email") or "",
                      "subject": email.get("subject") or "", **result}, "error": None}


@router.get("/needs")
def needs(uid: Uid):
    """The stored emails waiting on the user's answer, newest first, with the
    model's reason. Read only: nothing is stored or sent. A model failure is
    reported in `error`."""
    me = str((fs.get_user(uid) or {}).get("email") or "").lower()
    emails = fs.list_emails(uid, limit=needs_ai.LIMIT)
    try:
        found = needs_ai.needs_reply(emails, me, lambda thread_id: fs.thread_emails(uid, thread_id))
    except AIUnavailable as e:
        return {"items": [], "error": str(e)}
    return {"items": [{"email_id": e.get("id"), "thread_id": e.get("thread_id"), "sender": e.get("sender") or "",
                       "subject": e.get("subject") or "", "date": e.get("date"), "reason": e["needs_reason"]}
                      for e in found], "error": None}
