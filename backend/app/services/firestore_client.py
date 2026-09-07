"""Firestore access layer. Everything that touches the DB goes through here."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from app.core.config import get_settings
from app.models.email import EmailMessage


@lru_cache
def db() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(
        project=settings.project_id, database=settings.firestore_database
    )


def make_uid(email: str) -> str:
    """Stable doc id from an address until real Firebase Auth uids exist."""
    return re.sub(r"[^a-z0-9_]", "_", email.lower())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- users

def upsert_user(email: str) -> str:
    uid = make_uid(email)
    ref = db().collection("users").document(uid)
    snap = ref.get()
    data = {"email": email, "last_seen_at": _now()}
    if not snap.exists:
        data["created_at"] = _now()
        data["prefs"] = {"auto_archive": False, "digest": "weekly"}
    ref.set(data, merge=True)
    return uid


def get_user(uid: str) -> dict | None:
    snap = db().collection("users").document(uid).get()
    return snap.to_dict() if snap.exists else None


def mark_synced(uid: str) -> None:
    db().collection("users").document(uid).set({"last_sync_at": _now()}, merge=True)


# ---------------------------------------------------------------- emails

def _emails(uid: str):
    return db().collection("users").document(uid).collection("emails")


def save_emails(uid: str, messages: list[EmailMessage]) -> int:
    """Batched upsert. Gmail's message id is the doc id, so re-syncing is safe."""
    written = 0
    for start in range(0, len(messages), 400):  # batch limit is 500 writes
        batch = db().batch()
        for msg in messages[start : start + 400]:
            doc = msg.model_dump(mode="python")
            doc["synced_at"] = _now()
            batch.set(_emails(uid).document(msg.id), doc, merge=True)
            written += 1
        batch.commit()
    return written


def get_email(uid: str, message_id: str) -> dict | None:
    snap = _emails(uid).document(message_id).get()
    return snap.to_dict() if snap.exists else None


def list_emails(uid: str, limit: int = 20, category: str | None = None) -> list[dict]:
    q = _emails(uid)
    if category:
        q = q.where(filter=firestore.FieldFilter("category", "==", category))
    q = q.order_by("date", direction=firestore.Query.DESCENDING).limit(limit)
    return [d.to_dict() for d in q.stream()]


def set_category(uid: str, message_id: str, category: str, confidence: float) -> None:
    """Hook for Satwik's classifier."""
    _emails(uid).document(message_id).set(
        {"category": category, "confidence": confidence}, merge=True
    )


def count_by_category(uid: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in _emails(uid).select(["category"]).stream():
        key = (doc.to_dict() or {}).get("category") or "uncategorized"
        counts[key] = counts.get(key, 0) + 1
    return counts
