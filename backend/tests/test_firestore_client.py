import pytest
from datetime import datetime, timedelta, timezone
from conftest import mk
from fakefs import FakeDB
from app.services import firestore_client as fs

UID = "u1"
NOW = datetime.now(timezone.utc)

@pytest.fixture
def db(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    return f

def email_doc(id, category="subscription", days_ago=1, **kw):
    d = dict(id=id, thread_id="t", sender=kw.pop("sender", "Netflix <info@netflix.com>"),
             sender_email=kw.pop("sender_email", "info@netflix.com"), sender_domain=kw.pop("sender_domain", "netflix.com"),
             subject="", snippet="", body_text="", labels=[], category=category,
             date=NOW - timedelta(days=days_ago))
    d.update(kw)
    return d

# ------------------------------------------------ save_emails
def test_save_new_docs_full(db):
    n = fs.save_emails(UID, [mk(id="a", subject="hi"), mk(id="b")])
    assert n == 2
    doc = db.docs[("users", UID, "emails", "a")]
    for f in fs.DERIVED_FIELDS:
        assert f in doc and doc[f] is None, f
    assert "category" in doc and doc["category"] is None
    assert "synced_at" in doc and doc["subject"] == "hi"

def test_new_docs_found_by_uncategorized(db):
    fs.save_emails(UID, [mk(id="a", date=NOW)])
    assert [d["id"] for d in fs.list_emails(UID, category="uncategorized")] == ["a"]

def test_resync_keeps_derived_fields(db):
    db.put_email(UID, email_doc("a", category="bill", confidence=0.7, due_date="2026-10-03", due_label="Payment due",
                                sub_service="X", promo_subcategory="food", subject="old", labels=["UNREAD"]))
    fs.save_emails(UID, [mk(id="a", subject="new", labels=["INBOX"])])
    doc = db.docs[("users", UID, "emails", "a")]
    assert doc["category"] == "bill" and doc["confidence"] == 0.7
    assert doc["due_date"] == "2026-10-03" and doc["due_label"] == "Payment due"
    assert doc["sub_service"] == "X" and doc["promo_subcategory"] == "food"
    assert doc["subject"] == "new" and doc["labels"] == ["INBOX"]   # gmail fields refresh

def test_resync_real_value_overrides(db):
    db.put_email(UID, email_doc("a", category="bill"))
    fs.save_emails(UID, [mk(id="a", category="receipt")])
    assert db.docs[("users", UID, "emails", "a")]["category"] == "receipt"

def test_resync_write_payload_excludes_none_derived(db):
    db.put_email(UID, email_doc("a"))
    db.writes.clear()
    fs.save_emails(UID, [mk(id="a")])
    (_, data, merge), = db.writes
    assert merge is True
    assert not (set(data) & fs.DERIVED_FIELDS)
    assert "list_unsubscribe" in data  # gmail-derived, must refresh

def test_mixed_new_and_existing(db):
    db.put_email(UID, email_doc("old", category="bill"))
    fs.save_emails(UID, [mk(id="old"), mk(id="new")])
    assert db.docs[("users", UID, "emails", "old")]["category"] == "bill"
    assert db.docs[("users", UID, "emails", "new")]["category"] is None

def test_save_chunks_of_400(db):
    n = fs.save_emails(UID, [mk(id=f"m{i}") for i in range(850)])
    assert n == 850 and len(db.batches) == 3 and all(b.committed for b in db.batches)
    assert [len(b.ops) for b in db.batches] == [400, 400, 50]
    assert [r for r in db.reads if r[0] == "get_all"] == [("get_all", 400, ["id"]), ("get_all", 400, ["id"]), ("get_all", 50, ["id"])]

def test_save_empty(db):
    assert fs.save_emails(UID, []) == 0

def test_derived_fields_cover_model():
    # every classifier-filled field on the model should be protected
    for f in ["category", "confidence", "promo_subcategory", "sub_service", "sub_amount",
              "sub_cycle", "sub_renewal_hint", "due_date", "due_label"]:
        assert f in fs.DERIVED_FIELDS
    assert "list_unsubscribe" not in fs.DERIVED_FIELDS and "labels" not in fs.DERIVED_FIELDS

# ------------------------------------------------ list / set
def test_list_emails_order_and_limit(db):
    for i in range(5):
        db.put_email(UID, email_doc(f"e{i}", category="bill", days_ago=i))
    assert [d["id"] for d in fs.list_emails(UID, limit=3)] == ["e0", "e1", "e2"]
    assert [d["id"] for d in fs.list_emails(UID, category="bill", limit=2)] == ["e0", "e1"]
    assert fs.list_emails(UID, category="promotion") == []

def test_set_due_date(db):
    db.put_email(UID, email_doc("a", due_date="2026-01-01", due_label="Renews"))
    fs.set_due_date(UID, "a", "2026-10-03", "Payment due")
    d = db.docs[("users", UID, "emails", "a")]
    assert (d["due_date"], d["due_label"]) == ("2026-10-03", "Payment due")
    assert d["subject"] == ""  # merge, not overwrite
    fs.set_due_date(UID, "a", None, None)
    d = db.docs[("users", UID, "emails", "a")]
    assert d["due_date"] is None and d["due_label"] is None and d["id"] == "a"

def test_count_by_category(db):
    db.put_email(UID, email_doc("a", category="bill"))
    db.put_email(UID, email_doc("b", category="bill"))
    db.put_email(UID, email_doc("c", category=None))
    assert fs.count_by_category(UID) == {"bill": 2, "uncategorized": 1}

# ------------------------------------------------ subscriptions / merge
def test_list_subscriptions_unmerged_vs_merged(db):
    db.put_email(UID, email_doc("n1", days_ago=1, sub_service="Netflix", sub_amount="$15.49", sub_cycle="monthly"))
    db.put_email(UID, email_doc("n2", days_ago=5, sender_domain="members.netflix.com", sub_service="Netflix Account"))
    db.put_email(UID, email_doc("s1", days_ago=2, sender_domain="spotify.com", sub_service="Spotify", sub_amount="$11.99", sub_cycle="monthly"))
    raw = fs.list_subscriptions(UID, merged=False)
    assert [d["id"] for d in raw] == ["n1", "s1", "n2"]
    merged = fs.list_subscriptions(UID)
    assert len(merged) == 2
    net = next(m for m in merged if m["sub_service"] == "Netflix")
    assert net["sub_email_count"] == 2 and net["email_count"] == 2 and net["id"] == "n1"
    assert net["sub_amount"] == "$15.49" and net["is_stale"] is False and net["stale_reason"] is None
    assert net["last_seen"] == raw[0]["date"]

def test_merge_prefers_newest_with_amount_and_shortest_name():
    docs = [
        email_doc("a", days_ago=1, sender_domain="bestbuy.com", sub_service="Best Buy Labor Day Sale"),
        email_doc("b", days_ago=3, sender_domain="bestbuy.com", sub_service="Best Buy", sub_amount="$5.00"),
        email_doc("c", days_ago=4, sender_domain="bestbuy.com", sub_service="Best Buy Totaltech", sub_amount="$179.99"),
    ]
    (rep,) = fs._merge_by_service(docs)
    assert rep["id"] == "b" and rep["sub_service"] == "Best Buy" and rep["sub_email_count"] == 3

def test_merge_shared_domain_by_name_only():
    docs = [
        email_doc("a", sender_domain="paypal.com", sub_service="Hulu"),
        email_doc("b", sender_domain="paypal.com", sub_service="Spotify"),
        email_doc("c", sender_domain="paypal.com", sub_service="hulu"),
    ]
    out = fs._merge_by_service(docs)
    assert sorted(o["sub_email_count"] for o in out) == [1, 2]

def test_merge_by_name_across_domains():
    docs = [email_doc("a", sender_domain="netflix.com", sub_service="Netflix"),
            email_doc("b", sender_domain="gmail.com", sub_service="Netflix")]
    assert len(fs._merge_by_service(docs)) == 1

def test_merge_couk_domain():
    docs = [email_doc("a", sender_domain="netflix.co.uk", sub_service="A"),
            email_doc("b", sender_domain="mail.netflix.co.uk", sub_service="B")]
    assert len(fs._merge_by_service(docs)) == 1
    assert fs._domain_label("netflix.co.uk") == "netflix" and fs._domain_label("members.netflix.com") == "netflix"
    assert fs._domain_label("") == "" and fs._domain_label(None) == "" and fs._domain_label("localhost") == ""

def test_merge_transitive_chain():
    # a~b share domain, b~c share name -> all one group even though a,c share nothing
    docs = [email_doc("a", sender_domain="x.com", sub_service="Alpha"),
            email_doc("b", sender_domain="x.com", sub_service="Beta"),
            email_doc("c", sender_domain="y.com", sub_service="Beta")]
    assert len(fs._merge_by_service(docs)) == 1

def test_merge_no_keys_falls_back_to_id():
    docs = [email_doc("a", sender_domain="", sub_service=None), email_doc("b", sender_domain="", sub_service=None)]
    assert len(fs._merge_by_service(docs)) == 2

def test_merge_empty():
    assert fs._merge_by_service([]) == []

@pytest.mark.parametrize("cycle,days,stale", [
    ("monthly", 44, False), ("monthly", 45, True), ("trial", 44, False), ("trial", 45, True),
    ("yearly", 399, False), ("yearly", 400, True), (None, 59, False), (None, 60, True),
    ("weird", 60, True), ("weird", 59, False),
])
def test_stale_thresholds(cycle, days, stale):
    (rep,) = fs._merge_by_service([email_doc("a", days_ago=days, sub_cycle=cycle, sub_service="S")])
    assert rep["is_stale"] is stale
    if stale:
        plan = f" ({cycle} plan)" if cycle in ("monthly", "yearly") else ""
        assert rep["stale_reason"] == f"No email in {days} days{plan}"

def test_stale_uses_newest_member_date():
    docs = [email_doc("a", days_ago=10, sub_cycle="monthly", sub_service="S"),
            email_doc("b", days_ago=100, sub_cycle="monthly", sub_service="S")]
    (rep,) = fs._merge_by_service(docs)
    assert rep["is_stale"] is False and rep["last_seen"] == docs[0]["date"]

def test_stale_cycle_from_other_member():
    docs = [email_doc("a", days_ago=50, sub_service="S", sub_amount="$1.00"),
            email_doc("b", days_ago=60, sub_service="S", sub_cycle="yearly")]
    (rep,) = fs._merge_by_service(docs)
    assert rep["is_stale"] is False  # cycle yearly picked up from member b

@pytest.mark.parametrize("subject", ["We miss you!", "It's been a while", "Come back for 50% off",
    "You haven't used Hulu in a while", "Still interested?", "Reactivate your account", "We haven't seen you lately"])
def test_winback(subject):
    (rep,) = fs._merge_by_service([email_doc("a", days_ago=1, subject=subject, sub_service="S")])
    assert rep["is_stale"] and rep["stale_reason"] == "Service says you haven't been using it"

def test_winback_in_snippet_and_not_in_body():
    (r1,) = fs._merge_by_service([email_doc("a", snippet="we miss you", sub_service="S")])
    (r2,) = fs._merge_by_service([email_doc("a", body_text="we miss you", sub_service="S")])
    assert r1["is_stale"] and not r2["is_stale"]

def test_quiet_reason_beats_winback():
    (rep,) = fs._merge_by_service([email_doc("a", days_ago=90, subject="We miss you", sub_cycle="monthly", sub_service="S")])
    assert rep["stale_reason"] == "No email in 90 days (monthly plan)"

def test_no_date_not_stale():
    (rep,) = fs._merge_by_service([email_doc("a", date=None, sub_service="S")])
    assert rep["is_stale"] is False and rep["last_seen"] is None

def test_estimate_monthly_cost():
    subs = [{"sub_amount": "$12.00", "sub_cycle": "monthly"}, {"sub_amount": "$120.00", "sub_cycle": "yearly"},
            {"sub_amount": "$9.99", "sub_cycle": "trial"}, {"sub_amount": None}, {"sub_amount": "$1,200.00", "sub_cycle": None},
            {"sub_amount": "free"}]
    assert fs.estimate_monthly_cost(subs) == 1222.0

# ------------------------------------------------ unsubscribe suggestions
def promo(id, domain="shop.com", days_ago=1, unread=True, category="promotion", **kw):
    labels = ["UNREAD"] if unread else []
    labels += kw.pop("extra_labels", [])
    return email_doc(id, category=category, days_ago=days_ago, sender=f"Shop <news@{domain}>",
                     sender_email=kw.pop("sender_email", f"news@{domain}"), sender_domain=domain, labels=labels, **kw)

def test_suggest_all_unread_promos(db):
    for i in range(3): db.put_email(UID, promo(f"p{i}", days_ago=i, list_unsubscribe="https://shop.com/u" if i == 1 else None))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["count"] == 3 and s["reason"] == "3 promotional emails, none opened"
    assert s["category"] == "promotion" and s["latest_id"] == "p0" and s["service"] == "Shop"
    assert s["unsubscribe_url"] == "https://shop.com/u" and s["link_source"] == "header"
    assert set(s) == {"service", "sender", "sender_domain", "category", "count", "last_seen", "reason", "unsubscribe_url", "link_source", "latest_id"}

def test_suggest_two_unread_not_enough(db):
    for i in range(2): db.put_email(UID, promo(f"p{i}"))
    assert fs.unsubscribe_suggestions(UID) == []

def test_suggest_some_read_below_bulk(db):
    for i in range(5): db.put_email(UID, promo(f"p{i}", unread=i != 0))
    assert fs.unsubscribe_suggestions(UID) == []

def test_suggest_bulk_even_if_read(db):
    for i in range(6): db.put_email(UID, promo(f"p{i}", unread=i < 2))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["reason"] == "6 promotional emails, 2 unopened"

def test_suggest_starred_skipped(db):
    for i in range(8): db.put_email(UID, promo(f"p{i}", extra_labels=["STARRED"] if i == 3 else []))
    assert fs.unsubscribe_suggestions(UID) == []

def test_suggest_newsletter_kind(db):
    for i in range(3): db.put_email(UID, promo(f"n{i}", category="newsletter"))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["category"] == "newsletter" and s["reason"] == "3 newsletter emails, none opened"

def test_suggest_mixed_kind_is_promotion(db):
    db.put_email(UID, promo("a", category="newsletter")); db.put_email(UID, promo("b")); db.put_email(UID, promo("c"))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["category"] == "promotion"

def test_suggest_winback_under_min(db):
    db.put_email(UID, promo("a", subject="We miss you"))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["reason"] == "Sender says you haven't been engaging"

def test_suggest_winback_read_not_suggested(db):
    db.put_email(UID, promo("a", subject="We miss you", unread=False))
    assert fs.unsubscribe_suggestions(UID) == []

def test_suggest_group_by_registrable_domain(db):
    db.put_email(UID, promo("a", domain="em.shop.com")); db.put_email(UID, promo("b", domain="news.shop.com")); db.put_email(UID, promo("c", domain="shop.com"))
    (s,) = fs.unsubscribe_suggestions(UID)
    assert s["count"] == 3

def test_suggest_shared_domain_by_sender_email(db):
    db.put_email(UID, promo("a", domain="gmail.com", sender_email="a@gmail.com"))
    for i in range(3): db.put_email(UID, promo(f"b{i}", domain="gmail.com"))
    out = fs.unsubscribe_suggestions(UID)
    assert [s["count"] for s in out] == [3]

def test_suggest_stale_subscription_first_and_limit(db):
    db.put_email(UID, email_doc("s", days_ago=100, sub_cycle="monthly", sub_service="Netflix",
                                body_text="Unsubscribe: https://netflix.com/unsub?x=1."))
    for i in range(7): db.put_email(UID, promo(f"p{i}"))
    for i in range(3): db.put_email(UID, promo(f"q{i}", domain="other.com"))
    out = fs.unsubscribe_suggestions(UID)
    assert [s["category"] for s in out] == ["subscription", "promotion", "promotion"]
    assert out[0]["service"] == "Netflix" and out[0]["reason"] == "No email in 100 days (monthly plan)"
    assert out[0]["unsubscribe_url"] == "https://netflix.com/unsub?x=1" and out[0]["link_source"] == "body"
    assert [s["count"] for s in out[1:]] == [7, 3]
    assert len(fs.unsubscribe_suggestions(UID, limit=1)) == 1

def test_suggest_no_writes(db):
    for i in range(3): db.put_email(UID, promo(f"p{i}"))
    db.writes.clear(); fs.unsubscribe_suggestions(UID)
    assert db.writes == []

@pytest.mark.parametrize("body,expected", [
    ("[Unsubscribe](https://x.com/u/1)", "https://x.com/u/1"),
    ("Unsubscribe: https://x.com/prefs.", "https://x.com/prefs"),
    ("Unsubscribe <https://x.com/a>", "https://x.com/a"),
    ("Click https://x.com/unsubscribe?id=2 to stop", "https://x.com/unsubscribe?id=2"),
    ("https://x.com/opt-out", "https://x.com/opt-out"),
    ("Unsubscribe\nhttps://x.com/home", None),
    ("nothing here", None),
])
def test_body_unsubscribe_link(body, expected):
    link, src = fs._unsubscribe_link([{"body_text": body}])
    assert link == expected and src == ("body" if expected else None)

def test_header_link_beats_body():
    assert fs._unsubscribe_link([{"body_text": "https://x.com/unsub"}, {"list_unsubscribe": "mailto:u@x.com"}]) == ("mailto:u@x.com", "header")
