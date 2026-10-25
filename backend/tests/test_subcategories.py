"""Splitting a category into subcategories. The model is faked, so these run offline."""
import json
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fakefs import FakeDB

from app.services import firestore_client as fs
from app.services import personal_ai

NOW = datetime.now(timezone.utc)
UID = "u1"
JOBS = {"name": "Job hunt", "description": "emails about job applications, interviews and recruiters"}
SUGGESTION = [
    {"name": "Interviews", "description": "Interview invites and scheduling"},
    {"name": "Applications", "description": "Updates on applications I sent"},
    {"name": "Job alerts", "description": "Lists of new job openings"},
    {"name": "interviews", "description": "a repeat that should be dropped"},
    {"name": "Misc", "description": "a catch-all that should be dropped"},
]
KEYWORDS = {"interviews": "interview", "applications": "application", "job_alerts": "new jobs"}
SUBJECTS = ([f"Interview slot {n}" for n in range(4)] + [f"Application received {n}" for n in range(4)]
            + [f"New jobs for you {n}" for n in range(4)] + ["Recruiter call notes", "Recruiter follow up"])


class FakeAI:
    """Answers a split request with `suggestion` and a sort request by keyword."""

    def __init__(self, suggestion=SUGGESTION, error_on_sort=None, raw_suggest=None):
        self.suggestion, self.error_on_sort, self.raw_suggest = suggestion, error_on_sort, raw_suggest
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        system, prompt = kw["messages"][0]["content"], kw["messages"][1]["content"]
        split = system.startswith("You split one email category")
        self.calls.append((split, prompt))
        if split:
            content = self.raw_suggest if self.raw_suggest is not None else json.dumps({"subcategories": self.suggestion})
        else:
            if self.error_on_sort:
                raise self.error_on_sort
            ids = re.findall(r"- id: (\S+)", prompt)
            out = []
            for block in prompt.split("\n[")[1:]:
                i = int(block.split("]")[0])
                hit = next((c for c in ids if KEYWORDS.get(c, "\0") in block.lower()), None)
                out.append({"i": i, "category": hit or "none", "reason": f"Mentions {hit}" if hit else ""})
            content = json.dumps({"results": out})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def doc(id, days_ago=0, **kw):
    d = dict(id=id, thread_id="t", sender=f"S <{id}@x.com>", sender_email=f"{id}@x.com", sender_domain="x.com",
             subject="", snippet="PREVIEW TEXT", body_text="SECRET BODY", labels=[],
             date=NOW - timedelta(minutes=days_ago), category="other", confidence=0.3)
    d.update(kw)
    return d


@pytest.fixture
def env(monkeypatch):
    f = FakeDB()
    monkeypatch.setattr(fs, "db", lambda: f)
    ai = FakeAI()
    monkeypatch.setattr(personal_ai, "_client", lambda: ai)
    from app.main import app
    c = TestClient(app)
    c.post(f"/api/personal/categories?uid={UID}", json=JOBS)
    for n, subject in enumerate(SUBJECTS):
        f.put_email(UID, doc(f"j{n:02}", n, subject=subject, custom_category="job_hunt"))
    for n in range(8):
        f.put_email(UID, doc(f"p{n}", 100 + n, subject=f"{n}0% off", category="promotion"))
    return c, f, ai


def split(c, parent="my:job_hunt", uid=UID):
    return c.post(f"/api/personal/split?uid={uid}&parent={parent}")


def counts(view):
    return {**{s["id"]: s["count"] for s in view["items"]}, "other": view["other"]}


# ---------------------------------------------------------------- splitting

def test_split_suggests_and_sorts(env):
    c, _, ai = env
    r = split(c).json()
    assert r["error"] is None
    assert [s["name"] for s in r["items"]] == ["Interviews", "Applications", "Job alerts"]
    assert counts(r) == {"interviews": 4, "applications": 4, "job_alerts": 4, "other": 2}
    assert len(ai.calls) == 3  # one suggestion, then 14 emails ten at a time
    listed = c.get(f"/api/personal/subcategories?uid={UID}&parent=my:job_hunt").json()
    assert counts(listed) == counts(r)


def test_split_prompt_is_sender_and_subject_of_the_category_only(env):
    c, _, ai = env
    split(c)
    prompt = ai.calls[0][1]
    assert "Category: Job hunt" in prompt and JOBS["description"] in prompt
    assert "Interview slot 0" in prompt and "j00@x.com" in prompt
    assert "PREVIEW TEXT" not in prompt and "SECRET BODY" not in prompt
    assert "% off" not in prompt  # other mailboxes stay out
    assert "Interview invites and scheduling" in ai.calls[1][1]  # suggested descriptions drive the sort


def test_built_in_mailbox_can_be_split(env):
    c, _, _ = env
    r = split(c, parent="promotion").json()
    assert r["error"] is None and len(r["items"]) == 3
    assert sum(s["count"] for s in r["items"]) + r["other"] == 8


