"""Satwik's experiment: score backends against a hand-labelled set.

Workflow
  1. python scripts/sync_inbox.py --count 40
  2. python scripts/compare_models.py --uid <uid> --make-labels
     -> writes labels.json with category "" for each email; fill them in by hand
  3. python scripts/compare_models.py --uid <uid> --backends rules small large
"""
import _bootstrap  # noqa: F401
import argparse
import json
import time
from pathlib import Path

from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services.classifier import CATEGORIES, get_classifier

LABELS = Path(__file__).parent / "labels.json"


def _load(uid: str, limit: int) -> list[EmailMessage]:
    return [
        EmailMessage(**{k: v for k, v in d.items() if k in EmailMessage.model_fields})
        for d in fs.list_emails(uid, limit=limit)
    ]


def make_labels(uid: str, limit: int) -> None:
    rows = [
        {"id": e.id, "subject": e.subject, "sender": e.sender_domain, "category": ""}
        for e in _load(uid, limit)
    ]
    LABELS.write_text(json.dumps(rows, indent=2))
    print(f"wrote {len(rows)} rows to {LABELS}")
    print(f"fill in 'category' for each, using: {', '.join(CATEGORIES)}")


def score(uid: str, backends: list[str], limit: int) -> None:
    if not LABELS.exists():
        raise SystemExit("no labels.json — run with --make-labels first")

    truth = {r["id"]: r["category"] for r in json.loads(LABELS.read_text()) if r["category"]}
    if not truth:
        raise SystemExit("labels.json has no filled-in categories yet")

    emails = [e for e in _load(uid, limit) if e.id in truth]
    print(f"scoring {len(emails)} labelled emails\n")

    for backend in backends:
        clf = get_classifier(backend)
        correct = 0
        confusion: dict[tuple[str, str], int] = {}
        started = time.perf_counter()

        for email in emails:
            predicted, _ = clf.classify(email)
            actual = truth[email.id]
            correct += predicted == actual
            if predicted != actual:
                confusion[(actual, predicted)] = confusion.get((actual, predicted), 0) + 1

        elapsed = time.perf_counter() - started
        accuracy = correct / len(emails)
        print(f"{clf.name:<26} acc {accuracy:6.1%}  ({correct}/{len(emails)})  "
              f"{elapsed:5.1f}s  {elapsed / len(emails):.2f}s/email")
        for (actual, predicted), n in sorted(confusion.items(), key=lambda x: -x[1])[:5]:
            print(f"    missed {n}x: {actual} -> {predicted}")
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--uid", required=True)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--make-labels", action="store_true")
    ap.add_argument("--backends", nargs="+", default=["rules", "small"])
    args = ap.parse_args()

    if args.make_labels:
        make_labels(args.uid, args.limit)
    else:
        score(args.uid, args.backends, args.limit)


if __name__ == "__main__":
    main()
