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
    "due_date",
    "due_label",
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


def list_subscriptions(uid: str, merged: bool = True) -> list[dict]:
    """Every subscription email, or (merged) one entry per service."""
    docs = list_emails(uid, limit=200, category="subscription")
    return _merge_by_service(docs) if merged else docs


# Senders that mail on behalf of many different services, so their domain
# says nothing about which service it is; those merge on name only.
_SHARED_DOMAINS = {
    "gmail", "googlemail", "google", "outlook", "hotmail", "yahoo", "icloud",
    "apple", "paypal", "stripe",
}


def _domain_label(domain: str | None) -> str:
    """Registrable name of a sender domain: members.netflix.com -> 'netflix',
    netflix.co.uk -> 'netflix' (not 'co')."""
    labels = (domain or "").lower().split(".")
    if len(labels) < 2:
        return ""
    if len(labels) > 2 and len(labels[-1]) == 2 and labels[-2] in {
        "co", "com", "org", "net", "ac", "gov", "edu"
    }:
        return labels[-3]
    return labels[-2]


def _service_keys(doc: dict) -> set[str]:
    """Keys that identify one service: the registrable domain's name
    (members.netflix.com and account.netflix.com -> 'netflix') and the
    compacted display name ('Best Buy' -> 'bestbuy')."""
    keys = set()
    label = _domain_label(doc.get("sender_domain"))
    if label and label not in _SHARED_DOMAINS:
        keys.add(label)
    name = re.sub(r"[^a-z0-9]", "", (doc.get("sub_service") or "").lower())
    if name:
        keys.add(name)
    return keys or {doc.get("id", "")}


def _merge_by_service(docs: list[dict]) -> list[dict]:
    """Collapse several emails from the same service into one entry. Input is
    newest-first; each group keeps its newest email that has an amount (else
    its newest), under the shortest service name seen ('Best Buy' over
    'Best Buy Labor Day Sale'), plus how many emails were merged."""
    return [rep for rep, _ in _group_by_service(docs)]


def _group_by_service(docs: list[dict]) -> list[tuple[dict, list[dict]]]:
    """_merge_by_service, but each entry also keeps the emails it merged."""
    groups: list[tuple[set[str], list[dict]]] = []
    for doc in docs:
        keys = _service_keys(doc)
        hit = next((g for g in groups if g[0] & keys), None)
        if hit:
            hit[0].update(keys)
            hit[1].append(doc)
        else:
            groups.append((keys, [doc]))

    merged = []
    now = _now()
    for _, members in groups:
        rep = dict(next((d for d in members if d.get("sub_amount")), members[0]))
        names = [d["sub_service"] for d in members if d.get("sub_service")]
        if names:
            rep["sub_service"] = min(names, key=len)
        rep["sub_email_count"] = len(members)
        rep.update(_staleness(members, rep.get("sub_cycle"), now))
        merged.append((rep, members))
    return merged


# How long a service can go quiet, by billing cycle, before it looks
# forgotten: a monthly plan normally mails a receipt every month.
_STALE_AFTER_DAYS = {"monthly": 45, "trial": 45, "yearly": 400}
_STALE_AFTER_UNKNOWN = 60
# "We miss you" style mail: the service itself says it isn't being used.
_WINBACK_RE = re.compile(
    r"\b(haven'?t (?:used|seen you|logged in|visited)|we miss you|miss(?:ing)? you|"
    r"come back|it'?s been a while|still interested|win you back|reactivate|"
    r"we haven'?t seen)\b",
    re.I,
)


def _last_seen(members: list[dict]) -> datetime | None:
    dates = [d["date"] for d in members if d.get("date")]
    return max(dates) if dates else None


def _is_winback(doc: dict) -> bool:
    return bool(_WINBACK_RE.search(f"{doc.get('subject', '')}\n{doc.get('snippet', '')}"))


def _staleness(members: list[dict], cycle: str | None, now: datetime) -> dict:
    """last_seen/email_count for a merged service, and whether it looks
    stale: nothing from it for longer than its cycle allows, or the service
    itself sending 'we miss you' mail."""
    cycle = cycle or next((d["sub_cycle"] for d in members if d.get("sub_cycle")), None)
    last_seen = _last_seen(members)
    reason = None
    if last_seen:
        quiet = (now - last_seen).days
        if quiet >= _STALE_AFTER_DAYS.get(cycle, _STALE_AFTER_UNKNOWN):
            plan = f" ({cycle} plan)" if cycle in ("monthly", "yearly") else ""
            reason = f"No email in {quiet} days{plan}"
    if not reason and any(_is_winback(d) for d in members):
        reason = "Service says you haven't been using it"
    return {
        "last_seen": last_seen,
        "email_count": len(members),
        "is_stale": reason is not None,
        "stale_reason": reason,
    }


_AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d{2})?)")


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
        value = float(match.group(1).replace(",", ""))
        if sub.get("sub_cycle") == "yearly":
            value /= 12
        elif sub.get("sub_cycle") == "trial":
            continue
        total += value
    return round(total, 2)


