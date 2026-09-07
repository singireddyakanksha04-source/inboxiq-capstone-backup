"""Central settings, loaded from the .env file at the repo root."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel
import os

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


class Settings(BaseModel):
    project_id: str
    client_secrets_file: Path
    token_store: Path
    firestore_database: str

    # Web OAuth client. Both of these must be listed under "Authorized redirect
    # URIs" on the client in the Google console, exactly as written.
    #   oauth_redirect_uri  -> the dashboard sign-in flow (browser -> FastAPI)
    #   http://localhost:8080/ -> the CLI scripts' throwaway local server
    oauth_redirect_uri: str
    cli_redirect_port: int = 8080

    # Where the OAuth callback sends the browser when it is done. Vite in dev,
    # the FastAPI-served build in prod.
    frontend_url: str

    # Read-only is enough for this week. gmail.modify is listed on the consent
    # screen so we can archive/label later without a second review.
    gmail_scopes: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
    ]


@lru_cache
def get_settings() -> Settings:
    settings = Settings(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        client_secrets_file=REPO_ROOT / os.getenv(
            "GOOGLE_CLIENT_SECRETS", "secrets/oauth_client.json"
        ),
        token_store=REPO_ROOT / os.getenv("OAUTH_TOKEN_STORE", "secrets/tokens"),
        firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        oauth_redirect_uri=os.getenv(
            "OAUTH_REDIRECT_URI", "http://localhost:8000/api/auth/callback"
        ),
        frontend_url=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
    )
    settings.token_store.mkdir(parents=True, exist_ok=True)
    return settings
