"""Needs reply over stored mail. The model is faked, so these run offline."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fakefs import FakeDB

from app.services import firestore_client as fs
from app.services import needs_ai
from app.services import personal_ai

UID = "u1"
ME = "sam@example.com"
NOW = datetime.now(timezone.utc)

# The model's verdict, by the subject it is shown.
VERDICTS = {"Thursday?": (True, "Priya asks if Thursday at 3 works"),
            "Slides": (True, "Dev asks for the slides by Friday"),
            "Lunch": (True, "Ana asks about lunch on Monday")}


class FakeAI:
    def __init__(self, raw=None, error=None):
        self.raw, self.error = raw, error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, user = kw["messages"][0]["content"], kw["messages"][1]["content"]
        self.calls.append((system, user))
        if self.error:
            raise self.error
        results = [{"i": int(i), "needs_reply": VERDICTS.get(s, (False, ""))[0], "reason": VERDICTS.get(s, (False, ""))[1]}
                   for i, s in re.findall(r"\[(\d+)\] From: .*\n {4}Subject: (.*)\n", user + "\n")]
        results += [{"i": 99, "needs_reply": True}, {"i": 0, "needs_reply": "yes"}, "junk"]
        content = self.raw if self.raw is not None else json.dumps({"results": results})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def doc(id, minutes, sender, subject, category="other", thread_id=None, **kw):
    email = re.search(r"<([^>]+)>", sender)
    d = dict(id=id, thread_id=thread_id or "t" + id, sender=sender, sender_email=email.group(1) if email else sender,
             subject=subject, snippet=subject + " preview", labels=["INBOX"], category=category,
             date=NOW - timedelta(minutes=minutes))
    d.update(kw)
    return d


@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    ai = FakeAI()
    monkeypatch.setattr(personal_ai, "_client", lambda: ai)
    f.docs[("users", UID)] = {"email": "Sam@Example.com"}
    for d in [
        doc("m1", 1, "Priya Shah <priya@example.com>", "Thursday?", thread_id="t1"),
        doc("m2", 2, "Shop <orders@shop.example>", "Your receipt", "receipt"),
        doc("m3", 3, "GitHub <noreply@github.com>", "New sign-in"),
        doc("m4", 4, "Dev Patel <dev@example.com>", "Slides", thread_id="t4"),
        doc("m4b", 0, f"Sam <{ME}>", "Re: Slides", thread_id="t4"),          # answered
        doc("m5", 5, "Ana Lee <ana@example.com>", "Lunch", thread_id="t5"),
        doc("m5b", 0, f"Sam <{ME}>", "Re: Lunch", thread_id="t5", labels=["DRAFT"]),  # only a draft
        doc("m6", 6, "Priya Shah <priya@example.com>", "Older in thread", thread_id="t1"),
    ]:
        f.put_email(UID, d)
    from app.main import app
    return TestClient(app), f, ai


def test_needs_reply(env):
    c, f, ai = env
    writes = len(f.writes)
    r = c.get(f"/api/reply/needs?uid={UID}")
    assert r.status_code == 200
    body = r.json()
    assert body["error"] is None
    assert [(i["email_id"], i["reason"]) for i in body["items"]] == [
        ("m1", "Priya asks if Thursday at 3 works"), ("m5", "Ana asks about lunch on Monday")]
    assert body["items"][0]["thread_id"] == "t1" and body["items"][0]["subject"] == "Thursday?"
    assert len(f.writes) == writes  # nothing is stored


def test_rules_settle_automatic_mail_without_the_model(env):
    c, _, ai = env
    c.get(f"/api/reply/needs?uid={UID}")
    assert len(ai.calls) == 1
    system, prompt = ai.calls[0]
    assert "Prefer false over a weak guess" in system
    assert "Subject: Thursday?" in prompt and "Subject: Lunch" in prompt
    for left_out in ["Your receipt", "New sign-in", "Re: Slides", "Re: Lunch", "Older in thread"]:
        assert left_out not in prompt  # rules, own mail, an answered thread, one per thread
    assert "Subject: Slides" not in prompt


def test_rules():
    assert needs_ai.is_candidate({"category": "personal", "sender": "A <a@x.com>"}, ME)
    assert not needs_ai.is_candidate({"category": "bill", "sender": "A <a@x.com>"}, ME)
    assert not needs_ai.is_candidate({"category": "other", "sender": "Do Not Reply <donotreply@x.com>"}, ME)
    assert not needs_ai.is_candidate({"category": "other", "sender_email": "notifications@x.com"}, ME)
    assert not needs_ai.is_candidate({"category": "other", "sender": f"Me <{ME.upper()}>"}, ME)
    assert not needs_ai.is_candidate({"category": "other", "sender": ""}, ME)
    assert needs_ai.is_candidate({"category": "other", "sender": "Renotify <hello@renotify.com>"}, ME)
    assert needs_ai.thread_answered([{"sender": "a@x.com"}, {"sender": f"Sam <{ME}>"}], ME)
    assert not needs_ai.thread_answered([{"sender": f"Sam <{ME}>"}, {"sender": "a@x.com"}], ME)
    assert not needs_ai.thread_answered([{"sender": "a@x.com"}, {"sender": ME, "labels": ["DRAFT"]}], ME)
    assert not needs_ai.thread_answered([], ME)


def test_batches_of_ten():
    ai = FakeAI()
    emails = [doc(f"x{i}", i, f"P{i} <p{i}@x.com>", "Lunch") for i in range(23)]
    found = needs_ai.needs_reply(emails, ME, client=ai)
    assert len(ai.calls) == 3 and len(found) == 23


def test_failures(env, monkeypatch):
    c, _, _ = env
    busy = Exception("rate limited")
    busy.status_code = 429
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI(error=busy))
    assert c.get(f"/api/reply/needs?uid={UID}").json() == {"items": [], "error": "The AI is busy (rate limit). Try again in a minute."}
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI(raw="not json"))
    assert c.get(f"/api/reply/needs?uid={UID}").json() == {"items": [], "error": None}
    assert c.get("/api/reply/needs?uid=../x").status_code == 422


def test_same_prompt_as_the_extension():
    """The extension's needs.js carries the same instructions, line for line."""
    js = (Path(__file__).resolve().parents[2] / "extension" / "src" / "needs.js").read_text()
    start = js.index("var SYSTEM =")
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'', js[start:js.index(";", start)])
    js_text = "".join(a or b for a, b in parts)
    js_text = js_text.replace('\\"', '"').replace("\\n", "\n")
    assert js_text == needs_ai._SYSTEM