# ---------------------------------------------------------------- cleanup

# A link attached to the word on the same line ("[Unsubscribe](https://...)",
# "Unsubscribe: https://...", "Unsubscribe <https://...>"), else any link
# whose path says unsubscribe. A bare link on the next line is not trusted:
# plain-text mail puts links before and after their labels about equally.
_URL = r"https?://[^\s<>()\[\]\"']+"
_UNSUB_NEAR_RE = re.compile(rf"unsubscribe\]?[ \t]*[(:<][ \t]*({_URL})", re.I)
_UNSUB_URL_RE = re.compile(rf"https?://[^\s<>()\[\]\"']*(?:unsub|opt-?out)[^\s<>()\[\]\"']*", re.I)

# Promo/newsletter senders need this many emails before they are worth
# suggesting; more than _BULK_COUNT is suggested even if some were opened.
_MIN_COUNT = 3
_BULK_COUNT = 6


def _unsubscribe_link(members: list[dict]) -> tuple[str | None, str | None]:
    """Newest List-Unsubscribe header link, else a link found in a body.
    Mail synced before the header was captured has no list_unsubscribe, so
    the body is the fallback. Returns (link, 'header' | 'body' | None)."""
    for doc in members:
        if doc.get("list_unsubscribe"):
            return doc["list_unsubscribe"], "header"
    for doc in members[:5]:
        body = doc.get("body_text") or ""
        m = _UNSUB_NEAR_RE.search(body)
        link = m.group(1) if m else None
        if not link:
            m = _UNSUB_URL_RE.search(body)
            link = m.group(0) if m else None
        if link:
            return link.rstrip(".,;:!>"), "body"
    return None, None


def _sender_name(doc: dict) -> str:
    name = (doc.get("sender") or "").split("<")[0].strip().strip('"').strip()
    return name or doc.get("sender_domain") or doc.get("sender_email") or "Unknown sender"


def _suggestion(members: list[dict], name: str, category: str, reason: str) -> dict:
    link, source = _unsubscribe_link(members)
    newest = members[0]
    return {
        "service": name,
        "sender": newest.get("sender_email") or newest.get("sender"),
        "sender_domain": newest.get("sender_domain"),
        "category": category,
        "count": len(members),
        "last_seen": _last_seen(members),
        "reason": reason,
        "unsubscribe_url": link,
        "link_source": source,
        "latest_id": newest.get("id"),
    }


def unsubscribe_suggestions(uid: str, limit: int = 20) -> list[dict]:
    """Senders worth unsubscribing from: stale subscriptions, and promotion/
    newsletter senders that mail a lot and whose mail sits unopened. There is
    no open tracking, so 'unopened' means still UNREAD when it was synced.
    Only reads stored mail; never follows any unsubscribe link."""
    out = []
    for rep, members in _group_by_service(list_emails(uid, limit=200, category="subscription")):
        if rep.get("is_stale"):
            out.append(_suggestion(
                members, rep.get("sub_service") or _sender_name(members[0]),
                "subscription", rep["stale_reason"],
            ))

    bulk = list_emails(uid, limit=300, category="promotion") + list_emails(
        uid, limit=300, category="newsletter"
    )
    bulk.sort(key=lambda d: d.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    senders: dict[str, list[dict]] = {}
    for doc in bulk:
        label = _domain_label(doc.get("sender_domain"))
        key = label if label and label not in _SHARED_DOMAINS else doc.get("sender_email", "")
        senders.setdefault(key, []).append(doc)

    for members in senders.values():
        labels = [set(d.get("labels") or []) for d in members]
        if any("STARRED" in ls for ls in labels):
            continue  # starred something from them, so they're wanted
        count = len(members)
        unread = sum(1 for ls in labels if "UNREAD" in ls)
        kind = "newsletter" if all(d.get("category") == "newsletter" for d in members) else "promotion"
        noun = f"{kind} emails" if kind == "newsletter" else "promotional emails"
        if count >= _MIN_COUNT and unread == count:
            reason = f"{count} {noun}, none opened"
        elif count >= _BULK_COUNT:
            reason = f"{count} {noun}, {unread} unopened"
        elif any(_is_winback(d) for d in members) and unread == count:
            reason = "Sender says you haven't been engaging"
        else:
            continue
        out.append(_suggestion(members, _sender_name(members[0]), kind, reason))

    # Stale subscriptions first (they may cost money), then the noisiest senders.
    out.sort(key=lambda s: (s["category"] != "subscription", -s["count"]))
    return out[:limit]


def count_by_category(uid: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in _emails(uid).select(["category"]).stream():
        key = (doc.to_dict() or {}).get("category") or "uncategorized"
        counts[key] = counts.get(key, 0) + 1
    return counts


def set_due_date(uid: str, message_id: str, due_date: str | None, due_label: str | None) -> None:
    """Hook for extract_due_date. None clears a date left by an earlier run."""
    _emails(uid).document(message_id).set(
        {"due_date": due_date, "due_label": due_label}, merge=True
    )
