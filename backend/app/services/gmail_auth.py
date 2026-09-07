"""Google OAuth for Gmail (web application client).

The app never sees the user's Google password. The user signs in on Google's own
page, Google redirects back to us with a one-time code, we trade that code for a
refresh token, and we store the token locally (later: encrypted in Firestore,
keyed by user).

Two entry points, same web OAuth client:

  * dashboard -> ``authorization_url()`` then ``exchange_code()``, redirect URI
    ``settings.oauth_redirect_uri``
  * CLI scripts -> ``login()``, which opens a throwaway local server on
    ``settings.cli_redirect_port``

Both redirect URIs must be registered on the client in the Google console.
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from googleapiclient.discovery import build

from app.core.config import get_settings

# state -> account, so the callback knows whose token it is holding. In-memory is
# fine while the API is a single local process.
_pending: dict[str, str] = {}


def _token_path(account: str) -> Path:
    safe = account.replace("/", "_")
    return get_settings().token_store / f"{safe}.json"


def _require_client_secrets() -> Path:
    settings = get_settings()
    if not settings.client_secrets_file.exists():
        raise FileNotFoundError(
            f"OAuth client file missing: {settings.client_secrets_file}\n"
            "Follow SETUP.md."
        )
    return settings.client_secrets_file


def _save(account: str, creds: Credentials) -> None:
    path = _token_path(account)
    path.write_text(creds.to_json())
    path.chmod(0o600)


def load_credentials(account: str) -> Credentials | None:
    """Return stored credentials for an account, refreshed if expired."""
    path = _token_path(account)
    if not path.exists():
        return None

    settings = get_settings()
    creds = Credentials.from_authorized_user_file(str(path), settings.gmail_scopes)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save(account, creds)
        return creds
    return None


def is_authorized(account: str = "default") -> bool:
    return load_credentials(account) is not None


# --- dashboard flow -------------------------------------------------------


def authorization_url(account: str = "default") -> str:
    """Google sign-in URL to send the browser to."""
    settings = get_settings()
    flow = Flow.from_client_secrets_file(
        str(_require_client_secrets()), settings.gmail_scopes
    )
    flow.redirect_uri = settings.oauth_redirect_uri

    url, state = flow.authorization_url(
        access_type="offline",  # we want a refresh token, not just an hour of access
        prompt="consent",
    )
    _pending[state] = account
    return url


def exchange_code(code: str, state: str) -> str:
    """Trade the callback's code for tokens. Returns the account name."""
    account = _pending.pop(state, None)
    if account is None:
        raise ValueError("unknown or expired OAuth state")

    settings = get_settings()
    flow = Flow.from_client_secrets_file(
        str(_require_client_secrets()), settings.gmail_scopes, state=state
    )
    flow.redirect_uri = settings.oauth_redirect_uri
    flow.fetch_token(code=code)

    _save(account, flow.credentials)
    return account


# --- CLI flow -------------------------------------------------------------


def login(account: str = "default") -> Credentials:
    """Run the browser consent flow if we have no usable token, else reuse it."""
    creds = load_credentials(account)
    if creds:
        return creds

    settings = get_settings()
    flow = InstalledAppFlow.from_client_secrets_file(
        str(_require_client_secrets()), settings.gmail_scopes
    )
    # Fixed port: a web client only accepts redirect URIs registered ahead of
    # time, so this must match http://localhost:<cli_redirect_port>/ in console.
    creds = flow.run_local_server(port=settings.cli_redirect_port, prompt="consent")

    _save(account, creds)
    return creds


def gmail_service(account: str = "default"):
    """Authenticated Gmail API client."""
    return build("gmail", "v1", credentials=login(account), cache_discovery=False)


def logout(account: str = "default") -> bool:
    path = _token_path(account)
    if path.exists():
        path.unlink()
        return True
    return False
