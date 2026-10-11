"""Sign-in routes for the dashboard's Google OAuth flow."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import OAuth2Error

from app.core.config import get_settings
from app.services import firestore_client as fs
from app.services import gmail_auth
from app.services.gmail_client import get_profile

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def status(account: str = "default"):
    """Who is signed in right now. The dashboard keys all its data off `uid`,
    so a new sign-in with a different Google account switches the view."""
    signed_out = {"account": account, "authorized": False, "email": None, "uid": None}
    try:
        if not gmail_auth.is_authorized(account):
            return signed_out
        email = get_profile(account)["emailAddress"]
    except (RefreshError, gmail_auth.NotSignedIn):
        return signed_out  # token revoked or removed since the last check
    except HttpError as exc:
        if exc.resp.status == 401:
            return signed_out
        raise
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
        account = gmail_auth.exchange_code(code, state)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except OAuth2Error as exc:  # code already used or expired
        raise HTTPException(400, "Google sign-in expired. Please sign in again.") from exc
    get_profile(account)
    return RedirectResponse(f"{get_settings().frontend_url}/?signed_in=1")


@router.post("/logout")
def logout(account: str = "default"):
    return {"removed": gmail_auth.logout(account)}
