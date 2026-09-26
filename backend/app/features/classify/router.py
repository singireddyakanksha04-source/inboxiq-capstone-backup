"""Categorising stored mail. Owner: Satwik."""

from fastapi import APIRouter, Query

from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services.deadlines import extract_due_date
from app.services.classifier import (
    CATEGORIES,
    extract_promo_subcategory,
    extract_subscription_info,
    get_classifier,
)

router = APIRouter(prefix="/api/classify", tags=["classify"])


@router.get("/backends")
def backends():
    return {"backends": ["rules", "small", "large", "qwen"], "categories": CATEGORIES}


@router.post("")
def classify(uid: str, backend: str = "rules", limit: int = Query(25, le=200)):
    clf = get_classifier(backend)
    results = []
    # Newest `limit` plus anything older still waiting for a category — older
    # mail outside the newest window would otherwise stay uncategorized forever.
    docs = {d["id"]: d for d in fs.list_emails(uid, limit=limit)}
    for d in fs.list_emails(uid, limit=500, category="uncategorized"):
        docs.setdefault(d["id"], d)
    for doc in docs.values():
        email = EmailMessage(
            **{k: v for k, v in doc.items() if k in EmailMessage.model_fields}
        )
        category, confidence = clf.classify(email)
        fs.set_category(uid, email.id, category, confidence)
        if category == "promotion":
            fs.set_promo_subcategory(uid, email.id, extract_promo_subcategory(email))
        email.category = category
        due_date, due_label = extract_due_date(email) or (None, None)
        # Only write when it changed, so a re-run doesn't touch every doc twice.
        if (due_date, due_label) != (doc.get("due_date"), doc.get("due_label")):
            fs.set_due_date(uid, email.id, due_date, due_label)
        results.append({"id": email.id, "category": category, "confidence": confidence})
    return {"backend": clf.name, "classified": len(results), "results": results}


@router.post("/subscriptions")
def detect_subscriptions(uid: str):
    """Pull service/amount/cycle/renewal hint out of every already-categorised
    'subscription' email. Run classify first so there's something to scan."""
    results = []
    for doc in fs.list_subscriptions(uid, merged=False):
        email = EmailMessage(
            **{k: v for k, v in doc.items() if k in EmailMessage.model_fields}
        )
        info = extract_subscription_info(email)
        fs.set_subscription_info(uid, email.id, info)
        results.append({"id": email.id, **info})
    return {"detected": len(results), "results": results}
