from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.services import firestore_client as fs
from fakefs import FakeDB

@pytest.fixture
def mailbox(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: db)
    from app.main import app
    for i in range(23):
        db.put_email("u1", {"id":f"s{i:02}", "subject":"Running offer", "sender":"Shop", "category":"promotion", "promo_subcategory":"shopping", "date":datetime(2026,10,1,tzinfo=timezone.utc)})
    for id, tag, category, uid in [("food","food","promotion","u1"),("education","education","promotion","u1"),("unknown",None,"promotion","u1"),("unrecognized","custom","promotion","u1"),("wrong-category","shopping","newsletter","u1"),("other-account","shopping","promotion","u2")]:
        db.put_email(uid,{"id":id,"subject":"Running offer","sender":"Shop","category":category,"promo_subcategory":tag,"date":datetime(2026,10,1,tzinfo=timezone.utc)})
    return db, TestClient(app)

def page(client, **params):
    return client.get("/api/emails/search/page",params={"uid":"u1","category":"promotion","limit":20,**params})

def test_subcategory_only_uses_existing_tags_and_twenty_message_pages(mailbox):
    db, client = mailbox
    first=page(client,subcategory="shopping").json();second=page(client,subcategory="shopping",offset=20).json()
    assert first["total_matches"]==second["total_matches"]==23
    assert len(first["items"])==20 and len(second["items"])==3
    assert first["next_offset"]==20 and second["next_offset"] is None
    assert [r["id"] for r in first["items"]+second["items"]]==[f"s{i:02}" for i in range(23)]
    assert db.writes==[] and db.batches==[]

@pytest.mark.parametrize("tag,ids",[("food",["food"]),("education",["education"]),("other",["unknown","unrecognized"])])
def test_supported_and_unknown_buckets(mailbox,tag,ids):
    data=page(mailbox[1],subcategory=tag).json()
    assert sorted(r["id"] for r in data["items"])==sorted(ids)
    assert data["total_matches"]==len(ids)

def test_combines_text_sender_dates_and_preserves_scope(mailbox):
    data=page(mailbox[1],subcategory="shopping",q="running",sender="shop",after="2026-10-01",before="2026-10-01").json()
    assert data["total_matches"]==23
    assert page(mailbox[1],subcategory="shopping",q="nomatch").json()["total_matches"]==0
    assert page(mailbox[1],subcategory="shopping",after="2026-10-02").json()["total_matches"]==0

@pytest.mark.parametrize("params",[{"subcategory":"unsupported"},{"subcategory":"shopping","category":"newsletter"},{"subcategory":"shopping","category":""}])
def test_invalid_or_wrong_mailbox_filter_rejected(mailbox,params):
    assert page(mailbox[1],**params).status_code==422
