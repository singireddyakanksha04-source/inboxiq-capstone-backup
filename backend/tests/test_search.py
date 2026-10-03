import pytest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

import app
from fakefs import FakeDB
from app.services import firestore_client as fs

NOW = datetime.now(timezone.utc)
UID = "u1"


def doc(id, days_ago=0, **kw):
    d = dict(id=id, thread_id="t", sender="A <a@a.com>", sender_email="a@a.com", sender_domain="a.com",
             subject="", snippet="", body_text="", labels=[], date=NOW - timedelta(days=days_ago),
             category=None, confidence=None, due_date=None, due_label=None)
    d.update(kw); return d


@pytest.fixture
def f(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    return f


@pytest.fixture
def c(f):
    from app.main import app as fastapi_app
    return TestClient(fastapi_app)


def ids(res):
    return [d["id"] for d in res]


def test_imports_this_checkout():
    backend = Path(__file__).resolve().parents[1]
    assert Path(app.__file__).resolve().is_relative_to(backend)
    assert Path(fs.__file__).resolve().is_relative_to(backend)


# ---------------------------------------------------------------- matching

def test_single_term_subject(f):
    f.put_email(UID, doc("a", subject="Your Netflix receipt"))
    f.put_email(UID, doc("b", subject="Weekly digest"))
    assert ids(fs.search_emails(UID, "netflix")) == ["a"]


def test_matches_each_field(f):
    f.put_email(UID, doc("subj", subject="zebra"))
    f.put_email(UID, doc("name", sender="Zebra Co <x@x.com>", sender_email="x@x.com", sender_domain="x.com"))
    f.put_email(UID, doc("addr", sender="X <zebra@y.com>", sender_email="zebra@y.com", sender_domain="y.com"))
    f.put_email(UID, doc("dom", sender_email="hi@zebra.io", sender_domain="zebra.io"))
    f.put_email(UID, doc("snip", snippet="a zebra ran"))
    f.put_email(UID, doc("body", body_text="deep in the body zebra"))
    f.put_email(UID, doc("none", subject="lion"))
    assert set(ids(fs.search_emails(UID, "zebra"))) == {"subj", "name", "addr", "dom", "snip", "body"}


def test_multiple_terms_are_anded(f):
    f.put_email(UID, doc("both", subject="nimbus pro renewal"))
    f.put_email(UID, doc("split", subject="nimbus", body_text="your renewal"))
    f.put_email(UID, doc("one", subject="nimbus only"))
    assert set(ids(fs.search_emails(UID, "nimbus renewal"))) == {"both", "split"}


def test_quoted_phrase(f):
    f.put_email(UID, doc("phrase", subject="Your nimbus pro plan"))
    f.put_email(UID, doc("apart", subject="pro tips from nimbus"))
    assert ids(fs.search_emails(UID, '"nimbus pro"')) == ["phrase"]
    # unquoted, both match
    assert set(ids(fs.search_emails(UID, "nimbus pro"))) == {"phrase", "apart"}


def test_unclosed_quote_is_phrase(f):
    f.put_email(UID, doc("phrase", subject="Your nimbus pro plan"))
    f.put_email(UID, doc("apart", subject="pro tips from nimbus"))
    assert ids(fs.search_emails(UID, '"nimbus pro')) == ["phrase"]


def test_case_insensitive(f):
    f.put_email(UID, doc("a", subject="Amazon ORDER shipped"))
    assert ids(fs.search_emails(UID, "aMaZoN order")) == ["a"]
    assert ids(fs.search_emails(UID, "AMAZON")) == ["a"]


def test_from_operator(f):
    f.put_email(UID, doc("name", sender="Stripe Billing <billing@pay.io>", sender_email="billing@pay.io",
                         sender_domain="pay.io"))
    f.put_email(UID, doc("mention", subject="stripe is down", sender="News <n@news.com>",
                         sender_email="n@news.com", sender_domain="news.com"))
    assert ids(fs.search_emails(UID, "from:stripe")) == ["name"]
    assert ids(fs.search_emails(UID, "from:billing@pay.io")) == ["name"]
    assert ids(fs.search_emails(UID, "from:pay.io")) == ["name"]
    assert ids(fs.search_emails(UID, "FROM:news.com")) == ["mention"]


def test_from_operator_quoted(f):
    f.put_email(UID, doc("a", sender="Best Buy <x@bb.com>", sender_email="x@bb.com", sender_domain="bb.com"))
    f.put_email(UID, doc("b", sender="Buy Best <y@bb.com>", sender_email="y@bb.com", sender_domain="bb.com"))
    assert ids(fs.search_emails(UID, 'from:"best buy"')) == ["a"]


def test_subject_operator(f):
    f.put_email(UID, doc("subj", subject="Invoice ready"))
    f.put_email(UID, doc("body", subject="Hello", body_text="your invoice"))
    assert ids(fs.search_emails(UID, "subject:invoice")) == ["subj"]


def test_operator_combined_with_terms(f):
    f.put_email(UID, doc("a", subject="Receipt", body_text="total $20.00",
                         sender="Uber <u@uber.com>", sender_email="u@uber.com", sender_domain="uber.com"))
    f.put_email(UID, doc("b", subject="Receipt", body_text="total $5",
                         sender="Uber <u@uber.com>", sender_email="u@uber.com", sender_domain="uber.com"))
    f.put_email(UID, doc("c", subject="Receipt", body_text="total $20.00"))
    assert ids(fs.search_emails(UID, "from:uber $20.00")) == ["a"]


def test_accents_and_unicode(f):
    f.put_email(UID, doc("cafe", subject="Café Olé order"))
    f.put_email(UID, doc("jp", subject="注文確認"))
    assert ids(fs.search_emails(UID, "café")) == ["cafe"]
    assert ids(fs.search_emails(UID, "CAFE")) == ["cafe"]
    assert ids(fs.search_emails(UID, "注文")) == ["jp"]


@pytest.mark.parametrize("q", ["c++", "$20.00", "(test)", "[a-z]*", "a|b", "\\", "?", ".*"])
def test_regex_characters_are_literal(f, q):
    f.put_email(UID, doc("hit", subject=f"about {q} here"))
    f.put_email(UID, doc("miss", subject="nothing relevant"))
    assert ids(fs.search_emails(UID, q)) == ["hit"]


def test_missing_fields_do_not_crash(f):
    f.put_email(UID, {"id": "bare", "date": NOW, "subject": None, "category": None})
    f.put_email(UID, doc("a", subject="hello"))
    assert ids(fs.search_emails(UID, "hello")) == ["a"]


# ---------------------------------------------------------------- scope

def test_category_scoping(f):
    f.put_email(UID, doc("bill", subject="netflix", category="bill"))
    f.put_email(UID, doc("sub", subject="netflix", category="subscription"))
    f.put_email(UID, doc("none", subject="netflix"))
    assert ids(fs.search_emails(UID, "netflix", category="subscription")) == ["sub"]
    assert ids(fs.search_emails(UID, "netflix", category="uncategorized")) == ["none"]


def test_all_mail_includes_uncategorized(f):
    f.put_email(UID, doc("bill", days_ago=1, subject="netflix", category="bill"))
    f.put_email(UID, doc("none", days_ago=2, subject="netflix"))
    legacy = doc("legacy", days_ago=3, subject="netflix"); legacy.pop("category")
    f.put_email(UID, legacy)
    assert ids(fs.search_emails(UID, "netflix")) == ["bill", "none", "legacy"]


def test_other_uid_not_searched(f):
    f.put_email("someone-else", doc("x", subject="netflix"))
    assert fs.search_emails(UID, "netflix") == []


def test_window_is_newest_500(f):
    for i in range(505):
        f.put_email(UID, doc(f"m{i}", days_ago=i, subject="match"))
    res = fs.search_emails(UID, "match", limit=1000)
    assert len(res) == 500 and res[-1]["id"] == "m499"
    q = [r for r in f.reads if r[0] == "query"]
    assert q  # went through a query, not a full dump


# ---------------------------------------------------------------- ranking/limit

def test_subject_hit_ranks_above_body_only(f):
    f.put_email(UID, doc("body_new", days_ago=0, body_text="about stripe"))
    f.put_email(UID, doc("subj_old", days_ago=5, subject="stripe receipt"))
    f.put_email(UID, doc("sender_mid", days_ago=3, sender="Stripe <s@stripe.com>",
                         sender_email="s@stripe.com", sender_domain="stripe.com"))
    assert ids(fs.search_emails(UID, "stripe")) == ["sender_mid", "subj_old", "body_new"]


def test_ties_newest_first(f):
    f.put_email(UID, doc("old", days_ago=9, subject="alpha"))
    f.put_email(UID, doc("new", days_ago=1, subject="alpha"))
    f.put_email(UID, doc("mid", days_ago=4, subject="alpha"))
    assert ids(fs.search_emails(UID, "alpha")) == ["new", "mid", "old"]


def test_more_header_terms_rank_higher(f):
    f.put_email(UID, doc("one", days_ago=0, subject="netflix", body_text="renewal"))
    f.put_email(UID, doc("two", days_ago=3, subject="netflix renewal"))
    assert ids(fs.search_emails(UID, "netflix renewal")) == ["two", "one"]


def test_limit_respected(f):
    for i in range(10):
        f.put_email(UID, doc(f"m{i}", days_ago=i, subject="same"))
    assert ids(fs.search_emails(UID, "same", limit=3)) == ["m0", "m1", "m2"]


def test_no_match_empty(f):
    f.put_email(UID, doc("a", subject="hello"))
    assert fs.search_emails(UID, "goodbye") == []


def test_blank_query_empty(f):
    f.put_email(UID, doc("a", subject="hello"))
    assert fs.search_emails(UID, "   ") == []
    assert fs.search_emails(UID, '""') == []


def test_result_shape_matches_list(f):
    f.put_email(UID, doc("a", subject="hello", body_text="body"))
    assert fs.search_emails(UID, "hello") == fs.list_emails(UID)


def test_no_writes(f):
    f.put_email(UID, doc("a", subject="hello"))
    fs.search_emails(UID, "hello")
    assert f.writes == [] and f.batches == []


# ---------------------------------------------------------------- route

def test_route_basic(c, f):
    f.put_email(UID, doc("a", subject="Nimbus Pro receipt", category="receipt"))
    f.put_email(UID, doc("b", subject="other"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "nimbus"})
    assert r.status_code == 200 and ids(r.json()) == ["a"]


def test_route_not_swallowed_by_message_id(c, f):
    # a doc literally called "search" must not be what comes back
    f.put_email(UID, doc("search", subject="zzz"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "nomatch"})
    assert r.status_code == 200 and r.json() == []
    # and the detail route still works
    assert c.get("/api/emails/search", params={"uid": UID}).status_code == 422
    assert c.get("/api/emails/search-not", params={"uid": UID}).status_code == 404


def test_route_category(c, f):
    f.put_email(UID, doc("a", subject="netflix", category="bill"))
    f.put_email(UID, doc("b", subject="netflix", category="subscription"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "netflix", "category": "bill"})
    assert ids(r.json()) == ["a"]


def test_route_strips_query(c, f):
    f.put_email(UID, doc("a", subject="netflix"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "  netflix  "})
    assert ids(r.json()) == ["a"]


@pytest.mark.parametrize("q", ["", "   ", "\t\n"])
def test_route_blank_query_422(c, q):
    assert c.get("/api/emails/search", params={"uid": UID, "q": q}).status_code == 422


def test_route_missing_query_422(c):
    assert c.get("/api/emails/search", params={"uid": UID}).status_code == 422


def test_route_missing_uid_422(c):
    assert c.get("/api/emails/search", params={"q": "x"}).status_code == 422


@pytest.mark.parametrize("limit,code", [(0, 422), (-1, 422), (201, 422), (1, 200), (200, 200)])
def test_route_limit_validation(c, limit, code):
    assert c.get("/api/emails/search", params={"uid": UID, "q": "x", "limit": limit}).status_code == code


def test_route_limit_applied(c, f):
    for i in range(5):
        f.put_email(UID, doc(f"m{i}", days_ago=i, subject="same"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "same", "limit": 2})
    assert ids(r.json()) == ["m0", "m1"]


def test_route_long_query(c, f):
    f.put_email(UID, doc("a", subject="netflix"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "netflix " * 60})
    assert r.status_code == 200 and ids(r.json()) == ["a"]
    assert c.get("/api/emails/search", params={"uid": UID, "q": "x" * 501}).status_code == 422


def test_route_uid_without_mail(c):
    r = c.get("/api/emails/search", params={"uid": "nobody", "q": "anything"})
    assert r.status_code == 200 and r.json() == []


def test_route_special_chars(c, f):
    f.put_email(UID, doc("a", subject="learn c++ today"))
    r = c.get("/api/emails/search", params={"uid": UID, "q": "c++"})
    assert r.status_code == 200 and ids(r.json()) == ["a"]


def test_existing_routes_unaffected(c, f):
    f.put_email(UID, doc("a", subject="hi"))
    assert ids(c.get("/api/emails", params={"uid": UID}).json()) == ["a"]
    assert c.get("/api/emails/a", params={"uid": UID}).json()["id"] == "a"
    assert c.get("/api/emails/stats", params={"uid": UID}).status_code == 200
