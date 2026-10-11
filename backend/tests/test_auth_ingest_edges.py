"""Edge cases for sign-in / account switching (F1, F5), Gmail parsing (F1),
the ingest routes, and uid validation on every mailbox route (F3)."""
import base64
import importlib
import json
from datetime import datetime, timezone

import httplib2
import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from fakefs import FakeDB
from app.core.config import get_settings
from app.services import firestore_client as fs
from app.services import gmail_auth as ga
from app.services import gmail_client as gc

auth_router = importlib.import_module("app.features.auth.router")
ingest = importlib.import_module("app.features.ingest.router")


def http_error(status, reason="backendError", msg="boom"):
    resp = httplib2.Response({"status": status})
    body = json.dumps({"error": {"code": status, "message": msg,
                                 "errors": [{"reason": reason, "message": msg}]}}).encode()
    return HttpError(resp, body)


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def fdb(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    return f


@pytest.fixture
def tokens(monkeypatch, tmp_path):
    """Token store in a temp dir; never touches secrets/tokens."""
    monkeypatch.setattr(get_settings(), "token_store", tmp_path)
    return tmp_path


@pytest.fixture
def no_cli_flow(monkeypatch):
    """A web request must never start the CLI's local-server consent flow."""
    def boom(*a, **k):
        raise AssertionError("CLI consent flow started from a web request")
    monkeypatch.setattr(ga.InstalledAppFlow, "from_client_secrets_file", boom)


# ------------------------------------------------ uid

@pytest.mark.parametrize("a,b", [
    ("Name@Gmail.com", "name@gmail.com"),
    (" name@gmail.com ", "name@gmail.com"),
])
def test_make_uid_normalises(a, b):
    assert fs.make_uid(a) == fs.make_uid(b)


def test_make_uid_distinct_accounts():
    assert fs.make_uid("a.b@gmail.com") != fs.make_uid("a.c@gmail.com")


# ------------------------------------------------ /api/auth/status

def test_status_signed_out_does_not_call_gmail(client, monkeypatch):
    monkeypatch.setattr(ga, "is_authorized", lambda account="default": False)
    monkeypatch.setattr(auth_router, "get_profile", lambda account: pytest.fail("called Gmail"))
    j = client.get("/api/auth/status").json()
    assert j == {"account": "default", "authorized": False, "email": None, "uid": None}


def test_status_switch_account_changes_uid(client, monkeypatch):
    monkeypatch.setattr(ga, "is_authorized", lambda account="default": True)
    who = {"email": "first@gmail.com"}
    monkeypatch.setattr(auth_router, "get_profile", lambda account: {"emailAddress": who["email"]})
    first = client.get("/api/auth/status").json()
    who["email"] = "second@gmail.com"
    second = client.get("/api/auth/status").json()
    assert first["uid"] == "first_gmail_com" and second["uid"] == "second_gmail_com"
    assert second["email"] == "second@gmail.com"


def test_status_revoked_token_is_signed_out(client, monkeypatch):
    def revoked(account="default"):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")
    monkeypatch.setattr(ga, "is_authorized", revoked)
    r = client.get("/api/auth/status")
    assert r.status_code == 200 and r.json()["authorized"] is False


def test_status_gmail_401_is_signed_out(client, monkeypatch):
    monkeypatch.setattr(ga, "is_authorized", lambda account="default": True)
    def denied(account):
        raise http_error(401, "authError", "Invalid Credentials")
    monkeypatch.setattr(auth_router, "get_profile", denied)
    r = client.get("/api/auth/status")
    assert r.status_code == 200 and r.json()["authorized"] is False


def test_data_scoped_per_account(client, fdb):
    fs.save_emails("first_gmail_com", [_msg("a1")])
    fs.save_emails("second_gmail_com", [_msg("b1")])
    ids = lambda uid: [d["id"] for d in client.get("/api/emails", params={"uid": uid}).json()]
    assert ids("first_gmail_com") == ["a1"] and ids("second_gmail_com") == ["b1"]


# ------------------------------------------------ /api/auth/login

class FakeFlow:
    last = None
    def __init__(self): self.kw = None; self.redirect_uri = None
    @classmethod
    def from_client_secrets_file(cls, path, scopes, state=None):
        cls.last = cls(); cls.last.scopes = scopes; return cls.last
    def authorization_url(self, **kw):
        self.kw = kw
        return "https://accounts.google.com/o/oauth2/auth?x=1", "state-123"


def test_login_redirects_to_google_with_chooser(client, monkeypatch, tokens):
    monkeypatch.setattr(ga, "_require_client_secrets", lambda: tokens / "client.json")
    monkeypatch.setattr(ga, "Flow", FakeFlow)
    r = client.get("/api/auth/login")
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://accounts.google.com/")
    assert "select_account" in FakeFlow.last.kw["prompt"]
    assert FakeFlow.last.kw["access_type"] == "offline"
    assert ga._pending.pop("state-123") == "default"


def test_login_requests_only_readonly_scope(client, monkeypatch, tokens):
    monkeypatch.setattr(ga, "_require_client_secrets", lambda: tokens / "client.json")
    monkeypatch.setattr(ga, "Flow", FakeFlow)
    client.get("/api/auth/login")
    ga._pending.pop("state-123", None)
    assert FakeFlow.last.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]


