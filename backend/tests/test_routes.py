import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from fakefs import FakeDB
from app.services import firestore_client as fs

NOW = datetime.now(timezone.utc)
UID = "u1"

@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    from app.main import app
    return TestClient(app), f

def doc(id, days_ago=0, **kw):
    d = dict(id=id, thread_id="t", sender="A <a@a.com>", sender_email="a@a.com", sender_domain="a.com",
             subject="", snippet="", body_text="", labels=[], date=NOW - timedelta(days=days_ago),
             category=None, confidence=None, due_date=None, due_label=None)
    d.update(kw); return d

def writes_for(f, id):
    return [w for w in f.writes if w[0][-1] == id]

def test_health(env):
    c, _ = env
    r = c.get("/health"); assert r.status_code == 200
    assert r.json()["status"] == "ok" and set(r.json()["features"]) == {"auth", "classify", "emails", "ingest"}

def test_backends(env):
    c, _ = env
    j = c.get("/api/classify/backends").json()
    assert j["backends"] == ["rules", "small", "large", "qwen"] and len(j["categories"]) == 11

def test_classify_basic(env):
    c, f = env
    f.put_email(UID, doc("a", subject="Your order has shipped"))
    f.put_email(UID, doc("b", days_ago=1, subject="20% off shoes"))
    f.put_email(UID, doc("c", days_ago=2, subject="Payment due Oct 3", date=datetime(2026, 9, 20, tzinfo=timezone.utc)))
    f.writes.clear()
    r = c.post("/api/classify", params={"uid": UID})
    assert r.status_code == 200
    j = r.json()
    assert j["backend"] == "rules" and j["classified"] == 3
    got = {x["id"]: x["category"] for x in j["results"]}
    assert got == {"a": "shipping", "b": "promotion", "c": "bill"}
    assert all(set(x) == {"id", "category", "confidence"} for x in j["results"])
    d = f.docs
    assert d[("users", UID, "emails", "b")]["promo_subcategory"] == "clothing"
    assert (d[("users", UID, "emails", "c")]["due_date"], d[("users", UID, "emails", "c")]["due_label"]) == ("2026-10-03", "Payment due")
    # no due-date write for a/b (None == None unchanged)
    assert not any("due_date" in w[1] for w in writes_for(f, "a") + writes_for(f, "b"))

def test_classify_due_date_unchanged_not_rewritten(env):
    c, f = env
    f.put_email(UID, doc("c", subject="Payment due Oct 3", date=datetime(2026, 9, 20, tzinfo=timezone.utc),
                         due_date="2026-10-03", due_label="Payment due"))
    f.writes.clear()
    c.post("/api/classify", params={"uid": UID})
    assert not any("due_date" in w[1] for w in f.writes)

def test_classify_stale_due_date_cleared(env):
    c, f = env
    f.put_email(UID, doc("c", subject="Hello", due_date="2026-10-03", due_label="Payment due"))
    c.post("/api/classify", params={"uid": UID})
    x = f.docs[("users", UID, "emails", "c")]
    assert x["due_date"] is None and x["due_label"] is None

def test_classify_due_date_changed_rewritten(env):
    c, f = env
    f.put_email(UID, doc("c", subject="Payment due Oct 3", date=datetime(2026, 9, 20, tzinfo=timezone.utc),
                         due_date="2026-10-01", due_label="Payment due"))
    c.post("/api/classify", params={"uid": UID})
    assert f.docs[("users", UID, "emails", "c")]["due_date"] == "2026-10-03"

def test_classify_older_uncategorized_pickup(env):
    c, f = env
    for i in range(5):
        f.put_email(UID, doc(f"new{i}", days_ago=i, category="other"))
    f.put_email(UID, doc("old", days_ago=100, category=None, subject="Your receipt"))
    f.put_email(UID, doc("old_categorized", days_ago=101, category="other"))
    j = c.post("/api/classify", params={"uid": UID, "limit": 2}).json()
    # rules re-check every stored email, not just the newest `limit`
    ids = [x["id"] for x in j["results"]]
    assert ids == ["new0", "new1", "new2", "new3", "new4", "old", "old_categorized"]
    assert f.docs[("users", UID, "emails", "old")]["category"] == "receipt"

def test_classify_missing_category_field_picked_by_rules(env):
    # docs stored before save_emails wrote category=None explicitly have no field at all;
    # the rules backend re-checks all stored mail, so they are picked up too.
    c, f = env
    d = doc("legacy", days_ago=100); d.pop("category")
    f.put_email(UID, d)
    f.put_email(UID, doc("n", category="other"))
    j = c.post("/api/classify", params={"uid": UID, "limit": 1}).json()
    assert [x["id"] for x in j["results"]] == ["n", "legacy"]

def test_classify_extra_fields_ignored(env):
    c, f = env
    f.put_email(UID, doc("a", synced_at=NOW, sub_email_count=3, weird="x"))
    assert c.post("/api/classify", params={"uid": UID}).status_code == 200

