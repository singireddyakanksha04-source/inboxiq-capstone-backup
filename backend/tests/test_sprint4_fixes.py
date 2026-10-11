"""TDD cases for the Sprint 4 follow-up fixes: recurring payment receipts as
subscriptions, service names, billing cycle from a billing period, due-date
noise, full re-classification on sync, billing mail pulled on sync, and
input validation."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from conftest import mk
from fakefs import FakeDB
from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services.classifier import RuleClassifier, extract_subscription_info
from app.services.deadlines import extract_due_date
import importlib

clf = RuleClassifier()

NIMBUS_BODY = (
    "Receipt from Nimbus Labs, PBC\nAmount paid $20.00\nDate paid September 3, 2026\n"
    "Payment method Visa - 4242\nSummary\nNimbus Pro  Sep 3 - Oct 3, 2026  $20.00\n"
    "Total $20.00\nAmount paid $20.00"
)
NIMBUS = dict(
    subject="Your receipt from Nimbus Labs, PBC #2345-6789",
    sender='"Nimbus Labs, PBC" <invoice+statements@mail.nimbuslabs.com>',
    snippet="Receipt from Nimbus Labs, PBC $20.00 Paid September 3, 2026",
    body=NIMBUS_BODY, labels=["CATEGORY_UPDATES"],
)

# ------------------------------------------------ recurring receipts -> subscription

RECURRING = [
    ("nimbus_pro", NIMBUS),
    ("chatgpt_plus", dict(
        subject="Your ChatGPT receipt", sender="OpenAI <noreply@tm.openai.com>",
        body="Receipt\nChatGPT Plus Subscription\nQty 1  $20.00\nBilling period Sep 5 - Oct 5, 2026\nAmount paid $20.00")),
    ("spotify_premium", dict(
        subject="Your Spotify Premium receipt", sender="Spotify <no-reply@spotify.com>",
        body="Thanks for your payment. Premium Individual $11.99/month. Next billing date: October 12, 2026.")),
    ("netflix_payment", dict(
        subject="Your Netflix payment was successful", sender="Netflix <info@account.netflix.com>",
        body="We charged $15.49 for your Standard plan. Your next payment is on October 9, 2026. Billed monthly.")),
    ("icloud_apple", dict(
        subject="Your receipt from Apple.", sender="Apple <no_reply@email.apple.com>",
        body="Receipt\niCloud+ with 50 GB of storage\nMonthly\nRenews October 1, 2026\n$0.99")),
    ("youtube_premium", dict(
        subject="Your Google Play Order Receipt from Sep 14, 2026", sender="Google Play <googleplay-noreply@google.com>",
        body="YouTube Premium (YouTube) Subscription $13.99/month\nAuto-renewing subscription\nTotal: $13.99/month")),
    ("invoice_paid_membership", dict(
        subject="Invoice paid - Gym membership", sender="PureGym <billing@puregym.com>",
        body="Your monthly membership invoice has been paid. Amount paid $29.99.")),
]


@pytest.mark.parametrize("kw", [k for _, k in RECURRING], ids=[n for n, _ in RECURRING])
def test_recurring_receipt_is_subscription(kw):
    assert clf.classify(mk(**kw))[0] == "subscription"


ONE_OFF = [
    ("lyft_ride", dict(subject="Your ride with Shyanne on September 15", sender="Lyft <no-reply@lyftmail.com>",
                       body="Lyft receipt. Thanks for riding with Lyft. Total charged $14.20. Visa 4242."), "receipt"),
    ("nj_transit", dict(subject="NJ TRANSIT - Receipt", sender="NJ TRANSIT <noreply@mytix.njtransit.com>",
                        body="Receipt. One-way ticket Newark to Princeton. Amount paid $12.50."), "receipt"),
    ("amazon_order", dict(subject="Your Amazon.com order #112-555", sender="Amazon.com <auto-confirm@amazon.com>",
                          body="Thanks for your order. Order total $45.10. Arriving Friday."), "receipt"),
    ("order_confirmation", dict(subject="Order confirmation #1234"), "receipt"),
    ("card_payment_received", dict(subject="We received your payment", sender="Chase <no.reply@chase.com>",
                                   body="Thanks for your payment of $120.00. Minimum payment due Oct 3 on your monthly statement."), "bill"),
    ("utility_autopay", dict(subject="Your payment was successful", sender="PSE&G <billing@pseg.com>",
                             body="Autopay payment received for your monthly bill. Amount paid $84.10."), "bill"),
    ("order_confirmed", dict(subject="Your order is confirmed"), "receipt"),
    ("plan_word_one_off", dict(subject="Receipt for your purchase", sender="Best Buy <x@bestbuy.com>",
                               body="Thanks for your purchase. Total $299.99. Protection plan sold separately."), "receipt"),
    # Deal mail filed under Promotions with subscription fine print stays a promotion.
    ("udemy_promo_fineprint", dict(
        subject="Last chance to save on a year of learning.", sender="Udemy <hello@students.udemy.com>",
        labels=["CATEGORY_PROMOTIONS"],
        body="Learn AI with an annual Personal Plan subscription. " * 3
        + "Subscription auto-renews at then-applicable yearly pricing after first year unless canceled."), "promotion"),
    ("promo_tab_receipt_word", dict(
        subject="Get 3 months of Premium for $0", sender="Spotify <no-reply@spotify.com>",
        labels=["CATEGORY_PROMOTIONS"], body="Individual plan only. $11.99/month after. Receipt sent on signup."), None),
]


@pytest.mark.parametrize("kw,expected", [(k, e) for _, k, e in ONE_OFF], ids=[n for n, _, _ in ONE_OFF])
def test_one_off_and_promo_are_not_subscription(kw, expected):
    got = clf.classify(mk(**kw))[0]
    assert got != "subscription"
    if expected:
        assert got == expected


# ------------------------------------------------ subscription details

INFO = [
    ("nimbus", NIMBUS, dict(sub_service="Nimbus Pro", sub_amount="$20.00", sub_cycle="monthly")),
    ("chatgpt", RECURRING[1][1], dict(sub_service="ChatGPT Plus", sub_amount="$20.00", sub_cycle="monthly")),
    ("spotify", RECURRING[2][1], dict(sub_service="Spotify Premium", sub_amount="$11.99", sub_cycle="monthly")),
    ("netflix", RECURRING[3][1], dict(sub_service="Netflix", sub_amount="$15.49", sub_cycle="monthly")),
    ("youtube_via_google_play", RECURRING[5][1], dict(sub_service="YouTube Premium", sub_amount="$13.99", sub_cycle="monthly")),
    ("yearly_period", dict(subject="Receipt", sender="Notion <team@makenotion.com>",
                           body="Notion Plus  Sep 3, 2026 - Sep 3, 2027  $96.00\nAmount paid $96.00"),
     dict(sub_service="Notion Plus", sub_amount="$96.00", sub_cycle="yearly")),
    ("numeric_period", dict(subject="Receipt", sender="Dropbox <no-reply@dropbox.com>",
                            body="Dropbox Plus 09/03/2026 - 10/03/2026 Amount paid $11.99"),
     dict(sub_service="Dropbox Plus", sub_cycle="monthly")),
    ("legal_suffix_inc", dict(subject="Receipt", sender='"Hulu, Inc." <billing@hulu.com>', body="Amount paid $7.99"),
     dict(sub_service="Hulu")),
    ("legal_suffix_llc", dict(subject="Receipt", sender="Acme Streaming LLC <billing@acmestream.com>", body="x"),
     dict(sub_service="Acme Streaming")),
    ("bare_address_sender", dict(subject="x", sender="noreply@spotify.com"), dict(sub_service="Spotify")),
    ("bare_couk_sender", dict(subject="x", sender="noreply@netflix.co.uk"), dict(sub_service="Netflix")),
    ("plan_word_not_a_tier", dict(subject="Your plan renews on Oct 3", sender="Netflix <info@account.netflix.com>",
                                  body="Netflix standard features continue."), dict(sub_service="Netflix")),
]


@pytest.mark.parametrize("kw,expected", [(k, e) for _, k, e in INFO], ids=[n for n, _, _ in INFO])
def test_subscription_details(kw, expected):
    info = extract_subscription_info(mk(**kw))
    assert set(info) == {"sub_service", "sub_amount", "sub_cycle", "sub_renewal_hint"}
    for k, v in expected.items():
        assert info[k] == v, f"{k}: {info}"


def test_nimbus_receipts_merge_into_one_service():
    docs = []
    for i, month in enumerate((9, 8, 7)):
        e = mk(id=f"c{i}", **NIMBUS)
        docs.append({**e.model_dump(), **extract_subscription_info(e),
                     "date": datetime(2026, month, 3, tzinfo=timezone.utc), "category": "subscription"})
    merged = fs._merge_by_service(docs)
    assert len(merged) == 1
    assert merged[0]["sub_service"] == "Nimbus Pro" and merged[0]["sub_email_count"] == 3


# ------------------------------------------------ promo subcategory plurals

@pytest.mark.parametrize("subject", ["Cheap flights to Paris", "Hotels from $59", "Resorts on sale"])
def test_promo_plural_travel(subject):
    from app.services.classifier import extract_promo_subcategory
    assert extract_promo_subcategory(mk(subject=subject)) == "travel"


# ------------------------------------------------ due-date noise

SENT = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)


def due(category, sender="Someone <a@example.com>", **kw):
    return extract_due_date(mk(category=category, date=SENT, sender=sender, **kw))


DUE = [
    ("linkedin_quoted_post", dict(category="alert", sender="LinkedIn <jobs-noreply@linkedin.com>",
                                  subject="Remote Jobs recently posted",
                                  body="Excited to kick off our AI Policy Fellowship. Applications are due on Sep 25th."), None),
    ("alert_job_apply_by", dict(category="alert", sender="Indeed <alert@indeed.com>",
                                body="Data Analyst at Acme. Apply by September 30, 2026."), None),
    ("alert_webinar_still_event", dict(category="alert", body="The webinar is on October 1, 2026"), ("2026-10-01", "Event")),
    ("alert_card_expires_kept", dict(category="alert", body="Your card expires on October 31, 2026"), ("2026-10-31", "Expires")),
    ("other_season_ends", dict(category="other", body="The season ends Oct 3"), None),
    ("other_offer_ends", dict(category="other", body="Offer ends October 3, 2026"), None),
    ("sub_trial_ends", dict(category="subscription", body="Your free trial ends on October 3, 2026"), ("2026-10-03", "Renews")),
    ("sub_plan_ends", dict(category="subscription", body="Your plan ends on October 3, 2026"), ("2026-10-03", "Expires")),
    ("sub_membership_ends", dict(category="subscription", body="Your membership ends Oct 3"), ("2026-10-03", "Expires")),
    ("personal_apply_by_kept", dict(category="personal", body="Please apply here by September 30, 2026."), ("2026-09-30", "Deadline")),
    ("bill_still_works", dict(category="bill", subject="Payment due by Oct 3"), ("2026-10-03", "Payment due")),
    ("receipt_next_payment", dict(category="subscription", body="Your next payment is on October 9, 2026."), ("2026-10-09", "Renews")),
]


@pytest.mark.parametrize("kw,expected", [(k, e) for _, k, e in DUE], ids=[n for n, _, _ in DUE])
def test_due_noise(kw, expected):
    assert due(**kw) == expected


# ------------------------------------------------ routes

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
    d.update(kw)
    return d


def test_rules_classify_rechecks_old_mail_outside_limit(env):
    """Old mail sorted by older rules gets re-sorted, not just the newest `limit`."""
    c, f = env
    for i in range(5):
        f.put_email(UID, doc(f"new{i}", days_ago=i, subject="20% off shoes", category="promotion"))
    f.put_email(UID, doc("old", days_ago=30, subject="Last chance to save on a year of learning.",
                         labels=["CATEGORY_PROMOTIONS"], category="subscription", confidence=0.7))
    r = c.post("/api/classify", params={"uid": UID, "limit": 2})
    assert r.status_code == 200
    assert f.docs[("users", UID, "emails", "old")]["category"] == "promotion"


def test_classify_skips_write_when_category_unchanged(env):
    c, f = env
    f.put_email(UID, doc("a", subject="20% off shoes", category="promotion", confidence=0.7,
                         promo_subcategory="clothing"))
    f.writes.clear()
    c.post("/api/classify", params={"uid": UID})
    assert not [w for w in f.writes if "category" in w[1]]


def test_classify_drops_subscription_fields_when_no_longer_subscription(env):
    c, f = env
    f.put_email(UID, doc("u", subject="Last chance to save", labels=["CATEGORY_PROMOTIONS"],
                         category="subscription", sub_service="Udemy", sub_cycle="yearly"))
    c.post("/api/classify", params={"uid": UID})
    stored = f.docs[("users", UID, "emails", "u")]
    assert stored["category"] == "promotion" and stored.get("sub_service") is None


def test_sync_pulls_billing_mail_too(env, monkeypatch):
    c, f = env
    ingest = importlib.import_module("app.features.ingest.router")
    calls = []

    def fake_fetch(count, q, account, skip=frozenset()):
        calls.append((count, q))
        if "receipt" in q:
            return [m for m in [EmailMessage(id="bill1", thread_id="t", subject="Your receipt from Nimbus Labs, PBC",
                                 sender="Nimbus Labs <x@mail.nimbuslabs.com>", sender_email="x@mail.nimbuslabs.com",
                                 sender_domain="mail.nimbuslabs.com", date=NOW - timedelta(days=40)),
                    EmailMessage(id="dup", thread_id="t", subject="dup", sender="A <a@a.com>", sender_email="a@a.com", sender_domain="a.com", date=NOW)] if m.id not in skip]
        return [EmailMessage(id="dup", thread_id="t", subject="dup", sender="A <a@a.com>", sender_email="a@a.com", sender_domain="a.com", date=NOW)]

    monkeypatch.setattr(ingest, "fetch_messages", fake_fetch)
    monkeypatch.setattr(ingest, "get_profile", lambda account: {"emailAddress": "a@b.com"})
    r = c.post("/api/ingest/sync", params={"count": 10, "billing": 20})
    assert r.status_code == 200
    assert len(calls) == 2 and calls[1][0] == 20
    assert r.json()["stored"] == 2  # duplicates across the two pulls stored once
    uid = r.json()["uid"]
    assert ("users", uid, "emails", "bill1") in f.docs


def test_sync_without_billing_makes_one_call(env, monkeypatch):
    c, f = env
    ingest = importlib.import_module("app.features.ingest.router")
    calls = []
    monkeypatch.setattr(ingest, "fetch_messages", lambda count, q, account, skip=frozenset(): calls.append(q) or [])
    monkeypatch.setattr(ingest, "get_profile", lambda account: {"emailAddress": "a@b.com"})
    c.post("/api/ingest/sync", params={"count": 10})
    assert len(calls) == 1


@pytest.mark.parametrize("method,path,params", [
    ("get", "/api/emails", {"uid": UID, "limit": 0}),
    ("get", "/api/emails", {"uid": UID, "limit": -5}),
    ("post", "/api/classify", {"uid": UID, "limit": 0}),
    ("post", "/api/ingest/sync", {"count": 0}),
    ("post", "/api/ingest/sync", {"count": 10, "billing": -1}),
    ("get", "/api/emails/unsubscribe-suggestions", {"uid": UID, "limit": 0}),
])
def test_limits_must_be_positive(env, monkeypatch, method, path, params):
    c, _ = env
    ingest = importlib.import_module("app.features.ingest.router")
    monkeypatch.setattr(ingest, "fetch_messages", lambda *a, **k: [])
    monkeypatch.setattr(ingest, "get_profile", lambda account: {"emailAddress": "a@b.com"})
    assert getattr(c, method)(path, params=params).status_code == 422