def test_login_missing_client_file_is_clear_error(client, monkeypatch):
    def missing():
        raise FileNotFoundError("OAuth client file missing: x\nFollow SETUP.md.")
    monkeypatch.setattr(ga, "_require_client_secrets", missing)
    r = client.get("/api/auth/login")
    assert r.status_code == 500 and "SETUP.md" in r.json()["detail"]


# ------------------------------------------------ /api/auth/callback

@pytest.mark.parametrize("params", [
    {"error": "access_denied"},
    {"state": "s"},
    {"code": "c"},
    {},
])
def test_callback_bad_requests(client, params):
    assert client.get("/api/auth/callback", params=params).status_code == 400


def test_callback_unknown_state(client):
    r = client.get("/api/auth/callback", params={"code": "c", "state": "never-issued"})
    assert r.status_code == 400 and "state" in r.json()["detail"]


def test_callback_success_redirects_to_dashboard(client, monkeypatch):
    monkeypatch.setattr(ga, "exchange_code", lambda code, state: "default")
    r = client.get("/api/auth/callback", params={"code": "c", "state": "s"})
    assert r.status_code in (302, 307)
    assert r.headers["location"] == f"{get_settings().frontend_url}/?signed_in=1"


def test_callback_reused_code_is_400_not_500(client, monkeypatch):
    def reused(code, state):
        raise InvalidGrantError("Bad Request")
    monkeypatch.setattr(ga, "exchange_code", reused)
    r = client.get("/api/auth/callback", params={"code": "c", "state": "s"})
    assert r.status_code == 400 and "sign in again" in r.json()["detail"].lower()


def test_exchange_code_state_is_single_use(monkeypatch, tokens):
    monkeypatch.setattr(ga, "_require_client_secrets", lambda: tokens / "client.json")

    class F(FakeFlow):
        credentials = type("C", (), {"to_json": lambda self: "{}"})()
        def fetch_token(self, code): pass
    monkeypatch.setattr(ga, "Flow", F)
    ga._pending["st"] = "default"
    assert ga.exchange_code("c", "st") == "default"
    with pytest.raises(ValueError):
        ga.exchange_code("c", "st")


# ------------------------------------------------ tokens and logout

def test_logout_removes_token_then_status_signed_out(client, tokens):
    (tokens / "default.json").write_text("{}")
    assert client.post("/api/auth/logout").json() == {"removed": True}
    assert not (tokens / "default.json").exists()
    assert client.post("/api/auth/logout").json() == {"removed": False}
    assert client.get("/api/auth/status").json()["authorized"] is False


