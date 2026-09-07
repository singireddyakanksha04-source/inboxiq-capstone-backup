"""Step 3: the week's target workflow — Gmail -> backend -> Firestore."""
import _bootstrap  # noqa: F401
import argparse

from app.services import firestore_client as fs
from app.services.gmail_client import fetch_messages, get_profile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=25)
    ap.add_argument("--query", default="in:inbox")
    ap.add_argument("--account", default="default")
    args = ap.parse_args()

    address = get_profile(args.account)["emailAddress"]
    uid = fs.upsert_user(address)
    print(f"user {address} -> users/{uid}")

    messages = fetch_messages(args.count, args.query, args.account)
    print(f"fetched {len(messages)} messages from Gmail")

    print(f"wrote {fs.save_emails(uid, messages)} docs to Firestore")
    fs.mark_synced(uid)

    print("\nnewest stored:")
    for doc in fs.list_emails(uid, limit=5):
        print(f"  {doc['date']}  {doc['sender_domain']:<24} {doc['subject'][:50]}")


if __name__ == "__main__":
    main()
