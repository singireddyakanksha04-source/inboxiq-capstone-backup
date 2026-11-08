"""Reply drafts for one stored email. The model is faked, so these run offline."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fakefs import FakeDB

from app.services import firestore_client as fs
from app.services import personal_ai
from app.services import reply_ai

UID = "u1"
BODY = ("Great, could we do Thursday at 3? Café is fine too.\r\n\r\n"
        "On Mon, Oct 27, 2026 at 9:00 AM Sam Rivera\r\n<sam@example.com> wrote:\r\n"
        "> Yes, any afternoon works.\r\n")


class FakeAI:
    def __init__(self, answer=None, raw=None, error=None):
        self.answer = answer if answer is not None else {
            "reply": "Hi Priya,\r\n\r\n\r\nThursday at 3 works.   \n\nBest,\nSam", "needs_reply": True,
            "options": ["Suggest Friday instead.", "suggest friday instead", 42, '"Decline politely"', "Ask why", "Fourth"]}
        self.raw, self.error = raw, error
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append((kw["messages"][0]["content"], kw["messages"][1]["content"]))
        self.temperatures = getattr(self, "temperatures", []) + [kw["temperature"]]
        if self.error:
            raise self.error
        content = self.raw if self.raw is not None else json.dumps(self.answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def doc(id, **kw):
    d = dict(id=id, thread_id="t", sender="Priya Shah <priya@example.com>", sender_email="priya@example.com",
             sender_domain="example.com", subject="Re: Project sync", snippet="Great, could we do Thursday",
             body_text=BODY, labels=[], date=datetime.now(timezone.utc), category="other", confidence=0.3)
    d.update(kw)
    return d


@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    ai = FakeAI()
    monkeypatch.setattr(personal_ai, "_client", lambda: ai)
    f.put_email(UID, doc("m1"))
    f.put_email(UID, doc("m2", thread_id="t2", body_text="", snippet="Your order has shipped", sender="Shop <o@shop.example>",
                         sender_email="o@shop.example", subject="Order shipped"))
    from app.main import app
    return TestClient(app), f, ai


def draft(c, email_id="m1", **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return c.post(f"/api/reply/draft?uid={UID}&email_id={email_id}" + (f"&{query}" if query else ""))


def test_draft(env):
    c, f, ai = env
    writes = len(f.writes)
    r = draft(c, name="Sam%20Rivera")
    assert r.status_code == 200
    assert r.json() == {"error": None, "draft": {
        "email_id": "m1", "to": "priya@example.com", "subject": "Re: Project sync",
        "text": "Hi Priya,\n\nThursday at 3 works.\n\nBest,\nSam", "needs_reply": True,
        "options": ["Suggest Friday instead", "Decline politely", "Ask why"]}}
    system, prompt = ai.calls[0]
    assert "Never make up" in system
    assert "From: Priya Shah <priya@example.com>" in prompt and "Subject: Re: Project sync" in prompt
    assert "Café is fine too." in prompt and "The user's name: Sam Rivera" in prompt
    assert "wrote:" not in prompt and "any afternoon" not in prompt  # quoted mail stays out
    assert len(f.writes) == writes  # drafting stores nothing


def test_users_note_steers_the_draft(env):
    c, _, ai = env
    draft(c, note="%20yes,%0A%20but%20%20Friday%20is%20better%20")
    assert "What the user wants to say: yes, but Friday is better" in ai.calls[0][1]
    draft(c)
    assert "What the user wants to say" not in ai.calls[1][1]
    assert draft(c, note="n" * 301).status_code == 422
    assert "n" * 300 in reply_ai.prompt({"sender": "a"}, note="n" * 400)
    assert "n" * 301 not in reply_ai.prompt({"sender": "a"}, note="n" * 400)


def test_redraft_shows_the_earlier_draft_and_may_vary(env):
    c, _, ai = env
    draft(c)
    draft(c, previous="Hi%20Priya,%0A%0AThursday%20works.")
    assert ai.temperatures == [0, reply_ai.REDRAFT_TEMPERATURE]
    assert "Earlier draft" not in ai.calls[0][1]
    assert ai.calls[1][1].endswith("Earlier draft (write a different one):\nHi Priya,\n\nThursday works.")
    assert draft(c, previous="x" * 2001).status_code == 422


def test_tone_and_length(env):
    c, _, ai = env
    draft(c)
    assert "Tone: friendly\nLength: short" in ai.calls[0][1]
    draft(c, tone="formal", length="detailed")
    assert "Tone: formal\nLength: detailed" in ai.calls[1][1]
    assert draft(c, tone="angry").status_code == 422
    assert draft(c, length="long").status_code == 422
    assert reply_ai.clean_style({"tone": "formal", "length": 7}) == {"tone": "formal", "length": "short"}
    assert reply_ai.clean_style(None) == {"tone": "friendly", "length": "short"}


def test_earlier_thread_goes_first(env):
    c, f, ai = env
    f.docs[("users", UID)] = {"email": "Sam@Example.com"}
    now = datetime.now(timezone.utc)
    f.put_email(UID, doc("m0", body_text="Are you free this week?", date=now - timedelta(days=2)))
    f.put_email(UID, doc("m0b", sender="Sam Rivera <sam@example.com>", sender_email="sam@example.com",
                         body_text="Yes, any afternoon.\n> Are you free this week?", date=now - timedelta(days=1)))
    f.put_email(UID, doc("m9", body_text="LATER MAIL", date=now + timedelta(days=1)))
    f.put_email(UID, doc("x1", thread_id="other", body_text="OTHER THREAD", date=now - timedelta(days=3)))
    writes = len(f.writes)
    draft(c)
    prompt = ai.calls[0][1]
    assert ("Earlier in this thread (oldest first):\nFrom: Priya Shah <priya@example.com>\nAre you free this week?"
            "\n\nFrom: the user\nYes, any afternoon.\n\nEmail text:") in prompt
    assert "LATER MAIL" not in prompt and "OTHER THREAD" not in prompt
    draft(c, "m2")
    assert "Earlier in this thread" not in ai.calls[1][1]  # a thread of one
    assert len(f.writes) == writes


def test_thread_context_keeps_the_newest():
    earlier = [{"from": f"P{i}", "text": f"m{i} " + "z" * 900} for i in range(9)]
    blocks = reply_ai.thread_context(earlier)
    assert 0 < len(blocks) <= reply_ai.THREAD_MESSAGES and blocks[-1].startswith("From: P8\nm8")
    assert not any("m0 " in b for b in blocks)
    assert all(len(b) <= reply_ai.THREAD_EACH + 20 for b in blocks)
    assert len("".join(blocks)) <= reply_ai.THREAD_CHARS
    assert reply_ai.thread_context([{"from": "a", "text": " "}, None, "x"]) == []
    assert reply_ai.thread_context(None) == []


def test_no_body_uses_the_preview_and_no_name(env):
    c, _, ai = env
    draft(c, "m2")
    prompt = ai.calls[0][1]
    assert "Your order has shipped" in prompt and "The user's name: not given" in prompt


def test_automatic_mail_is_flagged(env, monkeypatch):
    c, _, _ = env
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI({"reply": "Thanks.", "needs_reply": False}))
    assert draft(c, "m2").json()["draft"]["needs_reply"] is False
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI({"reply": "Thanks.", "needs_reply": "no"}))
    assert draft(c, "m2").json()["draft"]["needs_reply"] is True  # only an explicit false


def test_failures_come_back_in_error(env, monkeypatch):
    c, _, _ = env
    busy = Exception("rate limited")
    busy.status_code = 429
    cases = [(FakeAI(raw="not json"), "Couldn't write a reply"), (FakeAI({"reply": "  "}), "Couldn't write a reply"),
             (FakeAI(error=busy), "busy"), (FakeAI(error=RuntimeError("down")), "unavailable")]
    for fake, message in cases:
        monkeypatch.setattr(personal_ai, "_client", lambda fake=fake: fake)
        r = draft(c)
        assert r.status_code == 200 and r.json()["draft"] is None and message in r.json()["error"]


def test_unknown_or_bad_email(env):
    c, _, ai = env
    assert draft(c, "nope").status_code == 404
    assert draft(c, "../x").status_code == 422
    assert c.post("/api/reply/draft?uid=../x&email_id=m1").status_code == 422
    assert c.post("/api/reply/draft?uid=u2&email_id=m1").status_code == 404  # another account's mail
    assert ai.calls == []


def test_clean_options():
    assert reply_ai.clean_options(["Yes, but Friday is better", "Decline"], "yes, but  Friday is better") == ["Decline"]
    assert reply_ai.clean_options("not a list") == []
    assert len(reply_ai.clean_options(["x" * 100])[0]) == 60


def test_strip_quoted_and_clean_reply():
    assert reply_ai.strip_quoted("Hi\n\n-----Original Message-----\nold") == "Hi"
    assert reply_ai.strip_quoted("Yes.\nOn Tue, Bob wrote:\n> no") == "Yes."
    assert reply_ai.strip_quoted("> quoted\nNew line") == "New line"
    assert reply_ai.clean_reply("Subject: Re: x\n\nSure.") == "Sure."
    assert reply_ai.clean_reply(None) == ""
    assert len(reply_ai.clean_reply("y" * 5000)) == reply_ai.MAX_CHARS
    long = reply_ai.prompt({"sender": "a", "subject": "b", "body_text": "x" * 9000})
    assert len(long) < reply_ai.TEXT_CHARS + 200
    assert "(no text, only the subject)" in reply_ai.prompt({"sender": "a", "subject": "b"})


def test_same_prompt_as_the_extension():
    """The extension's reply.js carries the same instructions, line for line."""
    from pathlib import Path
    js = (Path(__file__).resolve().parents[2] / "extension" / "src" / "reply.js").read_text()
    js = js.replace('" +\n    "', "").replace('" +\n    \'', "").replace("' +\n    '", "")
    for line in ("You write email replies for the user.", "Never make up facts, dates, times, prices, links",
                 "Formal: polite and professional, no slang or contractions", "Short: under 80 words",
                 "Detailed: 100 to 180 words", "Keep track of who asks whom", "do not pick: put them in square brackets", "reply to the newest email only", "Never choose a time, date or option for the user",
                 "build the reply around that and follow it over your own guess",
                 "If you are shown an earlier draft, the user wants a different one",
                 "other things the user might want to say instead",
                 "newsletters, receipts and automatic notices"):
        assert line in reply_ai._SYSTEM and line in js
