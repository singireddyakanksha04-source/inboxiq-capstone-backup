"""Step 2 test: prove we can write to and read from Firestore."""
import _bootstrap  # noqa: F401

from app.services import firestore_client as fs


def main() -> None:
    uid = fs.upsert_user("smoketest@example.com")
    print(f"wrote user doc: users/{uid}")
    print(f"read back      : {fs.get_user(uid)}")

    fs.db().collection("users").document(uid).delete()
    print("cleaned up. firestore round-trip OK.")


if __name__ == "__main__":
    main()
