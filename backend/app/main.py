"""InboxIQ API.

Routes come from ``app/features/*`` via the registry — nothing to register here.
In dev the React app runs on Vite (:5173) and calls this over CORS; in prod
``frontend/dist`` is served from ``/`` if it has been built.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.registry import discover

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
# Serve the built React app when it exists. In dev you run Vite instead
# (npm run dev on :5180), which proxies /api back here.
UI_DIR = FRONTEND / "dist"

settings = get_settings()
app = FastAPI(title="InboxIQ API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FEATURES = discover()
for feature in FEATURES:
    app.include_router(feature.router)


@app.get("/health")
def health():
    return {"status": "ok", "features": [f.name for f in FEATURES]}


if UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
