from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from app.services import firestore_client as fs
from fakefs import FakeDB

@pytest.fixture
def mailbox(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: db)
    from app.main import app
    return db, TestClient(app)

def put(db, i, uid="u1", category="promotion"):
    db.put_email(uid, {"id": f"m{i:03}", "subject": "Running offer", "sender": "Shop <shop@example.com>",
        "sender_email": "shop@example.com", "category": category,
        "date": datetime(2026, 10, 1, tzinfo=timezone.utc) - timedelta(hours=i)})

def test_twenty_message_pages_cover_all_matches_once_and_report_total(mailbox):
    db, client = mailbox
    for i in range(42): put(db, i)
    seen = []
    for offset, expected_size, next_offset in [(0, 20, 20), (20, 20, 40), (40, 2, None)]:
        response = client.get("/api/emails/search/page", params={"uid":"u1", "q":"running", "limit":20, "offset":offset})
        assert response.status_code == 200
        data = response.json()
        assert data["total_matches"] == 42
        assert len(data["items"]) == expected_size
        assert data["next_offset"] == next_offset
        seen.extend(row["id"] for row in data["items"])
    assert seen == [f"m{i:03}" for i in range(42)]
    assert db.writes == [] and db.batches == []

def test_total_is_filter_and_account_scoped(mailbox):
    db, client = mailbox
    for i in range(30): put(db, i)
    put(db, 31, category="newsletter")
    put(db, 32, uid="u2")
    data = client.get("/api/emails/search/page", params={"uid":"u1", "sender":"shop", "category":"promotion", "after":"2026-10-01", "before":"2026-10-01", "limit":20}).json()
    assert data["total_matches"] == 1
    assert [row["id"] for row in data["items"]] == ["m000"]

def test_total_never_claims_unsynced_or_beyond_window_messages(mailbox):
    db, client = mailbox
    for i in range(505): put(db, i)
    data = client.get("/api/emails/search/page", params={"uid":"u1", "q":"running", "limit":20, "offset":480}).json()
    assert data["total_matches"] == data["search_window"] == 500
    assert len(data["items"]) == 20 and data["next_offset"] is None
    assert data["items"][-1]["id"] == "m499"
