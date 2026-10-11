"""Gmail -> Firestore. Owner: Abhiram."""

from fastapi import APIRouter, HTTPException, Query
from google.auth.exceptions import RefreshError

from app.services import firestore_client as fs
from googleapiclient.errors import HttpError

from app.services.gmail_auth import NotSignedIn
from app.services.gmail_client import fetch_messages, get_profile, is_rate_limited

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

SIGN_IN_AGAIN = "Not signed in to Gmail. Sign in again."


def _gmail_error(exc: Exception) -> HTTPException:
    """What the dashboard should see when a Gmail call fails."""
    if isinstance(exc, (NotSignedIn, RefreshError)):
        return HTTPException(401, SIGN_IN_AGAIN)
    if isinstance(exc, HttpError):
        if exc.resp.status == 401:
            return HTTPException(401, SIGN_IN_AGAIN)
        if is_rate_limited(exc):
            return HTTPException(429, "Gmail is limiting requests right now. Wait a minute and try again.")
    return HTTPException(502, "Gmail did not answer properly. Try again in a moment.")


def _profile(account: str) -> dict:
    try:
        return get_profile(account)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (NotSignedIn, RefreshError, HttpError) as exc:
        raise _gmail_error(exc) from exc


@router.get("/me")
def me(account: str = "default"):
    profile = _profile(account)
    return {"email": profile["emailAddress"], "total": profile["messagesTotal"]}


# Sync only looks at recent mail, so a big inbox never means thousands of
# downloads. 30 days still catches each monthly bill and subscription charge.
SYNC_DAYS = 30

# Receipts and bills in the window, wherever they are filed. They are easy to
# miss in the newest-N inbox pull, and the subscriptions panel is built from them.
BILLING_TERMS = (
    "-in:spam -in:trash "
    "{subject:receipt subject:invoice subject:renewal subject:subscription "
    "subject:payment subject:billing category:purchases}"
)


def _within(query: str, days: int) -> str:
    """Add the date window unless the query already sets its own."""
    if "newer_than:" in query or "after:" in query:
        return query
    return f"{query} newer_than:{days}d"


@router.post("/sync")
def sync(
    count: int = Query(25, ge=1, le=200),
    q: str = "in:inbox",
    account: str = "default",
    billing: int = Query(0, ge=0, le=100),
    days: int = Query(SYNC_DAYS, ge=1, le=365),
):
    """Pull the newest `count` messages from the last `days` days, plus up to
    `billing` receipts/bills from the same window when asked. A message found
    by both pulls is stored once."""
    profile = _profile(account)
    uid = fs.upsert_user(profile["emailAddress"])
    try:
        messages = {m.id: m for m in fetch_messages(count, _within(q, days), account)}
    except (NotSignedIn, RefreshError, HttpError) as exc:
        raise _gmail_error(exc) from exc
    # The billing pull is extra: if Gmail refuses it, keep the inbox pull.
    billing_error = None
    if billing:
        try:
            for m in fetch_messages(billing, _within(BILLING_TERMS, days), account, skip=set(messages)):
                messages.setdefault(m.id, m)
        except HttpError as exc:
            billing_error = "Receipts and bills were skipped (Gmail limit); sync again in a minute."
            if not is_rate_limited(exc):
                billing_error = "Receipts and bills could not be fetched this time."
    written = fs.save_emails(uid, list(messages.values()))
    fs.mark_synced(uid)
    return {
        "uid": uid,
        "email": profile["emailAddress"],
        "fetched": len(messages),
        "stored": written,
        "billing_error": billing_error,
    }
