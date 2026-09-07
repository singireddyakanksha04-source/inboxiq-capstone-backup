"""Gmail -> Firestore. Owner: Abhiram."""

from fastapi import APIRouter, HTTPException, Query

from app.services import firestore_client as fs
from app.services.gmail_client import fetch_messages, get_profile

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/me")
def me(account: str = "default"):
    profile = get_profile(account)
    return {"email": profile["emailAddress"], "total": profile["messagesTotal"]}


@router.post("/sync")
def sync(count: int = Query(25, le=200), q: str = "in:inbox", account: str = "default"):
    try:
        profile = get_profile(account)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc

    uid = fs.upsert_user(profile["emailAddress"])
    messages = fetch_messages(count, q, account)
    written = fs.save_emails(uid, messages)
    fs.mark_synced(uid)
    return {"uid": uid, "email": profile["emailAddress"], "fetched": len(messages), "stored": written}