@pytest.mark.parametrize("account", ["../../etc/passwd", "..", "a/../../b", "x\\..\\y"])
def test_token_path_stays_in_store(tokens, account):
    p = ga._token_path(account).resolve()
    assert p.parent == tokens.resolve()


def test_corrupt_token_file_means_signed_out(tokens):
    (tokens / "default.json").write_text("{not json")
    assert ga.load_credentials("default") is None
    assert ga.is_authorized("default") is False


def test_token_without_refresh_token_means_signed_out(tokens):
    (tokens / "default.json").write_text(json.dumps({
        "token": "t", "client_id": "c", "client_secret": "s",
        "expiry": "2000-01-01T00:00:00Z"}))
    assert ga.load_credentials("default") is None


def test_revoked_refresh_token_means_signed_out(tokens, monkeypatch):
    (tokens / "default.json").write_text(json.dumps({
        "token": "t", "refresh_token": "r", "client_id": "c", "client_secret": "s",
        "expiry": "2000-01-01T00:00:00Z"}))
    def revoked(self, request):
        raise RefreshError("invalid_grant")
    monkeypatch.setattr(ga.Credentials, "refresh", revoked)
    assert ga.load_credentials("default") is None


def test_saved_token_is_private(tokens):
    creds = type("C", (), {"to_json": lambda self: "{}"})()
    ga._save("default", creds)
    assert (tokens / "default.json").stat().st_mode & 0o077 == 0


# ------------------------------------------------ ingest routes, signed out

def test_gmail_service_signed_out_raises_not_signed_in(tokens, no_cli_flow):
    with pytest.raises(ga.NotSignedIn):
        ga.gmail_service("default")


def test_me_signed_out_is_401(client, tokens, no_cli_flow):
    r = client.get("/api/ingest/me")
    assert r.status_code == 401 and "sign in" in r.json()["detail"].lower()


def test_sync_signed_out_is_401(client, tokens, no_cli_flow, fdb):
    r = client.post("/api/ingest/sync", params={"count": 5})
    assert r.status_code == 401
    assert fdb.writes == []


def test_me_returns_address_and_total(client, monkeypatch):
    monkeypatch.setattr(ingest, "get_profile",
                        lambda account: {"emailAddress": "a@b.com", "messagesTotal": 42})
    assert client.get("/api/ingest/me").json() == {"email": "a@b.com", "total": 42}


# ------------------------------------------------ sync edges

def _msg(mid, date=None):
    from app.models.email import EmailMessage
    return EmailMessage(id=mid, thread_id="t", subject=mid, sender="A <a@a.com>", sender_email="a@a.com",
                        sender_domain="a.com", date=date or datetime(2026, 9, 20, tzinfo=timezone.utc))


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(ingest, "get_profile", lambda account: {"emailAddress": "a@b.com"})


@pytest.mark.parametrize("params", [{"count": 0}, {"count": 201}, {"count": -1},
                                    {"billing": 101}, {"billing": -1}, {"count": "abc"}])
def test_sync_param_bounds(client, signed_in, params):
    assert client.post("/api/ingest/sync", params=params).status_code == 422


def test_sync_empty_mailbox(client, signed_in, fdb, monkeypatch):
    monkeypatch.setattr(ingest, "fetch_messages", lambda *a, **k: [])
    r = client.post("/api/ingest/sync", params={"count": 5})
    assert r.status_code == 200 and r.json()["stored"] == 0


def test_sync_duplicate_ids_stored_once(client, signed_in, fdb, monkeypatch):
    monkeypatch.setattr(ingest, "fetch_messages", lambda *a, **k: [_msg("x"), _msg("x")])
    assert client.post("/api/ingest/sync", params={"count": 5}).json()["stored"] == 1


def test_sync_gmail_server_error_is_502(client, signed_in, fdb, monkeypatch):
    def down(*a, **k):
        raise http_error(500)
    monkeypatch.setattr(ingest, "fetch_messages", down)
    r = client.post("/api/ingest/sync", params={"count": 5})
    assert r.status_code == 502 and "gmail" in r.json()["detail"].lower()


