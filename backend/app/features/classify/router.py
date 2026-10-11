"""Categorising stored mail. Owner: Satwik."""

from typing import Annotated

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

# Only ids make_uid could have produced reach Firestore.
Uid = Annotated[str, Query(pattern=fs.UID_PATTERN)]


@router.get("/backends")
def backends():
    return {"backends": ["rules", "small", "large", "qwen"], "categories": CATEGORIES}


# Rules are free, so the rules backend re-checks all stored mail (up to this
# many): mail sorted by an older version of the rules is fixed on the next
# sync instead of only the newest `limit`. LLM backends keep the limit.
RULES_RECHECK_LIMIT = 1000
_SUB_FIELDS = ("sub_service", "sub_amount", "sub_cycle", "sub_renewal_hint")


@router.post("")
def classify(uid: Uid, backend: str = "rules", limit: int = Query(25, ge=1, le=200)):
    clf = get_classifier(backend)
    results = []
    if backend == "rules":
        docs = {d["id"]: d for d in fs.list_emails(uid, limit=RULES_RECHECK_LIMIT)}
    else:
        # Newest `limit` plus anything older still waiting for a category.
        docs = {d["id"]: d for d in fs.list_emails(uid, limit=limit)}
        for d in fs.list_emails(uid, limit=500, category="uncategorized"):
            docs.setdefault(d["id"], d)
    for doc in docs.values():
        email = EmailMessage(
            **{k: v for k, v in doc.items() if k in EmailMessage.model_fields}
        )
        category, confidence = clf.classify(email)
        # Only write what changed, so a re-run doesn't touch every doc.
        if (category, confidence) != (doc.get("category"), doc.get("confidence")):
            fs.set_category(uid, email.id, category, confidence)
        if category == "promotion":
            sub = extract_promo_subcategory(email)
            if sub != doc.get("promo_subcategory"):
                fs.set_promo_subcategory(uid, email.id, sub)
        if category != "subscription" and any(doc.get(f) for f in _SUB_FIELDS):
            # No longer a subscription: drop the details so it leaves the list.
            fs.set_subscription_info(uid, email.id, dict.fromkeys(_SUB_FIELDS))
        email.category = category
        due_date, due_label = extract_due_date(email) or (None, None)
        if (due_date, due_label) != (doc.get("due_date"), doc.get("due_label")):
            fs.set_due_date(uid, email.id, due_date, due_label)
        results.append({"id": email.id, "category": category, "confidence": confidence})
    return {"backend": clf.name, "classified": len(results), "results": results}


@router.post("/subscriptions")
def detect_subscriptions(uid: Uid):
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
