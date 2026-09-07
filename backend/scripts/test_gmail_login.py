"""Step 1 test: log in to a Gmail account and read a few messages."""
import _bootstrap  # noqa: F401
import argparse

from app.services.gmail_client import fetch_messages, get_profile


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--query", default="in:inbox")
    ap.add_argument("--account", default="default")
    args = ap.parse_args()

    profile = get_profile(args.account)
    print(f"\nlogged in as : {profile['emailAddress']}")
    print(f"total messages: {profile['messagesTotal']}\n")

    for i, m in enumerate(fetch_messages(args.count, args.query, args.account), 1):
        print(f"--- {i} " + "-" * 60)
        print(f"from    : {m.sender}")
        print(f"domain  : {m.sender_domain}")
        print(f"subject : {m.subject}")
        print(f"date    : {m.date}")
        print(f"labels  : {', '.join(m.labels)}")
        print(f"body    : {m.body_text[:200].replace(chr(10), ' ')}...")
    print()


if __name__ == "__main__":
    main()