def test_sync_gmail_401_asks_to_sign_in_again(client, signed_in, fdb, monkeypatch):
    def expired(*a, **k):
        raise http_error(401, "authError", "Invalid Credentials")
    monkeypatch.setattr(ingest, "fetch_messages", expired)
    r = client.post("/api/ingest/sync", params={"count": 5})
    assert r.status_code == 401 and "sign in" in r.json()["detail"].lower()


def test_sync_revoked_during_profile_is_401(client, fdb, monkeypatch):
    def revoked(account):
        raise RefreshError("invalid_grant")
    monkeypatch.setattr(ingest, "get_profile", revoked)
    assert client.post("/api/ingest/sync", params={"count": 5}).status_code == 401


# ------------------------------------------------ uid validation on mailbox routes

BAD_UIDS = ["", "a/b", "../x", "users/other/emails", "A B", "x" * 300]
UID_ROUTES = [
    ("get", "/api/emails", {}),
    ("get", "/api/emails/search", {"q": "x"}),
    ("get", "/api/emails/stats", {}),
    ("get", "/api/emails/subscriptions", {}),
    ("get", "/api/emails/unsubscribe-suggestions", {}),
    ("get", "/api/emails/abc", {}),
    ("post", "/api/classify", {}),
    ("post", "/api/classify/subscriptions", {}),
]


@pytest.mark.parametrize("uid", BAD_UIDS)
@pytest.mark.parametrize("method,path,extra", UID_ROUTES)
def test_bad_uid_rejected_before_firestore(client, fdb, method, path, extra, uid):
    r = getattr(client, method)(path, params={"uid": uid, **extra})
    assert r.status_code == 422
    assert fdb.reads == [] and fdb.writes == []


@pytest.mark.parametrize("method,path,extra", UID_ROUTES[:5])
def test_good_uid_new_user_is_empty_not_error(client, fdb, method, path, extra):
    assert getattr(client, method)(path, params={"uid": "new_user_gmail_com", **extra}).status_code == 200


def test_unknown_category_is_empty(client, fdb):
    fs.save_emails("u_gmail_com", [_msg("a")])
    r = client.get("/api/emails", params={"uid": "u_gmail_com", "category": "bogus"})
    assert r.status_code == 200 and r.json() == []


# ------------------------------------------------ Gmail message parsing

def b64(s, pad=True):
    out = base64.urlsafe_b64encode(s.encode()).decode()
    return out if pad else out.rstrip("=")


def raw(payload=None, **kw):
    d = {"id": "m", "threadId": "t", "labelIds": ["INBOX"], "snippet": ""}
    if payload is not None:
        d["payload"] = payload
    d.update(kw)
    return d


def hdrs(**h):
    return [{"name": k.replace("_", "-"), "value": v} for k, v in h.items()]


@pytest.mark.parametrize("date", [
    "Mon, 21 Sep 2026 10:00:00 -0000",   # RFC 2822 "unknown zone"
    "Mon, 21 Sep 2026 10:00:00",         # no zone at all
    "21 Sep 2026 10:00:00 GMT",
])
def test_date_always_timezone_aware(date):
    m = gc.parse_message(raw({"headers": hdrs(Date=date), "mimeType": "text/plain"}))
    assert m.date is not None and m.date.tzinfo is not None
    assert m.date.astimezone(timezone.utc).hour == 10


@pytest.mark.parametrize("date", ["", "not a date", "Mon, 99 Foo 2026 99:99:99 +0000"])
def test_bad_date_is_none(date):
    assert gc.parse_message(raw({"headers": hdrs(Date=date)})).date is None


def test_body_without_base64_padding():
    text = "Receipt total $9.99"  # length gives '=' padding when encoded
    assert b64(text) != b64(text, pad=False)
    p = {"mimeType": "text/plain", "body": {"data": b64(text, pad=False)}, "headers": []}
    assert gc.parse_message(raw(p)).body_text == text


