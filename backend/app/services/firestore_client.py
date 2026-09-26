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


# Fields the classifier/extractors fill in after sync. Gmail never has them,
# so a re-sync sends them as None; on an existing doc that would wipe the
# stored result. Add any new derived field here. Fields that come from Gmail
# itself (headers, labels, ...) must NOT be listed — those should refresh.
DERIVED_FIELDS = frozenset({
    "category",
    "confidence",
    "promo_subcategory",
    "sub_service",
    "sub_amount",
    "sub_cycle",
    "sub_renewal_hint",
})


def save_emails(uid: str, messages: list[EmailMessage]) -> int:
    """Batched upsert. Gmail's message id is the doc id, so re-syncing is safe.

    New docs are written in full, so category is stored as an explicit None
    and the "uncategorized" filter in list_emails finds them. Docs that
    already exist keep their DERIVED_FIELDS unless the message carries a
    real value for one."""
    written = 0
    for start in range(0, len(messages), 400):  # batch limit is 500 writes
        chunk = messages[start : start + 400]
        refs = [_emails(uid).document(msg.id) for msg in chunk]
        # One round trip for the whole chunk; the field mask keeps it to ids.
        existing = {
            snap.id
            for snap in db().get_all(refs, field_paths=["id"])
            if snap.exists
        }
        batch = db().batch()
        for msg, ref in zip(chunk, refs):
            doc = msg.model_dump(mode="python")
            if msg.id in existing:
                doc = {
                    k: v for k, v in doc.items()
                    if not (k in DERIVED_FIELDS and v is None)
                }
            doc["synced_at"] = _now()
            batch.set(ref, doc, merge=True)
            written += 1
        batch.commit()
    return written


def get_email(uid: str, message_id: str) -> dict | None:
    snap = _emails(uid).document(message_id).get()
    return snap.to_dict() if snap.exists else None


def list_emails(uid: str, limit: int = 20, category: str | None = None) -> list[dict]:
    q = _emails(uid)
    if category == "uncategorized":
        # count_by_category's synthetic bucket for category is None/missing —
        # never a real stored value, so it needs its own filter.
        q = q.where(filter=firestore.FieldFilter("category", "==", None))
    elif category:
        q = q.where(filter=firestore.FieldFilter("category", "==", category))
    q = q.order_by("date", direction=firestore.Query.DESCENDING).limit(limit)
    return [d.to_dict() for d in q.stream()]


def set_category(uid: str, message_id: str, category: str, confidence: float) -> None:
    """Hook for Satwik's classifier."""
    _emails(uid).document(message_id).set(
        {"category": category, "confidence": confidence}, merge=True
    )


def set_promo_subcategory(uid: str, message_id: str, subcategory: str | None) -> None:
    """Hook for Satwik's extract_promo_subcategory."""
    _emails(uid).document(message_id).set({"promo_subcategory": subcategory}, merge=True)


def set_subscription_info(uid: str, message_id: str, info: dict) -> None:
    """Hook for Satwik's extract_subscription_info."""
    _emails(uid).document(message_id).set(info, merge=True)


def list_subscriptions(uid: str) -> list[dict]:
    return list_emails(uid, limit=200, category="subscription")


_AMOUNT_RE = re.compile(r"\$\s?(\d+(?:\.\d{2})?)")


def estimate_monthly_cost(subscriptions: list[dict]) -> float:
    """Trials cost nothing until charged, so only monthly/yearly entries with
    a parsed dollar amount count toward the estimate; yearly is normalized to
    its monthly-equivalent."""
    total = 0.0
    for sub in subscriptions:
        amount = sub.get("sub_amount")
        if not amount:
            continue
        match = _AMOUNT_RE.search(amount)
        if not match:
            continue
        value = float(match.group(1))
        if sub.get("sub_cycle") == "yearly":
            value /= 12
        elif sub.get("sub_cycle") == "trial":
            continue
        total += value
    return round(total, 2)


def count_by_category(uid: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in _emails(uid).select(["category"]).stream():
        key = (doc.to_dict() or {}).get("category") or "uncategorized"
        counts[key] = counts.get(key, 0) + 1
    return counts
