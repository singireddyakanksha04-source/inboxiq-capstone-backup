"""Gmail rate limits: retry with back-off, skip already-fetched ids, and a
sync that still stores the inbox pull when the billing pull fails."""
import base64
import importlib
import json
from datetime import datetime, timezone

import httplib2
import pytest
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError

from fakefs import FakeDB
from app.models.email import EmailMessage
from app.services import firestore_client as fs
from app.services import gmail_client as gc


def http_error(status, reason="rateLimitExceeded", msg="Quota exceeded for quota metric 'Total Query Cost'"):
    resp = httplib2.Response({"status": status})
    body = json.dumps({"error": {"code": status, "message": msg,
                                 "errors": [{"reason": reason, "message": msg}]}}).encode()
    return HttpError(resp, body)


def raw(mid):
    data = base64.urlsafe_b64encode(b"hello").decode()
    return {"id": mid, "threadId": "t", "labelIds": ["INBOX"], "snippet": "s",
            "payload": {"mimeType": "text/plain", "body": {"data": data},
                        "headers": [{"name": "From", "value": "A <a@a.com>"},
                                    {"name": "Subject", "value": f"msg {mid}"},
                                    {"name": "Date", "value": "Mon, 21 Sep 2026 10:00:00 +0000"}]}}


class Call:
    def __init__(self, fn): self.fn = fn
    def execute(self): return self.fn()


class FakeGmail:
    """users().messages().list/get with scripted failures per message id."""
    def __init__(self, ids, fail=None):
        self.ids = ids; self.fail = dict(fail or {}); self.gets = []; self.lists = 0
    def users(self): return self
    def messages(self): return self
    def list(self, userId, q, maxResults):
        self.lists += 1
        return Call(lambda: {"messages": [{"id": i} for i in self.ids[:maxResults]]})
    def get(self, userId, id, format):
        def run():
            self.gets.append(id)
            left = self.fail.get(id)
            if left:
                status, n = left
                self.fail[id] = (status, n - 1) if n > 1 else None
                raise http_error(status)
            return raw(id)
        return Call(run)


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(gc.time, "sleep", lambda s: slept.append(s))
    return slept


def test_rate_limited_get_is_retried(monkeypatch, no_sleep):
    svc = FakeGmail(["a", "b"], fail={"b": (403, 2)})
    monkeypatch.setattr(gc, "gmail_service", lambda account: svc)
    out = gc.fetch_messages(2, "in:inbox")
    assert [m.id for m in out] == ["a", "b"]
    assert svc.gets.count("b") == 3 and len(no_sleep) == 2
    assert no_sleep[1] > no_sleep[0]  # backs off


def test_429_is_retried(monkeypatch, no_sleep):
    svc = FakeGmail(["a"], fail={"a": (429, 1)})
    monkeypatch.setattr(gc, "gmail_service", lambda account: svc)
    assert [m.id for m in gc.fetch_messages(1, "q")] == ["a"]


def test_gives_up_after_retries(monkeypatch, no_sleep):
    svc = FakeGmail(["a"], fail={"a": (403, 99)})
    monkeypatch.setattr(gc, "gmail_service", lambda account: svc)
    with pytest.raises(HttpError):
        gc.fetch_messages(1, "q")
    assert 2 <= len(no_sleep) <= 6


def test_other_403_not_retried(monkeypatch, no_sleep):
    svc = FakeGmail(["a"])
    def boom(): raise http_error(403, reason="insufficientPermissions", msg="Insufficient Permission")
    svc.get = lambda userId, id, format: Call(boom)
    monkeypatch.setattr(gc, "gmail_service", lambda account: svc)
    with pytest.raises(HttpError):
        gc.fetch_messages(1, "q")
    assert no_sleep == []


def test_skip_ids_are_not_downloaded(monkeypatch, no_sleep):
    svc = FakeGmail(["a", "b", "c"])
    monkeypatch.setattr(gc, "gmail_service", lambda account: svc)
    out = gc.fetch_messages(3, "q", skip={"b"})
    assert [m.id for m in out] == ["a", "c"] and "b" not in svc.gets


# ------------------------------------------------ sync route

@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    ingest = importlib.import_module("app.features.ingest.router")
    monkeypatch.setattr(ingest, "get_profile", lambda account: {"emailAddress": "a@b.com"})
    from app.main import app
    return TestClient(app), f, ingest


def msg(mid):
    return EmailMessage(id=mid, thread_id="t", subject=mid, sender="A <a@a.com>", sender_email="a@a.com",
                        sender_domain="a.com", date=datetime(2026, 9, 20, tzinfo=timezone.utc))


def test_sync_keeps_inbox_when_billing_pull_fails(env, monkeypatch):
    c, f, ingest = env
    def fetch(count, q, account, skip=frozenset()):
        if "subject:receipt" in q:
            raise http_error(403)
        return [msg("i1"), msg("i2")]
    monkeypatch.setattr(ingest, "fetch_messages", fetch)
    r = c.post("/api/ingest/sync", params={"count": 2, "billing": 10})
    assert r.status_code == 200
    j = r.json()
    assert j["stored"] == 2 and j.get("billing_error")
    assert ("users", j["uid"], "emails", "i1") in f.docs


def test_sync_billing_skips_ids_from_inbox_pull(env, monkeypatch):
    c, f, ingest = env
    seen = {}
    def fetch(count, q, account, skip=frozenset()):
        seen[q] = set(skip)
        return [msg("b1")] if "subject:receipt" in q else [msg("i1")]
    monkeypatch.setattr(ingest, "fetch_messages", fetch)
    r = c.post("/api/ingest/sync", params={"count": 2, "billing": 10})
    assert [s for q, s in seen.items() if "subject:receipt" in q] == [{"i1"}] and r.json()["stored"] == 2


def test_sync_inbox_pull_failure_is_a_clear_error(env, monkeypatch):
    c, f, ingest = env
    def fetch(count, q, account, skip=frozenset()):
        raise http_error(429)
    monkeypatch.setattr(ingest, "fetch_messages", fetch)
    r = c.post("/api/ingest/sync", params={"count": 2})
    assert r.status_code == 429
    assert "try again" in r.json()["detail"].lower()