def test_nested_multipart_prefers_plain():
    p = {"mimeType": "multipart/mixed", "headers": [], "parts": [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/html", "body": {"data": b64("<b>html version</b>")}},
            {"mimeType": "text/plain", "body": {"data": b64("plain version")}},
        ]},
        {"mimeType": "application/pdf", "filename": "a.pdf", "body": {"attachmentId": "x"}},
    ]}
    assert gc.parse_message(raw(p)).body_text == "plain version"


def test_html_script_style_any_case_and_entities():
    html = "<STYLE>.x{}</STYLE><Script>evil()</Script><p>Tom &amp; Jerry&nbsp;&#8217;s</p><br>next"
    p = {"mimeType": "text/html", "body": {"data": b64(html)}, "headers": []}
    body = gc.parse_message(raw(p)).body_text
    assert "evil" not in body and ".x{}" not in body
    assert "Tom & Jerry" in body and "’s" in body and "next" in body


def test_body_capped():
    p = {"mimeType": "text/plain", "body": {"data": b64("a" * 30000)}, "headers": []}
    assert len(gc.parse_message(raw(p)).body_text) == 20000


def test_no_payload_no_labels():
    d = {"id": "m"}
    m = gc.parse_message(d)
    assert (m.subject, m.sender_email, m.body_text, m.labels, m.date) == ("", "", "", [], None)


@pytest.mark.parametrize("frm,addr,domain", [
    ("Shop <News@Shop.COM>", "News@Shop.COM", "shop.com"),
    ("undisclosed-recipients", "", ""),
    ('"Doe, Jane" <jane@x.org>', "jane@x.org", "x.org"),
    ("", "", ""),
])
def test_sender_parsing(frm, addr, domain):
    m = gc.parse_message(raw({"headers": hdrs(From=frm)}))
    assert (m.sender_email, m.sender_domain) == (addr, domain)


def test_header_names_case_insensitive():
    m = gc.parse_message(raw({"headers": [{"name": "SUBJECT", "value": "Hi"},
                                          {"name": "from", "value": "a@b.com"}]}))
    assert m.subject == "Hi" and m.sender_email == "a@b.com"


def test_snippet_entities_decoded():
    assert gc.parse_message(raw({}, snippet="It&#39;s &amp; done")).snippet == "It's & done"


def test_undecodable_bytes_do_not_crash():
    data = base64.urlsafe_b64encode(b"caf\xe9 \xff ok").decode()
    p = {"mimeType": "text/plain", "body": {"data": data}, "headers": []}
    assert "ok" in gc.parse_message(raw(p)).body_text


# ------------------------------------------------ sync window (recent mail only)

@pytest.fixture
def queries(client, signed_in, fdb, monkeypatch):
    seen = []
    def fetch(count, q, account, skip=frozenset()):
        seen.append(q)
        return []
    monkeypatch.setattr(ingest, "fetch_messages", fetch)
    return seen


def test_sync_default_is_last_30_days(client, queries):
    client.post("/api/ingest/sync", params={"count": 5, "billing": 5})
    inbox, billing = queries
    assert "in:inbox" in inbox and "newer_than:30d" in inbox
    assert "newer_than:30d" in billing and "newer_than:1y" not in billing
    assert "subject:receipt" in billing


def test_sync_days_param(client, queries):
    client.post("/api/ingest/sync", params={"count": 5, "billing": 5, "days": 15})
    assert all("newer_than:15d" in q for q in queries) and len(queries) == 2


@pytest.mark.parametrize("days", [0, -1, 366, "x"])
def test_sync_days_bounds(client, queries, days):
    assert client.post("/api/ingest/sync", params={"days": days}).status_code == 422
    assert queries == []


def test_sync_query_with_own_window_not_doubled(client, queries):
    client.post("/api/ingest/sync", params={"count": 5, "q": "in:inbox newer_than:7d"})
    assert queries == ["in:inbox newer_than:7d"]