def test_too_few_emails_is_refused(env):
    c, _, ai = env
    r = c.post(f"/api/personal/split?uid={UID}&parent=receipt")
    assert r.status_code == 422 and "at least 6" in r.json()["detail"]
    assert ai.calls == []


def test_bad_or_unknown_parent(env):
    c, _, _ = env
    assert c.post(f"/api/personal/split?uid={UID}&parent=../x").status_code == 422
    assert c.post(f"/api/personal/split?uid={UID}&parent=my:nope").status_code == 404


def test_splits_are_per_account(env):
    c, _, _ = env
    split(c)
    assert c.get("/api/personal/subcategories?uid=u2&parent=my:job_hunt").json()["items"] == []


# ---------------------------------------------------------------- failures

def test_failed_sort_saves_nothing(env, monkeypatch):
    c, _, _ = env
    first = counts(split(c).json())
    busy = Exception("rate limited")
    busy.status_code = 429
    monkeypatch.setattr(personal_ai, "_client", lambda: FakeAI(error_on_sort=busy))
    r = split(c)
    assert r.status_code == 200 and r.json()["error"] == "The AI is busy (rate limit). Try again in a minute."
    assert counts(r.json()) == first  # the earlier split is still there, unchanged


def test_unusable_suggestions_mean_no_split(env, monkeypatch):
    c, _, _ = env
    for fake in (FakeAI(raw_suggest="not json"), FakeAI(suggestion=[{"name": "Only", "description": "one"}])):
        monkeypatch.setattr(personal_ai, "_client", lambda fake=fake: fake)
        r = split(c).json()
        assert r["error"] == "Couldn't find clear subcategories in these emails." and r["items"] == []


# ---------------------------------------------------------------- rename, delete, list

def test_rename(env):
    c, _, _ = env
    split(c)
    url = f"/api/personal/subcategories/job_alerts?uid={UID}&parent=my:job_hunt"
    r = c.patch(url, json={"name": "  Job   listings "})
    assert r.status_code == 200 and r.json()["items"][2] == {
        "id": "job_alerts", "name": "Job listings", "description": "Lists of new job openings", "count": 4}
    assert c.patch(url, json={"name": "INTERVIEWS"}).status_code == 409
    assert c.patch(url, json={"name": "x" * 31}).status_code == 422
    assert c.patch(f"/api/personal/subcategories/nope?uid={UID}&parent=my:job_hunt",
                   json={"name": "Fine"}).status_code == 404


def test_delete_returns_emails_to_other_and_last_one_ends_the_split(env):
    c, _, _ = env
    split(c)
    base = f"?uid={UID}&parent=my:job_hunt"
    r = c.delete(f"/api/personal/subcategories/interviews{base}").json()
    assert counts(r) == {"applications": 4, "job_alerts": 4, "other": 6}
    r = c.delete(f"/api/personal/subcategories/applications{base}").json()
    assert r["items"] == [] and fs.get_split(UID, "my:job_hunt") is None


def test_emails_of_a_subcategory_and_of_other(env):
    c, _, _ = env
    split(c)
    base = f"?uid={UID}&parent=my:job_hunt"
    rows = c.get(f"/api/personal/subcategories/interviews/emails{base}").json()
    assert [m["id"] for m in rows] == ["j00", "j01", "j02", "j03"]
    assert rows[0]["sub_reason"] == "Mentions interviews"
    other = c.get(f"/api/personal/subcategories/_other/emails{base}").json()
    assert [m["id"] for m in other] == ["j12", "j13"] and other[0]["sub_reason"] is None
    assert c.get(f"/api/personal/subcategories/nope/emails{base}").status_code == 404


def test_deleting_the_category_deletes_its_split(env):
    c, _, _ = env
    split(c)
    split(c, parent="promotion")
    c.delete(f"/api/personal/categories/job_hunt?uid={UID}")
    assert fs.get_split(UID, "my:job_hunt") is None
    assert fs.get_split(UID, "promotion") is not None


# ---------------------------------------------------------------- the checks on suggestions

def test_clean_subs():
    assert personal_ai.clean_subs(None) == []
    assert personal_ai.clean_subs([{"name": "A", "description": "a"}]) == []
    many = personal_ai.clean_subs([{"name": f"Group {n}", "description": "d"} for n in range(6)])
    assert len(many) == 4
    tidy = personal_ai.clean_subs([{"name": "  Big   deals ", "description": " x\n y "}, "junk",
                                   {"name": "Other", "description": "o"}, {"name": "Misc promotions", "description": "m"},
                                   {"name": "General updates", "description": "g"}, {"name": "Coupons", "description": ""},
                                   {"name": "Food", "description": "f"}])
    assert tidy == [{"id": "big_deals", "name": "Big deals", "description": "x y"},
                    {"id": "food", "name": "Food", "description": "f"}]
