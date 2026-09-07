"""Run a classifier over emails already stored in Firestore, write categories back."""
import _bootstrap  # noqa: F401
import argparse

from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services.classifier import get_classifier


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", required=True, help="from sync_inbox.py output")
    ap.add_argument("--backend", default="rules", help="rules | small | large | qwen")
    ap.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    clf = get_classifier(args.backend)
    print(f"backend: {clf.name}\n")

    for doc in fs.list_emails(args.uid, limit=args.limit):
        email = EmailMessage(**{k: v for k, v in doc.items() if k in EmailMessage.model_fields})
        category, confidence = clf.classify(email)
        fs.set_category(args.uid, email.id, category, confidence)
        print(f"  {category:<13} {confidence:.2f}  {email.subject[:55]}")

    print("\ncounts:", fs.count_by_category(args.uid))


if __name__ == "__main__":
    main()