def test_classify_limit_validation(env):
    c, _ = env
    assert c.post("/api/classify", params={"uid": UID, "limit": 201}).status_code == 422
    assert c.post("/api/classify", params={"uid": UID, "limit": "abc"}).status_code == 422
    assert c.post("/api/classify").status_code == 422  # uid required

def test_classify_empty(env):
    c, _ = env
    assert c.post("/api/classify", params={"uid": "nobody"}).json() == {"backend": "rules", "classified": 0, "results": []}

def test_detect_subscriptions(env):
    c, f = env
    f.put_email(UID, doc("s", category="subscription", sender="Netflix <x@netflix.com>", sender_domain="netflix.com",
                         body_text="Your plan is $15.49/month"))
    j = c.post("/api/classify/subscriptions", params={"uid": UID}).json()
    assert j["detected"] == 1 and j["results"][0]["sub_amount"] == "$15.49"
    assert f.docs[("users", UID, "emails", "s")]["sub_service"] == "Netflix"

def test_emails_list(env):
    c, f = env
    for i in range(3): f.put_email(UID, doc(f"e{i}", days_ago=i, category="bill"))
    r = c.get("/api/emails", params={"uid": UID, "limit": 2})
    assert r.status_code == 200 and [x["id"] for x in r.json()] == ["e0", "e1"]
    assert c.get("/api/emails", params={"uid": UID, "category": "promotion"}).json() == []
    assert c.get("/api/emails", params={"uid": UID, "limit": "x"}).status_code == 422
    assert c.get("/api/emails").status_code == 422

def test_emails_list_uncategorized(env):
    c, f = env
    f.put_email(UID, doc("a", category=None)); f.put_email(UID, doc("b", category="bill"))
    assert [x["id"] for x in c.get("/api/emails", params={"uid": UID, "category": "uncategorized"}).json()] == ["a"]

def test_emails_list_negative_limit(env):
    c, f = env
    f.put_email(UID, doc("a"))
    r = c.get("/api/emails", params={"uid": UID, "limit": -1})
    assert r.status_code == 422

def test_stats(env):
    c, f = env
    f.put_email(UID, doc("a", category="bill")); f.put_email(UID, doc("b"))
    assert c.get("/api/emails/stats", params={"uid": UID}).json() == {"by_category": {"bill": 1, "uncategorized": 1}}
    assert c.get("/api/emails/stats").status_code == 422

def test_subscriptions_route(env):
    c, f = env
    f.put_email(UID, doc("n", category="subscription", sender_domain="netflix.com", sub_service="Netflix", sub_amount="$15.49", sub_cycle="monthly"))
    f.put_email(UID, doc("h", days_ago=90, category="subscription", sender_domain="hulu.com", sub_service="Hulu", sub_amount="$7.99", sub_cycle="monthly"))
    f.put_email(UID, doc("y", days_ago=2, category="subscription", sender_domain="yt.com", sub_service="YT", subject="We miss you"))
    r = c.get("/api/emails/subscriptions", params={"uid": UID})
    assert r.status_code == 200
    j = r.json()
    assert set(j) == {"items", "estimated_monthly_cost", "stale_count"}
    assert j["stale_count"] == 2 and j["estimated_monthly_cost"] == 23.48 and len(j["items"]) == 3
    for it in j["items"]:
        assert {"is_stale", "stale_reason", "last_seen", "email_count", "sub_email_count"} <= set(it)

def test_subscriptions_empty(env):
    c, _ = env
    assert c.get("/api/emails/subscriptions", params={"uid": "x"}).json() == {"items": [], "estimated_monthly_cost": 0.0, "stale_count": 0}

def test_unsubscribe_suggestions_route(env):
    c, f = env
    for i in range(3):
        f.put_email(UID, doc(f"p{i}", days_ago=i, category="promotion", labels=["UNREAD"], sender="Shop <n@shop.com>",
                             sender_email="n@shop.com", sender_domain="shop.com"))
    f.writes.clear()
    r = c.get("/api/emails/unsubscribe-suggestions", params={"uid": UID})
    assert r.status_code == 200 and len(r.json()["items"]) == 1 and f.writes == []
    assert c.get("/api/emails/unsubscribe-suggestions", params={"uid": UID, "limit": 0}).status_code == 422
    assert c.get("/api/emails/unsubscribe-suggestions", params={"uid": UID, "limit": "z"}).status_code == 422

def test_route_order_not_shadowed(env):
    # /subscriptions etc. must not be captured by /{message_id}
    c, _ = env
    assert c.get("/api/emails/stats", params={"uid": UID}).status_code == 200

def test_get_email(env):
    c, f = env
    f.put_email(UID, doc("a", subject="hi"))
    assert c.get("/api/emails/a", params={"uid": UID}).json()["subject"] == "hi"
    r = c.get("/api/emails/nope", params={"uid": UID})
    assert r.status_code == 404 and r.json() == {"detail": "email not found"}
