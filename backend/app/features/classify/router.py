"""Categorising stored mail. Owner: Satwik."""

from fastapi import APIRouter, Query

from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services.classifier import CATEGORIES, get_classifier

router = APIRouter(prefix="/api/classify", tags=["classify"])


@router.get("/backends")
def backends():
    return {"backends": ["rules", "small", "large", "qwen"], "categories": CATEGORIES}


@router.post("")
def classify(uid: str, backend: str = "rules", limit: int = Query(25, le=200)):
    clf = get_classifier(backend)
    results = []
    for doc in fs.list_emails(uid, limit=limit):
        email = EmailMessage(
            **{k: v for k, v in doc.items() if k in EmailMessage.model_fields}
        )
        category, confidence = clf.classify(email)
        fs.set_category(uid, email.id, category, confidence)
        results.append({"id": email.id, "category": category, "confidence": confidence})
    return {"backend": clf.name, "classified": len(results), "results": results}
