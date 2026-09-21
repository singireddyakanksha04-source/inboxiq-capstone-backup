"""Sign-in routes for the dashboard's Google OAuth flow."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.services import firestore_client as fs
from app.services import gmail_auth
from app.services.gmail_client import get_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def status(account: str = "default"):
    """Who is signed in right now. The dashboard keys all its data off `uid`,
    so a new sign-in with a different Google account switches the view."""
    if not gmail_auth.is_authorized(account):
        return {"account": account, "authorized": False, "email": None, "uid": None}
    email = get_profile(account)["emailAddress"]
    return {"account": account, "authorized": True, "email": email, "uid": fs.make_uid(email)}


@router.get("/login")
def login(account: str = "default"):
    """Send the browser to Google's consent page."""
    try:
        url = gmail_auth.authorization_url(account)
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    return RedirectResponse(url)


@router.get("/callback")
def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = Query(None),
):
    """Where Google sends the browser back. Trades the code for a token."""
    if error:
        raise HTTPException(400, f"Google returned: {error}")
    if not code or not state:
        raise HTTPException(400, "missing code or state")
    try:
        gmail_auth.exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # back to the dashboard, which re-checks /api/auth/status
    return RedirectResponse(f"{get_settings().frontend_url}/?signed_in=1")


@router.post("/logout")
def logout(account: str = "default"):
    return {"removed": gmail_auth.logout(account)}
